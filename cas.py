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
# here. The version (below) is the safety net if something is missing — but it
# only bumps on a *tracked* git change, so an untracked new source file is
# invisible to it; auto-discovery below is what actually catches those.
#
# The gimple_* family is auto-discovered (glob) rather than enumerated: the
# 2026-08 refactor split gimple_codegen.py into a dozen sibling modules, and
# forgetting to add a new one here silently served stale cached output for
# every edit to it (filed as BUG-2026-022 candidate by the box.3d/game AI).
# Auto-discovery makes "new compiler source file" self-registering.
#
# The 2026-09 restructure then moved the real implementation OUT of those
# gimple_*.py files into mojo/middle/ + mojo/backend_gimple/, leaving the
# gimple_*.py names as thin re-export shims (later deleted 2026-09-23; only
# root gimple_codegen.py remains). Hashing only the shims meant an
# edit to e.g. mojo/middle/resolve_shared.py left compiler_fingerprint()
# *unchanged* (confirmed: append a line, fp identical) while editing the
# empty shim changed it — every real codegen edit was invisible to the CAS
# and served stale .ci/.o. The mojo/** glob below closes that hole the same
# way the gimple_* glob closed the 2026-08 one.
_COMPILER_SOURCES = [
    'mlir.py', 'module_loader.py', 'ast_rewriter.py',
    'generated_dispatch.py', 'fire_compiler.py',
    'elaborate.py', 'monomorphize.py', 'comptime.py',
    'imports.py', 'reflect.py', 'build_stdlib_dylib.py',
    'version.py', 'build_config.py',
    # Root-level codegen-path deps (imported by gimple_codegen / mojo/* but
    # living outside the gimple_*.py and mojo/ globs below). Omitting them
    # had the same silent-stale-cache failure mode as the mojo/ gap:
    # ownership_destruct decides which locals get destructors emitted,
    # regex_compile drives pattern-recognition in the middle end, and
    # ownership_check's diagnostics gate real emission paths.
    'ownership_check.py', 'ownership_destruct.py', 'regex_compile.py',
]
import glob as _glob
for _p in sorted(_glob.glob(os.path.join(HERE, 'gimple_*.py'))):
    _COMPILER_SOURCES.append(os.path.basename(_p))
# The actual compiler implementation (post-2026-09 package split). Paths are
# repo-relative with forward slashes so the fingerprint is host-OS-stable.
for _p in sorted(_glob.glob(os.path.join(HERE, 'mojo', '**', '*.py'),
                            recursive=True)):
    if '__pycache__' in _p.split(os.sep):
        continue
    _COMPILER_SOURCES.append(os.path.relpath(_p, HERE).replace(os.sep, '/'))

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


# ── The self-host closure: a different, LARGER input set ────────────────────
# `compiler_fingerprint()` above is the right key for a *stdlib module's*
# codegen, and it is deliberately not a superset of everything: fire.py,
# fire_main.py and myinterpreter.py are the compiler's own source, and no
# stdlib module's generated C depends on them.
#
# Anything that COMPILES THE COMPILER is the other case. `fire.py --dump-full
# fire.py`, `fire.py build fire.py`, and therefore `mojoc` and `stage2/mojo`,
# all read those three files, so a key built only from _COMPILER_SOURCES would
# be UNSOUND for them: edit myinterpreter.py, get a cache hit, and serve a
# binary built from the old interpreter. That is the worst possible failure for
# a build cache — wrong output, cached, and quiet — so the set is spelled out
# explicitly and then CHECKED (see `selfhost_closure_is_complete`).
#
# The list is a superset-by-enumeration, not a live import walk, because a walk
# would silently change meaning as the code moves. The check below is what
# keeps the enumeration honest.
_SELFHOST_EXTRA = [
    'fire.py',            # the CLI/entry point everything is dumped through
    'fire_main.py',
    'myinterpreter.py',   # the interpreter the self-hosted closure embeds
    'driver.py',          # link-mode's entry, read by fire.py build
    'build_mojo_cli.py',
    'elaborate.py',       # already in _COMPILER_SOURCES; named for clarity
    # Reached by the import walk in `selfhost_closure_is_complete`, so named
    # here for that check to stay silent. Whether each one can actually change
    # the emitted code is not the question being asked — a build cache that is
    # too narrow is wrong and a build cache that is too wide only costs a
    # rebuild, so every module the closure touches is hashed and none is
    # second-guessed. (cas.py is in its own closure: it is this file.)
    'cas.py',
    'determinism_trace.py',
    'jit/arm64.py',
]

_selfhost_fp_cache = None


def selfhost_inputs() -> list:
    """Every file whose content can change what the compiler emits about
    ITSELF — the input set for `mojoc`, `stage2/mojo`, and the
    whole-closure `--dump-full` dumps."""
    seen, out = set(), []
    for name in list(_COMPILER_SOURCES) + _SELFHOST_EXTRA:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return sorted(out) + sorted(_RUNTIME_SOURCES)


