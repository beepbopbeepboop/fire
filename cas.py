#!/usr/bin/env python3
"""Content-addressed artifact store — MODULE_CACHE_DESIGN.md stage 3 (tier 1).

A compiled artifact (a module's `.o`, later a dylib or a generic instantiation)
is named by a hash of **all** of its compile inputs. Same key ⇒ provably same
output, so a cache hit is safe and a miss is the only thing that ever runs the
compiler. This is the dup-tolerant tier: publish is a temp-write + atomic
`os.replace` (immutable, hash-named files never conflict — identical races just
overwrite identical bytes), reads are plain file reads / `mmap`. No coordination.

The KEY is the whole correctness story. It folds in everything that can change
the output:

  * ABI_VERSION       — the boundary contract (bump on any ABI.md change)
  * compiler fingerprint — hash of the codegen sources, so changing the compiler
                           auto-invalidates every artifact (no stale hits)
  * toolchain fingerprint — gcc identity/version + target platform + flags
  * the module source bytes (exact)
  * the imported signatures the module is compiled against (so a dependency's
    signature change invalidates its dependents)

Anything not in this list MUST NOT affect the output, or hits would be wrong.
"""
import os
import sys
import hashlib
import platform
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# The cache's final resting place: a shared, per-user store under ~/.gmojo
# (override the home with $GMOJO_HOME). Content-addressed, so it is safely shared
# across every project/client on the machine — instantiate once, ever.
#
# ~/.gmojo already hosts the JIT cache (~/.gmojo/jit), which is the *same concept*
# (content-keyed compiled artifacts) but a *different shape* (standalone
# executables, not relocatable objects/dylibs). Per "either cas or inside the
# other if same shaped": different shape ⇒ the CAS gets its own sibling namespace
# ~/.gmojo/cas, so a JIT executable and a CAS object can never be type-mismatched.
#
# Within the CAS, artifacts are further domain-separated by KIND
# (cas/module, cas/inst, cas/comptime). Keys carry a per-kind hash domain too, so
# a cross-kind type mismatch needs a true hash collision AND the kind subdirectory
# rules it out regardless. Same-shaped artifacts share a directory; different
# shapes never collide. Override CAS_DIR (e.g. in tests) to isolate.
GMOJO_HOME = os.environ.get('GMOJO_HOME') or os.path.expanduser('~/.gmojo')
CAS_DIR = os.path.join(GMOJO_HOME, 'cas')

# Bump when ABI.md (the boundary contract) changes incompatibly.
# v2 (2026-07): struct method C symbols are module-qualified
# (<module-qualifier>_Struct_method<overload-suffix>) instead of bare
# Struct_method — see ABI.md's "Functions and methods" section and
# STDLIB-BUGS.md. Every cached .ci/.o/dylib artifact under v1 is
# automatically invalidated (compile_key/stdlib_compile_key/dylib_link_key
# all fold in ABI_VERSION first), so no manual cache-clear step is needed.
ABI_VERSION = "2"

# Codegen sources whose content defines the compiler's output. Hashing these
# means "the compiler changed" ⇒ new keys ⇒ recompile, with zero manual version
# bumping, and (unlike the git SHA) it catches *uncommitted* edits during dev.
# Keep this list complete: anything that changes generated C / objects belongs
# here. The version (below) is the safety net if something is missing.
#
# The gimple_* family is auto-discovered (glob) rather than enumerated: the
# 2026-08 refactor split gimple_codegen.py into a dozen sibling modules, and
# forgetting to add a new one here silently served stale cached output for
# every edit to it (filed as BUG-2026-022 candidate by the box.3d/game AI).
# Auto-discovery makes "new compiler source file" self-registering.
_COMPILER_SOURCES = [
    'mlir.py', 'module_loader.py', 'ast_rewriter.py',
    'generated_dispatch.py', 'fire_compiler.py',
    'elaborate.py', 'monomorphize.py', 'comptime.py',
    'imports.py', 'reflect.py', 'build_stdlib_dylib.py',
    'version.py', 'build_config.py',
]
import glob as _glob
for _p in sorted(_glob.glob(os.path.join(HERE, 'gimple_*.py'))):
    _COMPILER_SOURCES.append(os.path.basename(_p))

