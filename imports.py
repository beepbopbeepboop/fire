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

# How far up the tree a CPython source checkout is looked for. A `Lib/os.py`
# is never more than a couple of levels above a `Tools/<tool>/` entry file
# (`Lib` is a SIBLING of `Tools`, so the root is two levels up from
# `Tools/<tool>/x.py`), and a bound is what keeps this from walking a
# filesystem root on a pathologically deep checkout.
_CPYTHON_LIB_WALK = 8
# start dir -> detected `Lib` (or None). One `os.path.exists` per ancestor per
# DISTINCT start directory, memoized because `_module_candidate_paths` asks the
# same question once per imported module name.
_cpython_lib_cache: dict = {}


def cpython_lib_root(start_dir):
    """`start_dir`'s nearest ancestor's `Lib/` if that ancestor is a CPython
    source checkout, else None.

    A CPython checkout is recognised by `Lib/os.py` — `os` is the one module
    every CPython `Lib/` has, it is a top-level file rather than a package, and
    no ordinary project directory has a `Lib/os.py` in it. This is what lets a
    build whose ENTRY file lives in `Tools/` reach `Lib/`: `Lib` is a SIBLING of
    `Tools`, not an ancestor, so no upward walk from `Tools/c-analyzer/` ever
    arrives there — the whole reason `import argparse` used to degrade to a
    receiver stub from inside a CPython checkout (see
    “The compiler has no way to see CPython's `Lib/` from an entry file outside it”).

    One definition, used by both consumers that need the answer: this
    resolver's `_find` (which can only look along MOJO_PATH, so the directory
    has to be handed to it) and `emit_resolve._module_candidate_paths` (the
    inline importer's own importer-anchored search list)."""
    if not start_dir:
        return None
    key = os.path.realpath(start_dir)
    if key in _cpython_lib_cache:
        return _cpython_lib_cache[key]
    found = None
    d = key
    for _ in range(_CPYTHON_LIB_WALK):
        if not d or d == os.path.sep:
            break
        cand = os.path.join(d, 'Lib')
        if os.path.exists(os.path.join(cand, 'os.py')):
            # `realpath`, not the walked `d`: a checkout reached THROUGH a
            # symlinked `Lib` (a mirrored work tree, a bind mount, a
            # `ln -s` into a scratch dir) otherwise hands the search list a
            # second spelling of every module it contains, and the very next
            # import of one of them resolves through the walked ancestor to
            # the real path instead — the same module compiled twice into one
            # translation unit, which is the one-identity-per-name rule this
            # whole module exists to enforce (and `default_mojo_path` already
            # dedups on `realpath` for the same reason).
            found = os.path.realpath(cand)
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    _cpython_lib_cache[key] = found
    return found


def default_mojo_path():
    """The ordered search path, like sys.path. Because Mojo is a superset of
    Python, we honor both pathing env vars: **$MOJO_PATH first (ours wins)**, then
    $PYTHONPATH, then the project dir, the runtime test dir, and the stdlib root.
    Deduped, order preserved.

    `$PYTHONPATH` naming a CPython `Lib/` works only because `_find` probes the
    `.py` spelling too (see its own comment); before that it silently resolved
    nothing, which is worth stating because the env var looked like it should
    have been enough."""
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
        candidate if the name is provided more than once.

        Both `.mojo` AND `.py` spellings, because Mojo is a superset of Python
        and a `.py` file on the search path IS a provider — probing only
        `.mojo` made `$PYTHONPATH` useless for pointing at a CPython `Lib/`
        (`$PYTHONPATH=<checkout>/Lib` left `resolve_source('argparse')` at
        None), which is half of why a build whose entry file sits in a CPython
        checkout could not see `Lib/` at all: see
        “The compiler has no way to see CPython's `Lib/` from an entry file outside it”.

        Extension is the INNER priority and LOCATION the outer one, so a real
        match in a closer directory still wins over an unrelated same-named
        `.py` further along the path. That ordering is the same rule
        `emit_resolve._module_candidate_paths` already applies, and it is the
        one that matters here: `$PYTHONPATH` entries come first precisely so
        they can shadow, and `HERE`/`RUNTIME`/`STDLIB_PATH` (this compiler's
        own directories, whose `.py` files are its *implementation*) come last.

        Within one location a `.mojo` file still wins over a `.py` sibling: the
        self-hosted stdlib modules are the ones a compiled program means when it
        says `import std.io`, and a project that ships both has said which it
        wants."""
        rel = name.replace('.', os.sep)
        found, shadowed = None, None
        for d in self.path:
            for cand in (os.path.join(d, rel + '.mojo'),
                         os.path.join(d, rel, '__init__.mojo'),
                         os.path.join(d, rel + '.py'),
                         os.path.join(d, rel, '__init__.py')):
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
    # Only the source *path* is wanted (codegen parses it to find a struct/generic
    # definition). Do NOT go through resolve(), which builds the whole dylib — that
    # turns a parse into a recursive build of the module's entire import closure
    # (each in its own large-stack thread), which on the stdlib never terminates in
    # any reasonable time. If the module was already fully resolved, reuse its entry.
    r = get_resolver()
    if name in r._modules:
        return r._modules[name].source
    found, _shadowed = r._find(name)
    return found