def selfhost_fingerprint() -> str:
    """Hash of the self-host input set — 'which compiler compiled the
    compiler'. Distinct from `compiler_fingerprint()`; see above for why, and
    `selfhost_closure_is_complete` for what keeps the list honest."""
    global _selfhost_fp_cache
    if _selfhost_fp_cache is None:
        h = hashlib.blake2b(digest_size=20)
        for name in selfhost_inputs():
            path = path if (path := os.path.join(HERE, name)) else path
            try:
                with open(path, 'rb') as f:
                    h.update(name.encode())
                    h.update(f.read())
            except (FileNotFoundError, NotADirectoryError):
                h.update(b'\0missing:' + name.encode())
        try:
            import version as _v
            h.update(b'\0version:' + _v.version().encode())
        except Exception:
            pass
        _selfhost_fp_cache = h.hexdigest()
    return _selfhost_fp_cache


def selfhost_closure_is_complete(entry: str = 'fire.py') -> tuple:
    """Walk `entry`'s repo-local imports transitively; return (missing, seen).

    `missing` is the set of files the walk reaches that
    `selfhost_fingerprint()` does NOT hash. An empty set is the invariant that
    makes the self-host cache keys sound; a non-empty one means a new module
    was imported without being added to `_SELFHOST_EXTRA`, and every cached
    self-host artifact is now suspect. Checked by test_suite.py, because the
    failure it prevents is silent and catastrophic rather than loud.

    Deliberately a syntactic walk of `import X` / `from X import` at module
    level and inside `def`/`try` bodies — not a resolved one. A resolved walk
    would need the import to actually succeed, which means executing the
    compiler, which is not something a key-completeness check should do. The
    over-approximation is the safe direction: a file reached only inside a
    function is still hashed, so the key is never narrower than the truth.
    """
    import re
    known = set(selfhost_inputs())
    pat = re.compile(r'^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|'
                     r'import\s+([A-Za-z_][\w.]*))', re.M)
    missing, seen = set(), set()
    queue = [(None, entry)]               # (module, path) — the entry is a path
    while queue:
        mod, path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        if path not in known:
            missing.add(path)
        try:
            with open(os.path.join(HERE, path), 'r', errors='replace') as f:
                src = f.read()
        except OSError:
            continue
        for line in src.splitlines():
            m = pat.match(line)
            for grp in (m.group(1), m.group(2)) if m else ():
                if not grp:
                    continue
                dotted = grp.replace('.', os.sep)
                for cand in (dotted + '.py',
                             os.path.join(dotted, '__init__.py')):
                    if os.path.isfile(os.path.join(HERE, cand)):
                        queue.append((grp, cand))
                        break
    return missing, seen


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


# The formal (arm64 + Mach-O) backend's own inputs. Deliberately NOT folded
# into compiler_fingerprint(): a formal artifact does not depend on the gimple
# codegen, the C runtime or gcc at all, so putting these in the shared list
# would invalidate every cached module object on every formal tweak.
#
# Auto-discovered for the same reason gimple_*.py is: a NEW formal/*.py has to
# self-register, or editing it would silently keep serving stale verdicts (the
# exact failure mode documented for gimple_*.py above). mojo/middle/** is
# globbed because formal/*.py reaches into it (boundnames, closures, and their
# own imports) — it is a subtree rather than an enumeration for that reason.
_FORMAL_SOURCES = ['fire.py', 'fire_compiler.py']
for _p in sorted(_glob.glob(os.path.join(HERE, 'formal', '**', '*.py'),
                            recursive=True)):
    if '__pycache__' in _p.split(os.sep):
        continue
    _FORMAL_SOURCES.append(os.path.relpath(_p, HERE).replace(os.sep, '/'))
for _p in sorted(_glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))):
    if '__pycache__' in _p.split(os.sep):
        continue
    _FORMAL_SOURCES.append(os.path.relpath(_p, HERE).replace(os.sep, '/'))

_formal_fp_cache = None


def formal_fingerprint() -> str:
    """Hash of the sources a `build --formal` run reads: fire.py's dispatch,
    the parser, formal/** and the mojo/middle subtree. Narrow on purpose —
    see _FORMAL_SOURCES."""
    global _formal_fp_cache
    if _formal_fp_cache is None:
        # Deliberately the same shape as runtime_fingerprint() below, down to
        # the absence of a `set(...)`: the two globs that build _FORMAL_SOURCES
        # are already sorted and disjoint, so the set bought nothing — and
        # handing the static backends a set where they build a list is what
        # made this fail the self-host compile with "passing argument 1 of
        # 'mojo_list_len' makes pointer from integer without a cast".
        parts = []
        for name in sorted(_FORMAL_SOURCES):
            try:
                with open(os.path.join(HERE, name), 'rb') as f:
                    parts += [name, f.read()]
            except (FileNotFoundError, IsADirectoryError):
                parts += [name, b'\0missing']
        _formal_fp_cache = _hash('mojo-formal-fp-v1', *parts)
    return _formal_fp_cache


