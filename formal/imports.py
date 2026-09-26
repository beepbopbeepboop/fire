"""Import resolution for the formal backends: source → dylib → link line.

The formal path compiles ONE file and, until this module, silently ignored
every `import`. That is worse than an error: an ignored import leaves the
calls it implies as BLs against symbols nothing defines, so the program builds
and then dies in dyld at launch. This turns the import into what it means — a
dependency — by resolving the module, compiling its WHOLE source into a dylib
that represents it, and handing the link step that dylib.

"Whole source" is the point, and it is deliberate. A module dylib is a
*representation of a source file*, not a cache of the call sites that happened
to need it: the function this program never mentions still has to be in there,
compiled and exported, because the next module that imports the same file will
link against exactly this artifact and expect it. Building only the referenced
functions would make the artifact depend on who asked for it — the same source
compiled twice, two different libraries, and a symbol that exists in one and
not the other depending on which program triggered the build. So: one module in
⇒ every public function it defines, exported per doc/ABI.md.

Everything is content-addressed (cas.formal_build_key), so a module is compiled
once per (source, compiler, dependency-closure) and shared by every program
that imports it.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cas
import fire_compiler as F

from formal.build import ImportBuildError  # noqa: E402  (cycle-free: build
# imports this module lazily, inside the function)

# Built module dylibs this process has already produced, keyed by resolved
# path, so a program importing the same module twice (or a cycle) reuses it.
_BUILT: dict = {}


# CPython's standard library. These have no Mojo source and no symbol the
# formal model could bind, so a file importing one cannot be built here — but
# that is a statement about the target, not a module-resolution failure.
HOST_MODULES = frozenset((
    "os", "sys", "ast", "json", "re", "argparse", "dataclasses", "typing",
    "collections", "itertools", "functools", "math", "random", "time",
    "pathlib", "subprocess", "shutil", "textwrap", "inspect", "abc", "enum",
    "io", "csv", "copy", "pickle", "struct", "threading", "socket", "glob",
    "hashlib", "base64", "urllib", "http", "unittest", "logging", "warnings",
    "importlib", "importlib.util", "importlib.machinery", "contextlib",
    "traceback", "gc", "atexit", "signal", "errno", "stat", "platform",
    "tempfile", "uuid", "zlib", "gzip", "codecs", "locale", "getpass",
    "webbrowser", "unittest.mock", "difflib", "fnmatch", "operator",
    "heapq", "bisect", "array", "numbers", "decimal", "fractions", "secrets",
    "select", "queue", "weakref", "types", "dis", "pprint", "reprlib",
))


def _is_host_module(name: str) -> bool:
    return name in HOST_MODULES or name.split(".")[0] in HOST_MODULES


def _manifest_path(dylib_path: str) -> str:
    from formal.build import dylib_manifest_path
    return dylib_manifest_path(dylib_path)


def imported_modules(stmts) -> list:
    """The module names a statement list imports, in source order, deduped.

    `import a.b`, `import a.b as c` and `from a.b import x, y` all name the
    module `a.b`; the alias and the imported names do not change which module
    has to be built. `extra` carries `import a, b, c`'s additional names.
    """
    out = []
    for st in stmts or []:
        if isinstance(st, F.ImportStmt):
            names = [st.module]
            for mod, _alias in (st.extra or []):
                names.append(mod)
            for m in names:
                if isinstance(m, str) and m and m not in out:
                    out.append(m)
        elif isinstance(st, F.FromImportStmt):
            m = st.module
            if isinstance(m, str) and m and m not in out:
                out.append(m)
    return out


def _search_roots(relative_to: str, project_root: str) -> list:
    """Directories a module name is looked for in, nearest first.

    A module inside a package importing a sibling of the PACKAGE (not of
    itself) is ordinary code, not a mistake: `pkg/__init__.mojo` doing
    `from leaf import base` while `leaf.mojo` sits beside `pkg/`. So the walk
    goes from the importing file's own directory up towards the project root
    — the directory of the program being compiled — and stops there. It does
    NOT continue past the project root: an unbounded walk would happily
    resolve `import math` to some unrelated ~/math.mojo, which is far worse
    than failing to find it. A file under the stdlib also gets the stdlib
    root, so stdlib modules resolve each other."""
    roots = []
    if relative_to:
        here = os.path.dirname(os.path.abspath(relative_to))
        # project_root is normally the path of the file being compiled, so
        # normalise it to a directory — comparing against a filename would
        # never match a walk that stops at directories.
        top = os.path.abspath(project_root) if project_root else None
        if top and not os.path.isdir(top):
            top = os.path.dirname(top)
        d = here
        # Ascending from `here` towards `top`: while d is below top we keep
        # going; when d IS top we take it and stop; and if d is a strict
        # ANCESTOR of top we have overshot the project root and must stop
        # there — continuing would search the whole filesystem, where
        # `import math` could bind to an unrelated ~/math.mojo.
        unlimited = 8
        while True:
            if top:
                if d == top:
                    roots.append(d)
                    break
                if top.startswith(d + os.sep):
                    break                       # overshot the project root
            roots.append(d)
            parent = os.path.dirname(d)
            if parent == d:
                break
            if not top:
                unlimited -= 1
                if unlimited <= 0:
                    break                          # no project root: bounded
            d = parent
    try:
        import module_loader
        stdlib = getattr(module_loader, "STDLIB_PATH", None)
        if stdlib and (not relative_to or
                       os.path.abspath(relative_to).startswith(
                           os.path.abspath(stdlib) + os.sep)):
            roots.append(os.path.abspath(stdlib))
    except Exception:
        pass
    seen, out = set(), []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def resolve_module_path(module_name: str, relative_to: str = None,
                        project_root: str = None) -> str:
    """The source file for `module_name`, or None if it cannot be resolved.

    Delegates to module_loader for the stdlib (`std.memory` →
    `.../stdlib/std/memory/__init__.mojo`) after looking beside the importing
    file, so a local multi-file project works without being under the stdlib
    root. A module is either `<name>.mojo` or a package directory
    `<name>/__init__.mojo` — the same two shapes module_loader resolves."""
    rel = module_name.replace(".", os.sep)
    leaf = module_name.split(".")[-1]
    for base in _search_roots(relative_to, project_root):
        for cand in (os.path.join(base, rel + ".mojo"),
                     os.path.join(base, rel, "__init__.mojo"),
                     os.path.join(base, leaf + ".mojo"),
                     os.path.join(base, leaf, "__init__.mojo")):
            if os.path.isfile(cand):
                return cand
    try:
        from module_loader import ModuleLoader
        path = ModuleLoader().resolve_module_path(module_name)
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def imported_struct_defs(source_path: str, stmts: list,
                         project_root: str = None) -> list:
    """The StructDefs declared by the modules `source_path` imports.

    An importer needs these for the same reason its own file's structs are
    needed: a constructor call and a method call have to be recognised as
    operations on a TYPE. `from lib1 import Counter` binds the name `Counter`
    in this file, so `Counter()` here is a struct default-construction — but
    with only this file's declarations in hand it looks like a call to an
    unknown function, and lowered to a BL against a symbol named `Counter`
    that nothing defines.

    The declarations are read from the imported module's own source, which is
    the same parse the module's dylib was built from, so the two cannot
    disagree about a struct's shape."""
    out, seen = [], set()
    for mod in imported_modules(stmts):
        path = resolve_module_path(mod, relative_to=source_path,
                                   project_root=project_root or source_path)
        if path is None:
            continue
        try:
            with open(path) as f:
                text = f.read()
            mod_stmts = F.Parser(F.py_tokenize(text)).with_filename(path) \
                            .parse_module()
        except Exception:
            continue
        for st in mod_stmts:
            name = getattr(st, "name", None)
            if st.__class__.__name__ == "StructDef" and name not in seen:
                seen.add(name)
                out.append(st)
    return out


