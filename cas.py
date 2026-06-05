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
CAS_DIR = os.path.join(HERE, 'build', 'cas')

# Bump when ABI.md (the boundary contract) changes incompatibly.
ABI_VERSION = "1"

# Codegen sources whose content defines the compiler's output. Hashing these
# means "the compiler changed" ⇒ new keys ⇒ recompile, with zero manual version
# bumping. Keep this list complete: anything that changes generated C belongs here.
_COMPILER_SOURCES = [
    'gimple_codegen.py', 'mlir.py', 'module_loader.py',
    'generated_dispatch.py', 'mojo_compiler.py',
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
        for name in sorted(_COMPILER_SOURCES):
            path = os.path.join(HERE, name)
            try:
                with open(path, 'rb') as f:
                    h.update(name.encode())
                    h.update(f.read())
            except FileNotFoundError:
                h.update(b'\0missing:' + name.encode())
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


def module_key(source: str, imported_sigs, gcc: str, flags: tuple = ()) -> str:
    """The content key for compiling one module to an object artifact."""
    sigs = '\n'.join(sorted(imported_sigs or ()))
    return _hash(
        'mojo-cas-v1',
        ABI_VERSION,
        compiler_fingerprint(),
        toolchain_fingerprint(gcc, flags),
        source,
        sigs,
    )


def instantiation_key(template_id: str, type_args, comptime_args,
                      gcc: str, flags: tuple = ()) -> str:
    """Content key for a generic instantiation.  template_id is the template's
    canonical identity (its source); type_args / comptime_args are the concrete
    arguments.  Same key ⇒ same monomorphized output, so an instantiation is
    compiled once, ever, and shared across clients (MODULE_CACHE_DESIGN.md)."""
    ta = '\x1f'.join(f"{k}={v}" for k, v in sorted((type_args or {}).items()))
    ca = '\x1f'.join(f"{k}={v}" for k, v in sorted((comptime_args or {}).items()))
    return _hash(
        'mojo-inst-v1',
        ABI_VERSION,
        compiler_fingerprint(),
        toolchain_fingerprint(gcc, flags),
        template_id,
        ta,
        ca,
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
    os.makedirs(CAS_DIR, exist_ok=True)
    final = path_for(key, ext)
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