# ── Compile-to-GIMPLE keys ─────────────────────────────────────────────

def compile_key(source: str, do_imports: bool, filename: str = "",
                deps_digest: str = "", auto_gpu: bool = True) -> str:
    """Key (`compile/<hash>`) for caching compile_to_gimple output (.ci).

    Folds in the entry source, do_imports mode, filename, ABI_VERSION, the
    compiler fingerprint, and the stdlib fingerprint (imports are resolved
    against stdlib sources even when not inlined). `deps_digest` must cover
    every non-stdlib source the compile can read — the sibling-import closure
    (see gimple_codegen._dep_sources_digest) — so editing an imported file
    invalidates the cached .ci.

    `auto_gpu` is in the key because it changes the OUTPUT, not just how it
    is produced: with it False, a recognised parallel loop nest gets no
    synthesised device kernel, so the .ci has a different function set and a
    different MSL sidecar. Leaving it out would serve a cached GPU build to a
    `--no-gpu` request, which is exactly the silent-wrong-output class this
    cache exists to avoid."""
    # The auto-offload trip-count floor is in the key for the same reason
    # `auto_gpu` is: it changes the OUTPUT, because it decides whether the
    # host keeps its loop or gains a dispatch. Measured, not reasoned about --
    # with the floor at 0 a two-call program dispatched twice, and re-running
    # it with the floor at 90000 served the CACHED floor-0 binary and still
    # dispatched twice, because nothing in the key had moved. An override that
    # silently does nothing is worse than no override.
    return 'compile/' + _hash(
        'mojo-compile-v1', ABI_VERSION, compiler_fingerprint(),
        stdlib_fingerprint(), source, 't' if do_imports else 'f',
        filename, deps_digest, 'gpu' if auto_gpu else 'nogpu',
        'minel:' + os.environ.get('MOJO_OFFLOAD_MIN_ELEMENTS', ''),
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


def formal_build_key(source: str, path: str, flags: tuple = (),
                     criteria: str = '') -> str:
    """Key (`formal/<hash>`) for caching one `build --formal` VERDICT.

    The same contract as every other key here — ABI version + a compiler-source
    fingerprint + a toolchain + the exact source bytes — specialised for the
    formal backend, which has no gcc and resolves no imports:

      * "compiler" is formal_fingerprint() (formal/**, the parser, mojo/middle);
      * "toolchain" is the Python interpreter that runs the in-process arm64
        emitter, plus the flags, since the emitted code depends on both;
      * "imported signatures" do not exist here — compile_formal compiles one
        file and skips its import statements, so a stdlib edit cannot change
        this artifact and stdlib_fingerprint() is deliberately not folded in.

    `path` only enters the key through the source it names, but is kept for
    diagnostics in the store. `flags` must carry every build flag that changes
    the output (`--no-prove`; `-n` as well, since the entry argument is baked
    into the startup stub).

    `criteria` identifies whatever is DECIDING pass/fail — for the sweep that
    is the tool's own source. A verdict is a function of the source AND the
    rules applied to it, so a tool that tightens its checks (here: also
    requiring the image's imports to be dyld-resolvable) must invalidate every
    entry it previously wrote, or it keeps serving verdicts its own current
    rules would no longer produce.
    """
    return 'formal/' + _hash(
        'mojo-cas-v1-formal',
        ABI_VERSION,
        formal_fingerprint(),
        toolchain_fingerprint(sys.executable, flags),
        source,
        criteria,
    )


def dylib_link_key(obj_paths: list, reflect_src: str,
                   gcc: str, undefined: bool,
                   extra_digest: str = '', arch: str = '') -> str:
    """Key (`dylib-link/<hash>`) for caching the final stdlib dylib link (.dylib).

    Folds in the content digest of every .o on the link line, the reflection
    table source, the toolchain, the link-mode flag, and the target
    architecture — so changing ANY object or configuration invalidates the
    cached dylib.
    `extra_digest` folds in content that is not in obj_paths (e.g. a
    separately-linked runtime dylib).

    `arch` is a key input in its own right and not merely something the
    per-object flags already carry, because the LINK invocation has its own
    target flag and nothing about the objects distinguishes a link that
    honoured it from one that ignored it. On the toolchain this tree is
    configured with, `-arch x86_64` is accepted, warned about, and ignored
    (see build_stdlib_dylib.arch_flags), so without the arch in the key two
    builds for different architectures would share one entry and the second
    would be served the first's bytes. `toolchain_fingerprint` above folds the
    HOST, which is the wrong fact for this purpose for the same reason."""
    obj_digests = '\0'.join(
        f'{os.path.basename(p)}={file_digest(p)}'
        for p in sorted(obj_paths)
    )
    return 'dylib-link/' + _hash(
        'mojo-dylib-link-v2', ABI_VERSION, compiler_fingerprint(),
        toolchain_fingerprint(gcc, ()), obj_digests, reflect_src,
        'undef' if undefined else 'defined', extra_digest, arch or '',
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