def build_module_dylib(module_name: str, source_path: str, out_dir: str,
                       arch: str = "arm64", project_root: str = None,
                       _stack=()) -> str:
    """Compile `source_path` in full into a dylib; return its path.

    "In full" = every public function the module defines. Its own imports are
    resolved first and the resulting dylibs are recorded in the manifest's
    `depends_on`, so a program linking this module also gets what IT needs
    (that is Stage 2's transitive closure; the dependency list is written now
    so nothing has to be rediscovered later).

    A module already on the stack is a cycle — legal, because ABI.md
    forward-declares functions precisely so mutual imports work. It is
    reported as a dependency and not rebuilt, which is what breaks the
    recursion.
    """
    key = os.path.abspath(source_path)
    if key in _BUILT:
        return _BUILT[key]
    if key in _stack:
        return None            # cycle: the caller links us, we link them

    from formal.build import compile_formal_dylib, FormalBuildError
    from formal.arm64_codegen import CodegenError

    with open(source_path) as f:
        text = f.read()
    try:
        stmts = F.Parser(F.py_tokenize(text)).with_filename(source_path) \
                 .parse_module()
    except SyntaxError as e:
        raise ImportBuildError(f"{source_path}: parse error: {e}")

    # Its imports, first, so we know what this module needs.
    depends = []
    for mod in imported_modules(stmts):
        dep_path = resolve_module_path(mod, relative_to=source_path,
                                       project_root=project_root or source_path)
        if dep_path is None:
            # A HOST module is a different answer from a typo. `import os` in
            # a Python-superset language names the CPython standard library,
            # which has no Mojo source to compile and no symbol this backend
            # could bind; that is a property of the target, not a resolution
            # failure, and saying so keeps it from reading as one. It stays an
            # error either way — the file genuinely cannot be built here — but
            # it is the file's use of the host stdlib, not a broken module
            # path, and lumping the two together buries the real failures.
            kind = ("a host module (CPython standard library), which has no "
                    "Mojo source for this backend to compile"
                    if _is_host_module(mod)
                    else "not a stdlib or sibling module, and no such file "
                         "exists")
            raise ImportBuildError(
                f"{os.path.basename(source_path)} imports {mod!r}, which is "
                f"{kind}")
        depends.append((mod, dep_path))
    # Build the dependencies first, and keep their dylibs: they go on THIS
    # library's link line, both so cross-module calls get the right exported
    # spelling and so the load commands that let dyld bind them exist.
    dep_dylibs = []
    for _mod, dep_path in depends:
        d = build_module_dylib(_mod, dep_path, out_dir, arch,
                               project_root=project_root or source_path,
                               _stack=_stack + (key,))
        if d:
            dep_dylibs.append(d)

    os.makedirs(out_dir, exist_ok=True)
    # The library's identity is the module NAME the importer used, not the
    # file's basename: a package resolves to `<pkg>/__init__.mojo`, and two
    # packages would otherwise both be `_init_`.
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", module_name)
    out = os.path.join(out_dir, prefix + ".dylib")
    try:
        result = compile_formal_dylib([source_path], output=out, prove=False,
                                      check=False,
                                      module_prefixes={source_path: prefix},
                                      link_dylibs=dep_dylibs)
    except (FormalBuildError, CodegenError) as e:
        raise ImportBuildError(f"{os.path.basename(source_path)}: {e}")
    # Record the dependencies in the manifest so a program can link them
    # without re-deriving this module's imports.
    _record_depends(_manifest_path(out),
                    [(m, p) for m, p in depends])
    _BUILT[key] = out
    return out