# Runtime ABI: every cached object is compiled against this header (and links the
# runtime). A change to either MUST invalidate the cache, or stale objects link
# against a mismatched ABI. These live under runtime/, not next to the .py files.
_RUNTIME_SOURCES = [
    os.path.join('runtime', 'fire_runtime.h'),
    os.path.join('runtime', 'fire_runtime.c'),
]

# In-process hit/miss instrumentation (and reset for tests).
stats = {'hits': 0, 'misses': 0}


def reset_stats():
    stats['hits'] = 0
    stats['misses'] = 0


def _hash(*parts: bytes) -> str:
    h = hashlib.blake2b(digest_size=20)
    for p in parts:
        if isinstance(p, str):
            p = p.encode('utf-8')
        # length-prefix each part so concatenation is unambiguous
        h.update(len(p).to_bytes(8, 'little'))
        h.update(p)
    return h.hexdigest()


_compiler_fp_cache = None


def compiler_fingerprint() -> str:
    """Hash of the codegen sources — 'which compiler built this'."""
    global _compiler_fp_cache
    if _compiler_fp_cache is None:
        h = hashlib.blake2b(digest_size=20)
        for name in sorted(_COMPILER_SOURCES) + sorted(_RUNTIME_SOURCES):
            path = os.path.join(HERE, name)
            try:
                with open(path, 'rb') as f:
                    h.update(name.encode())
                    h.update(f.read())
            except FileNotFoundError:
                h.update(b'\0missing:' + name.encode())
        # Fold in the compiler version as a coarse epoch + safety net: a new
        # commit (or a dirty tree) bumps it, invalidating across versions even if
        # a relevant file were missing from the list above.
        try:
            import version as _v
            h.update(b'\0version:' + _v.version().encode())
        except Exception:
            pass
        _compiler_fp_cache = h.hexdigest()
    return _compiler_fp_cache


_toolchain_fp_cache = {}


def toolchain_fingerprint(gcc: str, flags: tuple = ()) -> str:
    """Hash of the toolchain + target: gcc identity/version, platform, flags."""
    key = (gcc, flags)
    if key not in _toolchain_fp_cache:
        try:
            ver = subprocess.run([gcc, '--version'], capture_output=True,
                                 text=True, timeout=10).stdout.splitlines()[0]
        except Exception:
            ver = gcc
        target = f"{platform.system()}/{platform.machine()}"
        _toolchain_fp_cache[key] = _hash(gcc, ver, target, '\x1f'.join(flags))
    return _toolchain_fp_cache[key]


def module_key(source: str, imported_sigs, gcc: str, flags: tuple = (),
               dep_fingerprint: str = '') -> str:
    """The content key for compiling one module to an object artifact.

    The returned key is `module/<hash>` — the `module/` segment domain-separates
    this artifact kind on disk so it can never be confused with an instantiation
    or comptime artifact (no type mismatch), and the hash is also kind-prefixed.

    `dep_fingerprint` folds in the *content* of every local module reachable
    from this one by following `from X import ...` (see
    build_stdlib_dylib._local_dep_fingerprint).  `imported_sigs` only carries a
    dependency's fn/def *signatures* — never a `comptime` constant's value,
    which gimple_codegen constant-folds straight into every importer's C, nor a
    re-export hop's own transitive content — so without this a regenerated
    `comptime` value in a transitively-imported module kept serving its
    previously-cached object (BUG-2026-032, box.3d/game)."""
    sigs = '\n'.join(sorted(imported_sigs or ()))
    parts = [
        'mojo-cas-v1-module',
        ABI_VERSION,
        compiler_fingerprint(),
        toolchain_fingerprint(gcc, flags),
        source,
        sigs,
    ]
    # Only extend the key material when there actually is a local-dep
    # fingerprint: a module with no local (non-stdlib) imports — every stdlib
    # module — keeps its existing `module/` cache entry, so introducing this
    # does not force a cold rebuild of the whole stdlib.
    if dep_fingerprint:
        parts.append(dep_fingerprint)
    return 'module/' + _hash(*parts)


def _inst_hash(domain: str, template_id: str, type_args, comptime_args,
               gcc: str, flags: tuple) -> str:
    ta = '\x1f'.join(f"{k}={v}" for k, v in sorted((type_args or {}).items()))
    ca = '\x1f'.join(f"{k}={v}" for k, v in sorted((comptime_args or {}).items()))
    return _hash(domain, ABI_VERSION, compiler_fingerprint(),
                 toolchain_fingerprint(gcc, flags), template_id, ta, ca)


