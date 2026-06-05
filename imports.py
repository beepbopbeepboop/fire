#!/usr/bin/env python3
"""imports.py — `import` is the seam (MODULE_CACHE_DESIGN.md).

Importing a module means: locate/build its dylib in the CAS, and wire symbol
resolutions to come from that dylib's `__mojo_reflect` table — the plain-C ABI.
`import X` is literally "make X's ABI available": dlopen the dylib (here via the
reflection table), resolve names through it.

Used by both sides of the boundary so they agree:
  * the codegen (link mode) gets imported signatures from the reflection ABI;
  * the driver links the client against the same dylib.
"""
import os

import cas
import build_stdlib_dylib as bsd
from build_config import find_gcc
from module_loader import ModuleLoader, read_reflection

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')


def resolve_source(module: str):
    """Resolve a module name to a `.mojo` source path (local or stdlib), or None."""
    cands = [os.path.join(HERE, module + '.mojo'),
             os.path.join(RUNTIME, module + '.mojo')]
    try:
        p = ModuleLoader().resolve_module_path(module)
        if p:
            cands.append(p)
    except Exception:
        pass
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _dylib_key(src: str, gcc: str, flags: tuple) -> str:
    return 'dylib/' + cas._hash(
        'mojo-dylib-v1', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags), src)


def module_dylib(module: str, gcc: str = None, flags: tuple = ()):
    """Build (or find in the CAS) the dylib for `module`; return its path or None.

    The dylib is content-addressed, so importing the same module anywhere reuses
    it — instantiate once, ever. Building on demand is how `import X` makes X's
    ABI available."""
    gcc = gcc or find_gcc()
    path = resolve_source(module)
    if not path:
        return None
    src = open(path).read()
    dylib = cas.path_for(_dylib_key(src, gcc, flags), '.dylib')
    if not os.path.exists(dylib):
        os.makedirs(os.path.dirname(dylib), exist_ok=True)
        try:
            bsd.build([path], dylib)
        except Exception:
            return None
    return dylib


def resolve(module: str, gcc: str = None, flags: tuple = ()):
    """The import seam in one call: return (dylib_path, exports), where exports is
    the module's ABI from its `__mojo_reflect` table. (None, {}) if unavailable.

    `import` records the returned dylib as a link dependency of the program, so the
    final binary links against every dylib its imports resolved through — the
    "report which dylibs provide resolutions, then link them all" design."""
    dylib = module_dylib(module, gcc, flags)
    if not dylib:
        return None, {}
    try:
        return dylib, read_reflection(dylib)
    except Exception:
        return dylib, {}


def import_exports(module: str, gcc: str = None, flags: tuple = ()) -> dict:
    """Just the ABI (see resolve)."""
    return resolve(module, gcc, flags)[1]