def _record_depends(manifest_path: str, depends: list) -> None:
    import json
    try:
        with open(manifest_path) as f:
            payload = json.load(f)
    except OSError:
        return
    payload["depends_on"] = [{"module": m, "source": p} for m, p in depends]
    with open(manifest_path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")


def dylib_chain(dylib_path: str, _seen=None) -> list:
    """`dylib_path` plus every dylib its module depends on, dependencies first.

    A dependency has to be on the link line before the module that needs it is
    bound, so the order is the post-order of the dependency graph. A cycle
    terminates because `_seen` stops the walk."""
    _seen = set() if _seen is None else _seen
    key = os.path.abspath(dylib_path)
    if key in _seen:
        return []
    _seen.add(key)
    import json
    depends = []
    try:
        with open(_manifest_path(dylib_path)) as f:
            depends = json.load(f).get("depends_on") or []
    except OSError:
        depends = []
    out = []
    for dep in depends:
        dep_dylib = _BUILT.get(os.path.abspath(dep["source"]))
        if dep_dylib:
            out.extend(dylib_chain(dep_dylib, _seen))
    out.append(dylib_path)
    return out


# ImportBuildError is defined in formal/build.py (a FormalBuildError subclass,
# so an unresolvable import reaches the user as "build: ..." and not a
# traceback) and re-exported here for callers that import it from either
# place.