def instantiation_key(template_id: str, type_args, comptime_args,
                      gcc: str, flags: tuple = ()) -> str:
    """Content key (`inst/<hash>`) for a generic instantiation. template_id is the
    template's canonical identity (its source); type_args / comptime_args are the
    concrete arguments. Same key ⇒ same monomorphized output, so an instantiation
    is compiled once, ever, and shared across clients (MODULE_CACHE_DESIGN.md)."""
    return 'inst/' + _inst_hash('mojo-inst-v1', template_id, type_args,
                                comptime_args, gcc, flags)


def comptime_key(fn_src: str, fn_name: str, gcc: str, flags: tuple = ()) -> str:
    """Content key (`comptime/<hash>`) for a comptime function compiled to a
    callable artifact — separated from runtime modules/instantiations so the two
    shapes (a callable dylib vs a linkable object) can never be type-mismatched."""
    return 'comptime/' + _inst_hash('mojo-comptime-v1', fn_src,
                                    {'fn': fn_name}, None, gcc, flags)


def file_digest(path: str) -> str:
    """Content hash of a file (a linked artifact, an object on a link line, …)."""
    with open(path, 'rb') as f:
        return _hash(f.read())


_stdlib_fp_cache = None


def stdlib_fingerprint() -> str:
    """Hash of every stdlib .mojo source — 'which stdlib was this compiled
    against'. Codegen resolves imports against the stdlib even when it isn't
    inlining them (extern signatures via load_module, generic definitions via
    _parsed_import, struct layouts), so any stdlib edit must invalidate cached
    codegen output. Deliberately coarse — one edit anywhere invalidates every
    key that folds this in — because over-invalidation only costs a recompile
    while under-invalidation serves wrong artifacts. Computed once per process."""
    global _stdlib_fp_cache
    if _stdlib_fp_cache is None:
        h = hashlib.blake2b(digest_size=20)
        try:
            from module_loader import STDLIB_PATH
            root = STDLIB_PATH if STDLIB_PATH and os.path.isdir(STDLIB_PATH) else None
        except Exception:
            root = None
        if root:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames.sort()
                for fname in sorted(filenames):
                    if fname.endswith('.mojo'):
                        p = os.path.join(dirpath, fname)
                        try:
                            with open(p, 'rb') as f:
                                h.update(os.path.relpath(p, root).encode())
                                h.update(f.read())
                        except OSError:
                            h.update(b'\0unreadable:' + p.encode())
        _stdlib_fp_cache = h.hexdigest()
    return _stdlib_fp_cache


def hash_parts(*parts) -> str:
    """Public wrapper around the internal length-prefixed hash, for callers
    outside this module that need a CAS-consistent key (e.g. checked_run.py's
    make-check result cache) without duplicating the hashing scheme."""
    return _hash(*parts)


def runtime_fingerprint() -> str:
    """Hash of just the runtime sources (fire_runtime.h/.c). For artifacts whose
    only compiler-side input is the runtime — e.g. a gcc syntax check of already-
    generated C, which #includes the header via -I — this is the right, narrow
    fingerprint: folding in compiler_fingerprint() instead would needlessly
    invalidate them on every codegen .py edit."""
    parts = []
    for name in _RUNTIME_SOURCES:
        try:
            with open(os.path.join(HERE, name), 'rb') as f:
                parts += [name, f.read()]
        except FileNotFoundError:
            parts += [name, b'\0missing']
    return _hash('mojo-runtime-fp-v1', *parts)


# ── Compile-to-GIMPLE keys ─────────────────────────────────────────────

def compile_key(source: str, do_imports: bool, filename: str = "",
                deps_digest: str = "") -> str:
    """Key (`compile/<hash>`) for caching compile_to_gimple output (.ci).

    Folds in the entry source, do_imports mode, filename, ABI_VERSION, the
    compiler fingerprint, and the stdlib fingerprint (imports are resolved
    against stdlib sources even when not inlined). `deps_digest` must cover
    every non-stdlib source the compile can read — the sibling-import closure
    (see gimple_codegen._dep_sources_digest) — so editing an imported file
    invalidates the cached .ci."""
    return 'compile/' + _hash(
        'mojo-compile-v1', ABI_VERSION, compiler_fingerprint(),
        stdlib_fingerprint(), source, 't' if do_imports else 'f',
        filename, deps_digest,
    )


