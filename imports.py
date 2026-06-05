#!/usr/bin/env python3
"""imports.py — the module-resolution authority (MODULE_CACHE_DESIGN.md).

`import` is the seam, and *identity* is the rule that makes it safe. Like
CPython's `sys.modules`, a build has **exactly one module per fully-qualified
name**: the first resolution along a single ordered `MOJO_PATH` wins, is cached,
and is shared by every importer (the client and, transitively, every module).
So `import io` denotes one `io` everywhere — two different `io`s can't coexist,
which is the whole point.

Resolving a module also: builds/finds its content-addressed dylib (CAS), reads
its `__mojo_reflect` ABI, and lets the caller record that dylib on the program's
link line. The loader then binds the symbols — we don't reinvent dyld.
"""
import os
import sys

import cas
import build_stdlib_dylib as bsd
from build_config import find_gcc
from module_loader import read_reflection

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')


def default_mojo_path():
    """The ordered search path, like sys.path. Because Mojo is a superset of
    Python, we honor both pathing env vars: **$MOJO_PATH first (ours wins)**, then
    $PYTHONPATH, then the project dir, the runtime test dir, and the stdlib root.
    Deduped, order preserved."""
    parts = []
    for var in ('MOJO_PATH', 'PYTHONPATH'):     # ours preferred, then Python's
        env = os.environ.get(var)
        if env:
            parts += [d for d in env.split(os.pathsep) if d]
    parts += [HERE, RUNTIME]
    try:
        from module_loader import STDLIB_PATH
        if STDLIB_PATH and os.path.isdir(STDLIB_PATH):
            parts.append(STDLIB_PATH)
    except Exception:
        pass
    seen, out = set(), []
    for d in parts:
        rd = os.path.realpath(d)
        if rd not in seen:
            seen.add(rd)
            out.append(d)
    return out


class ModuleEntry:
    """One resolved module: its identity (fully-qualified name), canonical source,
    dylib, and reflection ABI. The dylib/exports are absent if it didn't resolve."""
    __slots__ = ('name', 'source', 'dylib', 'exports')

    def __init__(self, name, source, dylib, exports):
        self.name = name
        self.source = source
        self.dylib = dylib
        self.exports = exports

    @property
    def symbol_prefix(self):
        """Identity as a C symbol prefix: std.io -> std_io. Distinct names get
        distinct prefixes, so a local `io` and `std.io` never collide."""
        return self.name.replace('.', '_')


class Resolver:
    """The module-resolution authority for one build — our `sys.modules`.

    One ordered MOJO_PATH; one module per fully-qualified name; first match wins
    and is cached, so every importer shares the same module. Shadowed candidates
    on the path are reported (first-wins, Python-style) rather than silently
    producing two different modules with the same name.
    """

    def __init__(self, path=None, gcc=None, flags=()):
        self.path = list(path) if path is not None else default_mojo_path()
        self.gcc = gcc or find_gcc()
        self.flags = tuple(flags)
        self._modules = {}     # fqname -> ModuleEntry  (the sys.modules analog)

    def resolve(self, name: str) -> ModuleEntry:
        if name in self._modules:
            return self._modules[name]
        source, shadowed = self._find(name)
        if shadowed:
            sys.stderr.write(
                f"# import note: {name!r} resolved to {source} "
                f"(shadows {shadowed}); first on MOJO_PATH wins\n")
        dylib, exports = None, {}
        if source:
            dylib = self._dylib(source)
            if dylib:
                try:
                    exports = read_reflection(dylib)
                except Exception:
                    exports = {}
        entry = ModuleEntry(name, source, dylib, exports)
        self._modules[name] = entry        # identity fixed for the rest of the build
        return entry

    def _find(self, name: str):
        """First file providing `name` along MOJO_PATH, plus the first shadowed
        candidate if the name is provided more than once."""
        rel = name.replace('.', os.sep)
        found, shadowed = None, None
        for d in self.path:
            for cand in (os.path.join(d, rel + '.mojo'),
                         os.path.join(d, rel, '__init__.mojo')):
                if os.path.exists(cand):
                    if found is None:
                        found = cand
                    elif shadowed is None and \
                            os.path.realpath(cand) != os.path.realpath(found):
                        shadowed = cand
                    break
        return found, shadowed

    def _dylib(self, source: str):
        src = open(source).read()
        # Fold in the module's imported signatures (review finding #2): they are
        # baked into the generated C as extern decls, so a dependency's signature
        # change must invalidate this dylib even when its own source is unchanged
        # — mirroring cas.module_key.
        sigs = '\n'.join(sorted(bsd._imported_sigs(src)))
        key = 'dylib/' + cas._hash(
            'mojo-dylib-v1', cas.ABI_VERSION, cas.compiler_fingerprint(),
            cas.toolchain_fingerprint(self.gcc, self.flags), src, sigs)
        dylib = cas.path_for(key, '.dylib')
        if not os.path.exists(dylib):
            os.makedirs(os.path.dirname(dylib), exist_ok=True)
            try:
                bsd.build([source], dylib)
            except Exception:
                return None
        return dylib


# ── Process-global authority (our sys.modules), shared by codegen + driver ──

_RESOLVER = None


def get_resolver() -> Resolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = Resolver()
    return _RESOLVER


def reset_resolver(path=None, gcc=None, flags=()):
    """Start a fresh authority (e.g. a new build, or tests with a temp MOJO_PATH)."""
    global _RESOLVER
    _RESOLVER = Resolver(path=path, gcc=gcc, flags=flags)
    return _RESOLVER


# Thin name-keyed accessors — all go through the one authority.
def resolve(name: str) -> ModuleEntry:
    return get_resolver().resolve(name)


def module_dylib(name: str, gcc=None, flags=()):
    return get_resolver().resolve(name).dylib


def import_exports(name: str, gcc=None, flags=()) -> dict:
    return get_resolver().resolve(name).exports


def resolve_source(name: str):
    return get_resolver().resolve(name).source