def stdlib_compile_key(source: str, path: str, module_name: str) -> str:
    """Key (`stdlib-compile/<hash>`) for caching compile_module_to_c output (.ci).

    Covers the module source, its file path, its module name, the compiler
    fingerprint, and the stdlib fingerprint — a stdlib module's generated C
    depends on its imports' signatures/layouts, and those imports are
    themselves stdlib modules, so the whole-stdlib fingerprint covers the
    closure without tracing it."""
    return 'stdlib-compile/' + _hash(
        'mojo-stdlib-compile-v1', ABI_VERSION, compiler_fingerprint(),
        stdlib_fingerprint(), source, path, module_name,
    )


def gcc_syntax_key(gcc_variant: str, flags: tuple, c_source: str) -> str:
    """Key (`gcc-syntax/<hash>`) for caching gcc -fsyntax-only results.

    Folds in the toolchain fingerprint (gcc version, platform, flags), the
    runtime fingerprint (the C #includes fire_runtime.h via -I), and the C
    source — so a gcc upgrade or a runtime-header edit invalidates stale
    syntax-check results."""
    return 'gcc-syntax/' + _hash(
        'mojo-gcc-syntax-v1',
        toolchain_fingerprint(gcc_variant, flags),
        runtime_fingerprint(),
        c_source,
    )


def dylib_link_key(obj_paths: list, reflect_src: str,
                   gcc: str, undefined: bool,
                   extra_digest: str = '') -> str:
    """Key (`dylib-link/<hash>`) for caching the final stdlib dylib link (.dylib).

    Folds in the content digest of every .o on the link line, the reflection
    table source, the toolchain, and the link-mode flag — so changing ANY
    object or the link configuration invalidates the cached dylib.
    `extra_digest` folds in content that is not in obj_paths (e.g. a
    separately-linked runtime dylib)."""
    obj_digests = '\0'.join(
        f'{os.path.basename(p)}={file_digest(p)}'
        for p in sorted(obj_paths)
    )
    return 'dylib-link/' + _hash(
        'mojo-dylib-link-v1', ABI_VERSION, compiler_fingerprint(),
        toolchain_fingerprint(gcc, ()), obj_digests, reflect_src,
        'undef' if undefined else 'defined', extra_digest,
    )


def path_for(key: str, ext: str = '.o') -> str:
    return os.path.join(CAS_DIR, key + ext)


def lookup(key: str, ext: str = '.o'):
    """Return the artifact path on a cache hit, else None."""
    p = path_for(key, ext)
    return p if os.path.exists(p) else None


def publish(key: str, ext: str, data: bytes) -> str:
    """Atomically install bytes as the artifact for `key`. Hash-named files are
    immutable, so a racing identical write is harmless (`os.replace` is atomic)."""
    final = path_for(key, ext)
    os.makedirs(os.path.dirname(final), exist_ok=True)   # per-kind subdir
    tmp = f"{final}.tmp.{os.getpid()}.{os.urandom(4).hex()}"
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, final)   # atomic publish
    return final


def get_or_build(key: str, ext: str, build_fn) -> tuple:
    """Return (artifact_path, hit). On a miss, `build_fn()` must return the
    artifact bytes; they are published atomically and the path returned."""
    p = lookup(key, ext)
    if p is not None:
        stats['hits'] += 1
        return p, True
    stats['misses'] += 1
    data = build_fn()
    return publish(key, ext, data), False


def get_or_build_text(key: str, ext: str, build_fn, l1: dict = None) -> str:
    """Text-artifact variant of get_or_build: returns the artifact *content*
    (str). On a miss, `build_fn()` must return the text; it is published
    atomically. `l1` is an optional caller-owned in-process dict consulted
    before the CAS, so repeated same-key calls in one process skip file I/O."""
    if l1 is not None and key in l1:
        return l1[key]
    p = lookup(key, ext)
    if p is not None:
        stats['hits'] += 1
        with open(p) as f:
            text = f.read()
    else:
        stats['misses'] += 1
        text = build_fn()
        publish(key, ext, text.encode('utf-8'))
    if l1 is not None:
        l1[key] = text
    return text
