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

# The root of this source tree — the directory holding fire_compiler.py. This
# repository is itself the source the formal path compiles, so it is a
# legitimate (and bounded) place to look for a module name.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# CPython's standard library, SPLIT BY WHAT IMPLEMENTING IT WOULD REQUIRE.
#
# These have no Mojo source in this tree and no symbol this formal model could
# bind, so a file importing one cannot be built here — that much is a statement
# about the TARGET, not a module-resolution failure. But "cannot be built here"
# and "could never be built here" are different claims, and the coverage report
# used to conflate them: `tools/formal_sweep.py`'s CLASS_HOST blurb says a host
# import is *"outside this backend's reach, and not fixable"*, which is FALSE of
# `os`, `sys`, `math`, `struct`, `time`, `json` and `re`. Those are modules
# whose capability is reachable — libSystem provides the underlying facility, or
# the work is pure computation. Saying "not fixable" about them is how the
# largest bucket in the report came to rest on a claim nobody had checked.
#
# The rule that separates the tiers, stated once: **does implementing it need an
# object a freestanding image that links libSystem and NOTHING ELSE does not
# have?** A second process, a thread, a socket, a dynamic loader for foreign
# code, an embedded CPython, a terminal — or a library outside libSystem. That
# is a property of the target and no amount of backend work changes it.
# Everything else is `HOST_MODELLED`: reachable in principle, not implemented
# today, and therefore a gap with an owner rather than a permanent fact.
#
# This is a judgement with a stated rule, not a proof. A module is placed by the
# rule and by nothing else — never because it happens to be unimplemented, and
# never because it is unimplemented *on this backend specifically*.
#
# `_is_host_module` consults the UNION, so this is a CLASSIFICATION change and
# not a behaviour change: every one of these refuses the build exactly as
# before, and the union is asserted to equal what the single list used to hold.
HOST_UNREACHABLE = frozenset((
    # A second process.
    "subprocess",
    # A thread, and a proved model of one.
    "threading", "concurrent", "concurrent.futures", "asyncio",
    # A socket.
    "socket", "urllib", "http",
    # A dynamic loader for foreign code, or an embedded CPython.
    "ctypes", "importlib", "importlib.util", "importlib.machinery",
    # The interpreter's own frames, allocation set, or shutdown path. There is
    # no interpreter here to ask, and on this path a value is one 64-bit word,
    # so there is nothing for `gc` to track and no bytecode for `dis` to
    # disassemble (the formal backends emit machine code, not bytecode).
    "traceback", "gc", "atexit", "signal", "warnings", "dis",
    # Process-wide reporting machinery, which is a host object by construction.
    "logging", "unittest", "unittest.mock",
    # A terminal, or a writable filesystem this target does not get.
    "getpass", "webbrowser", "tempfile", "shutil",
    # A library outside libSystem, so linking it would contradict the premise
    # that a formal image links libSystem and nothing else.
    "zlib", "gzip", "locale",
))

# The reachable half: libSystem provides the facility, or the module is pure
# computation over values the model already represents. NOT implemented today.
# Grouped by what it would need, because that is what "reachable" means here.
HOST_MODELLED = frozenset((
    # A libSystem/libc facility: getcwd, stat, clock_gettime, regcomp,
    # arc4random_buf, CommonCrypto for hashlib, the POSIX file calls.
    #
    # `os` was in this set and is not any more: it is WRITTEN, in
    # `os/_syscalls.mojo` (every libSystem call it makes, once), `os/path`
    # (CPython's posixpath) and `os` itself, and `test_formal_os.py` builds
    # and RUNS all of it — 436 path answers against CPython's own, 75
    # filesystem operations against the real filesystem. What of CPython's
    # `os` is not here is stated on each function that lacks it (`listdir` and
    # `walk` need a run-time-length sequence, which a list on this path cannot
    # be; `environ` needs a `char **` walk) rather than approximated, and both
    # omissions are bug docs. The entry has to go: leaving it would mean a file
    # that imports `os` is refused AFTER the module that answers it exists,
    # and the refusal would be a claim about a module that is sitting right
    # there.
    "sys", "errno", "stat", "platform", "time", "select", "io",
    "pathlib", "glob", "fnmatch", "hashlib", "secrets", "uuid",
    # Pure computation over representable values: string and text handling,
    # numeric containers, pattern matching, byte packing, data structures.
    "json", "re", "struct", "math", "random", "decimal", "fractions",
    "numbers", "array", "operator", "functools", "itertools", "collections",
    "heapq", "bisect", "textwrap", "csv", "difflib", "base64",
    "codecs", "copy", "abc", "enum", "types", "contextlib", "queue",
    "weakref", "pprint", "reprlib", "pickle",
    # A shape over the source language rather than a runtime facility: the
    # parser, the type lattice, the dataclass transform, the CLI parser.
    "ast", "typing", "dataclasses", "argparse",
    # A SUBSET is reachable, and the subset is the point. `inspect` reads
    # attributes off live values, which this path has (the gimple runtime
    # carries a type tag and `mojo_obj_getattr`); what it cannot do is walk a
    # live interpreter's frames, because there is no interpreter. Flagged as
    # considered rather than missed.
    "inspect",
))

# Everything the build treats as a host module. The union, deliberately: the
# predicate the BUILD consults must not change behaviour, and this is the one
# place that says so.
#
# `__future__` is deliberately NOT in either tier. It is not a host module but a
# compiler directive that binds nothing, and it is excluded as INERT_MODULES
# below — a different and more accurate reason than "the host provides it", and
# the reason that matters is the sweep's: a file whose FIRST problem was
# `from __future__ import annotations` was reported as importing a module that
# cannot be built, which buried the `import os` that was what actually stopped
# it. That was the reason `asyncio`, `ctypes` and `concurrent` were added here in
# the first place: the coverage report was working around their absence, telling
# files they imported "not a stdlib or sibling module", which is a statement
# about module RESOLUTION and is simply false of a CPython standard-library
# module with no Mojo source.
HOST_MODULES = HOST_UNREACHABLE | HOST_MODELLED


def host_module_tier(name: str) -> str:
    """`'modelled'`, `'unreachable'`, or `''` for a name that is not a host module.

    The accessor that makes the split usable. A coverage report can then say
    "this file is out of reach because it needs a second process" — a fact
    about the target, permanent — separately from "this file is out of reach
    because `os.path.join` has not been built yet", which is a gap with an
    owner. Before this existed both were one bucket, and the bucket's own
    description asserted the stronger of the two claims about all of them.

    `unreachable` is tested first, so a name in both tiers would resolve to the
    permanent answer; the partition is asserted to be disjoint by the test
    suite, and `_host_tier_conflicts` reports any overlap on demand.
    """
    if not name:
        return ""
    top = name.split(".")[0]
    if top in HOST_UNREACHABLE or name in HOST_UNREACHABLE:
        return "unreachable"
    if top in HOST_MODELLED or name in HOST_MODELLED:
        return "modelled"
    return ""


def _host_tier_conflicts() -> list:
    """Names in both tiers, and (for auditing a future edit) names in neither.

    Empty is correct. This exists so a name added to one tier and forgotten in
    the other is a visible failure rather than a silent change to a verdict
    nobody reads a diff for. The suite asserts on it.
    """
    return sorted(HOST_UNREACHABLE & HOST_MODELLED)



def _is_host_module(name: str) -> bool:
    return name in HOST_MODULES or name.split(".")[0] in HOST_MODULES


# Modules whose import is a DECLARATION to the reader rather than a
# dependency, so there is nothing for the link step to provide.
#
# `from __future__ import annotations` is the whole of it. `__future__` is not
# a library: importing a name from it is a compiler directive (`annotations`
# means "store string annotations"), it binds no value the program can use, and
# it produces no code. Demanding a source file for it is the resolver asking a
# file to exist that was never meant to, and it buries the real reason a file
# cannot be built under a name nobody is looking for: it was the FIRST thing
# wrong with 30+ real files in this repo, reported instead of the `import os`
# that is what actually stops them.
#
# This is the general rule stated once: an import that cannot change what the
# program computes is not a dependency. The rest of that family needs no list
# because it is already excluded structurally — a `TYPE_CHECKING` block, an
# `if False:`/`if sys.version_info >= ...` arm and a `try: import x except
# ImportError:` are all NESTED inside an If/Try, and `imported_modules` reads
# only the module's top level. That is load-bearing, not incidental: descending
# into a body would make every one of those names a hard dependency, so
# `test_guarded_imports_stay_inert` pins it.
INERT_MODULES = frozenset(("__future__",))


def _is_inert_module(name: str) -> bool:
    return name in INERT_MODULES


def _manifest_path(dylib_path: str) -> str:
    from formal.build import dylib_manifest_path
    return dylib_manifest_path(dylib_path)


def imported_modules(stmts) -> list:
    """The module names a statement list imports, in source order, deduped.

    `import a.b`, `import a.b as c` and `from a.b import x, y` all name the
    module `a.b`; the alias and the imported names do not change which module
    has to be built. `extra` carries `import a, b, c`'s additional names.

    Two kinds of import are deliberately NOT dependencies, and both exclusions
    belong here rather than at each call site, because every consumer of this
    list wants the same answer:

      * a semantically inert import (`from __future__ import annotations` — see
        `INERT_MODULES`), which binds nothing and emits nothing;
      * anything nested inside an `if`/`try` body, which is not a top-level
        statement and so is never seen. A `TYPE_CHECKING` block, an
        `if sys.version_info` arm and a guarded `try: import x except
        ImportError` are inert for the same underlying reason — the name is not
        unconditionally required — and excluding them structurally means the
        rule cannot go stale as new spellings appear.

    What is left is exactly "what must be on the link line for this file".
    """
    out = []
    for st in stmts or []:
        if isinstance(st, F.ImportStmt):
            names = [st.module]
            for mod, _alias in (st.extra or []):
                names.append(mod)
            for m in names:
                if (isinstance(m, str) and m and m not in out
                        and not _is_inert_module(m)):
                    out.append(m)
        elif isinstance(st, F.FromImportStmt):
            m = st.module
            if (isinstance(m, str) and m and m not in out
                    and not _is_inert_module(m)):
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
    # The repository root, last among the local roots. For the file being
    # compiled the "project root" above IS that file's own directory, so the
    # walk stops after one entry and a sibling of the REPO — `fire_compiler`,
    # `gimple_codegen`, `type_system` — is out of reach even though the file
    # importing it is in the same tree. That is the ordinary case for a
    # multi-file project in this repository, and it produced the flatly false
    # "not a stdlib or sibling module, and no such file exists" for a file
    # that was sitting there. This root is fixed and specific (the tree this
    # module lives in), NOT a walk to `/`: the whole point of stopping at the
    # project root was to keep `import math` from binding to an unrelated
    # ~/math.mojo, and a bounded root cannot do that.
    roots.append(_REPO_ROOT)
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


def _candidates(module_name: str, base: str, ext: str) -> list:
    """The file shapes a module name can take under `base`, for one extension.

    `<name>.mojo`, `<name>/__init__.mojo` (a package), and the same two spelled
    with the LEAF only. The leaf fallback is what makes a package-relative
    dotted import of a sibling work: inside `formal/`, `import formal.types`
    looks for `formal/formal/types.mojo` (the path spelled from the project
    root, which is `formal/` itself here) and finds nothing, but the sibling
    really is `types` in the very directory the import was written in.
    module_loader resolves the same two shapes for the stdlib, so this is the
    same rule, not a second one.
    """
    rel = module_name.replace(".", os.sep)
    leaf = module_name.split(".")[-1]
    return [os.path.join(base, rel + ext),
            os.path.join(base, rel, "__init__" + ext),
            os.path.join(base, leaf + ext),
            os.path.join(base, leaf, "__init__" + ext)]


def _relative_candidates(module_name: str, relative_to: str, ext: str) -> list:
    """The file shapes a RELATIVE module name can take, resolved properly.

    A leading dot is not a path separator, and treating it as one is what made
    `..` resolve to the importer's own package. `_candidates` does
    `module_name.replace(".", os.sep)`, so `".."` becomes `"/"`, the first two
    candidates land at the FILESYSTEM ROOT where they never exist, and the leaf
    fallback — which takes `"..".split(".")[-1]`, i.e. the empty string — then
    matches the importer's OWN `__init__.mojo`. Measured, before this function
    existed:

        _candidates("..", ".../std/gpu/host/nvidia", ".mojo")
          ['//.mojo', '//__init__.mojo',
           '.../gpu/host/nvidia/.mojo', '.../gpu/host/nvidia/__init__.mojo']

        from .../gpu/host/nvidia/tma.mojo
          ".."            -> .../gpu/host/nvidia/__init__.mojo   WRONG
          "std.gpu.host"  -> .../gpu/host/__init__.mojo         right

    so `from .. import DeviceBuffer` imported nvidia's own package instead of
    its parent, and the file was refused for a module that resolves perfectly
    well (bugs/FORMAL_known_limits.md 1.3).

    The rule, which is Python's and needs no special case: **the containing
    package's directory is the importing file's own directory, whatever the file
    is called.** `a/b/c.py` is a module of package `a.b`, and `a/b/__init__.py`
    *is* package `a.b`; in both cases `.` is `a/b`. So `.` is `dirname(file)`,
    each additional dot ascends one level, and whatever follows the dots is
    appended to the result.

    This deliberately reproduces what the leaf fallback already did for `.leaf`
    and `.` — `from .path import ...` inside `os/path/__init__.mojo` resolves to
    `os/path/path.mojo` today and still does, because it was never the broken
    case. Fixing `..` must not disturb it, so `resolve_module_path` tries the
    relative form FIRST and leaves the four root passes exactly as they were.

    Ascending stops at the filesystem root rather than looping, and a name that
    asks for more levels than exist simply yields the root, fails to match, and
    falls through to the ordinary search — a miss, not a wrong answer.
    """
    if not module_name or not module_name.startswith("."):
        return []
    if not relative_to:
        return []
    dots = 0
    while dots < len(module_name) and module_name[dots] == ".":
        dots += 1
    rest = module_name[dots:]
    base = os.path.dirname(os.path.abspath(relative_to))
    for _ in range(dots - 1):
        parent = os.path.dirname(base)
        if parent == base:            # already at the root: stop, do not spin
            break
        base = parent
    if not rest:
        # `.` and `..` with nothing after them name a PACKAGE, and a package is
        # a directory. Its `__init__` is the only spelling.
        return [os.path.join(base, "__init__" + ext)]
    rel = rest.replace(".", os.sep)
    return [os.path.join(base, rel + ext),
            os.path.join(base, rel, "__init__" + ext)]


def resolve_module_path(module_name: str, relative_to: str = None,
                        project_root: str = None) -> str:
    """The source file for `module_name`, or None if it cannot be resolved.

    The search is four ordered passes, and the order is the contract — it is
    what decides whether a name binds to the target's own module, to CPython's,
    or to a source file in this repository:

      1. MOJO SOURCE, any search root, nearest first. `<name>.mojo` or
         `<name>/__init__.mojo`. This wins OUTRIGHT, including over the
         host-module list below: a `.mojo` file sitting beside the importer is
         the target's own module, and refusing it because a same-named CPython
         module exists would bind the program to the wrong one. A real Mojo
         module is a stronger statement than any name in `HOST_MODULES`.
      2. HOST MODULE. If no Mojo source exists and the name is in
         `HOST_MODULES` (or its first dotted component is), the answer is
         "CPython standard library, nothing to compile" and no sibling is
         consulted. This has to come BEFORE pass 3 rather than after it,
         because this repository contains `formal/types.py` and
         `mojo/middle/types.py` — a `.py` sibling whose basename is a host
         module name. Looking at siblings first would silently rebind a file's
         ordinary `from types import SimpleNamespace` to a same-named local
         module, which is precisely the kind of quietly-narrower result that
         turns into a bug nobody can see. Python's own absolute-import rule
         agrees: `import types` is the standard library, never a neighbour.
      3. REPOSITORY SIBLING, any search root, nearest first, `.py` and
         `__init__.py`. This repository IS the source the formal path compiles
         (that is what `fire_compiler.py`, `gimple_codegen.py` and
         `type_system.py` are), so a program that imports a sibling has to be
         able to find it. Without this pass those files were reported as
         importing "not a stdlib or sibling module, and no such file exists" —
         a statement that is simply false about a file that is sitting right
         there. A `.py` loses to a `.mojo` of the same name in a further root
         (pass 1 runs first, over every root): Mojo source is the target's own
         vocabulary and outranks a host-language source file.
      4. module_loader, for the stdlib, as the last resort.

    Returns None when all four come up empty; the caller then distinguishes a
    host module from a plain typo and says which (see
    `unresolvable_import_error`, the single wording for that).

    A RELATIVE name (`.x`, `..x`, `..`) is resolved before all four passes, from
    the importing file's own directory, by `_relative_candidates`. It cannot go
    through the root search at all: the roots are absolute directories and a
    relative name is not spelled from any of them, so pass 1 reduces it to a
    filesystem-root path that never exists and the leaf fallback then finds the
    importer's OWN package. That is how `from .. import DeviceBuffer` came to
    mean `gpu.host.nvidia` rather than `gpu.host`. Trying it first leaves the
    four passes — and the leaf fallback that several real stdlib
    `from .sibling import` statements depend on — exactly as they were.
    """
    if module_name.startswith("."):
        for ext in (".mojo", ".py"):
            for cand in _relative_candidates(module_name, relative_to, ext):
                if os.path.isfile(cand):
                    return cand
        # A relative name that resolved to nothing is a MISS, and returning None
        # here rather than falling through is the point. A relative name is by
        # definition not spelled from any of the search roots, so the root
        # passes cannot answer it correctly -- they can only answer it wrongly.
        # They did: the leaf fallback takes `"..".split(".")[-1]`, which is the
        # EMPTY STRING, so any all-dots name matched `__init__` in the importing
        # file's own directory and `from .......... import x` resolved to the
        # importer's own package. A miss is the honest answer.
        return None
    roots = _search_roots(relative_to, project_root)
    for ext in (".mojo",):                       # pass 1
        for base in roots:
            for cand in _candidates(module_name, base, ext):
                if os.path.isfile(cand):
                    return cand
    if _is_host_module(module_name):              # pass 2
        return None
    for ext in (".py",):                         # pass 3
        for base in roots:
            for cand in _candidates(module_name, base, ext):
                if os.path.isfile(cand):
                    return cand
    try:                                         # pass 4
        from module_loader import ModuleLoader
        path = ModuleLoader().resolve_module_path(module_name)
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def unresolvable_import_error(source_path: str, module_name: str) -> str:
    """The one wording for "this import names nothing this backend can build".

    Two call sites raise it — formal/build.py for the file being compiled and
    `build_module_dylib` for a file reached through a dependency — and two
    messages for one cause is how a real failure ends up filed under the wrong
    heading. It lives here, next to the rules that decide which of the two
    reasons applies, so the wording cannot drift from the resolution it
    describes.
    """
    kind = ("a host module (CPython standard library), which has no Mojo "
            "source for this backend to compile"
            if _is_host_module(module_name)
            else "not a stdlib or sibling module, and no such file exists")
    return (f"{os.path.basename(source_path)} imports {module_name!r}, which "
            f"is {kind}")


def imported_struct_defs(source_path: str, stmts: list,
                         project_root: str = None) -> list:
    """The StructDefs reachable through the modules `source_path` imports.

    An importer needs these for the same reason its own file's structs are
    needed: a constructor call and a method call have to be recognised as
    operations on a TYPE. `from lib1 import Counter` binds the name `Counter`
    in this file, so `Counter()` here is a struct default-construction — but
    with only this file's declarations in hand it looks like a call to an
    unknown function, and lowered to a BL against a symbol named `Counter`
    that nothing defines.

    The declarations are read from the imported module's own source, which is
    the same parse the module's dylib was built from, so the two cannot
    disagree about a struct's shape.

    The walk follows RE-EXPORTS, and that is not a refinement — it is the
    whole point for a package. `from pkg import Two` resolves to
    `pkg/__init__.mojo`, which declares no struct at all; it re-exports one
    from `pkg/two.mojo`. Reading only the file the import NAME resolved to
    therefore found nothing, and the importer's `Two(...)` was lowered as a
    call to an undefined function — the type half of exactly the bug the
    re-export fix in `build_module_dylib` addresses on the symbol half. A
    package's API is its re-exports, so reaching a type means walking to the
    module that defines it.

    Transitive, and cycle-safe: a package that re-exports from a sibling that
    re-exports back terminates on the visited set, and a struct is collected
    once however many paths reach it."""
    out, seen, visited = [], set(), set()

    def collect(path):
        key = os.path.abspath(path)
        if key in visited:
            return
        visited.add(key)
        try:
            with open(path) as f:
                text = f.read()
            mod_stmts = F.Parser(F.py_tokenize(text)).with_filename(path) \
                            .parse_module()
        except Exception:
            return
        for st in mod_stmts:
            name = getattr(st, "name", None)
            if st.__class__.__name__ == "StructDef" and name not in seen:
                seen.add(name)
                out.append(st)
        # Then whatever this module re-exports, which is where a package's
        # types actually live.
        for st in mod_stmts:
            if not isinstance(st, F.FromImportStmt):
                continue
            dep = resolve_module_path(st.module, relative_to=path,
                                      project_root=project_root or source_path)
            if dep:
                collect(dep)

    for mod in imported_modules(stmts):
        path = resolve_module_path(mod, relative_to=source_path,
                                   project_root=project_root or source_path)
        if path is not None:
            collect(path)
    return out


def declared_kinds(path: str) -> dict:
    """{name: "function"|"type"} for what `path` declares at top level.

    Read from the module's OWN source — the same file the dylib is built from,
    so the two cannot disagree about what the module contains. A name the
    source does not declare at all is simply absent, which is how a re-export
    of something that does not exist gets caught rather than forwarded."""
    out: dict = {}
    try:
        with open(path) as f:
            text = f.read()
        stmts = F.Parser(F.py_tokenize(text)).with_filename(path).parse_module()
    except Exception:
        return out
    for st in stmts:
        name = getattr(st, "name", None)
        if not name:
            continue
        if isinstance(st, F.FunctionDef):
            out.setdefault(name, "function")
        elif isinstance(st, F.StructDef):
            out.setdefault(name, "type")
    return out


def reexported_names(stmts, kinds_by_module: dict = None) -> dict:
    """{name: (module, kind)} for the names this module binds by RE-EXPORT.

    `from .sub import addone` binds `addone` in this file without defining
    it. A package `__init__.mojo` is nothing BUT such statements, and that is
    a module with a real public API, not one with none — which is why it used
    to be refused as "a struct-only module has no free-function API" and took
    every importer of the package down with it.

    A name this module also DEFINES is not a re-export: its definition is
    here, it exports under this module's own qualifier, and the submodule's
    same-named symbol is irrelevant to anything binding it. (Which of the two
    a bare call resolves to is the pre-existing name-based-dispatch limit,
    stated in `compile_formal_dylib`'s overload handling.)

    `kind` is the DECLARED kind in the defining module (`declared_kinds`), and
    it is what makes a missing symbol reportable as the right kind of gap: a
    re-exported FUNCTION nobody exports is a missing definition, while a
    re-exported TYPE is not a missing symbol at all — a type crosses the
    boundary as a layout in the reflection table and is carried to the importer
    by `imported_struct_defs`, not by a trie entry. Conflating the two would
    either refuse every package that re-exports a type (most of them) or wave
    through a genuinely missing function.

    `import a.b` binds the MODULE, not a name, so it contributes nothing here;
    only `from ... import ...` does."""
    defined = {st.name for st in (stmts or [])
               if isinstance(st, (F.FunctionDef, F.StructDef))}
    kinds_by_module = kinds_by_module or {}
    out: dict = {}
    for st in stmts or []:
        if not isinstance(st, F.FromImportStmt):
            continue
        for pair in (st.names or []):
            name = pair[0] if isinstance(pair, (tuple, list)) else pair
            if (isinstance(name, str) and name and name not in defined
                    and not _is_inert_module(name)
                    and not name.startswith("_")):
                out.setdefault(name, (st.module,
                                      kinds_by_module.get(st.module, {})
                                      .get(name, "unknown")))
    return out


def _module_identity(module_name: str, parent: str = None) -> str:
    """`module_name` resolved against the module that spelled it.

    An absolute name is its own identity. A relative one — `.sub`, `..util` —
    only means something relative to the module that wrote it, so it is
    qualified by `parent`, that module's own already-resolved identity. The
    result is the dotted name the file is really addressed by, which is what
    makes two different `a/sub.mojo` and `b/sub.mojo` two different libraries
    instead of one name written twice.

    With no parent (a top-level build, where the import is resolved from the
    project root rather than from a package) a relative name keeps its own
    spelling: there is nothing to qualify it against, and flattening it is
    better than dropping it, since the name is then at least stable."""
    if not module_name or not module_name.startswith("."):
        return module_name
    if not parent:
        return module_name
    if parent.endswith(".__init__"):
        parent = parent[: -len(".__init__")]
    return parent + module_name


def _dylib_lock(out: str):
    """Exclusive, cross-process, released on exit: an flock on a side file.

    A side file and not the library itself: `compile_formal_dylib` truncates
    and rewrites the `.dylib`, so locking that would let a second process in
    as soon as the first created it. A side file is never rewritten, so the
    lock spans the whole build. `flock` is advisory and per-open-file-
    description, so it is released when the process dies — a crashed build
    cannot wedge the tree.
    """
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def _locked():
        fd = os.open(out + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)
    return _locked()


def build_module_dylib(module_name: str, source_path: str, out_dir: str,
                       arch: str = "arm64", project_root: str = None,
                       _stack=(), _parent: str = None) -> str:
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

    `arch` is part of the identity of what comes out, so it is part of BOTH
    keys. `_BUILT` used to be keyed by source path alone, so a process that
    built the same module for two architectures got the first architecture's
    dylib back for the second request; and the OUTPUT NAME is the same for
    both, so even across processes one architecture's library overwrote the
    other's on disk. Together those are why an x86-64 program could link an
    arm64 module dylib and then die in dyld with "mach-o file, but is an
    incompatible architecture" — a cache key that was not the thing being
    cached, in the one place where a stale hit is a wrong-architecture load
    rather than a slow rebuild. `out_dir` is per-architecture for the same
    reason (see `formal/build.py`'s `_resolve_imports`).
    """
    key = (arch, os.path.abspath(source_path))
    if key in _BUILT:
        return _BUILT[key]
    if os.path.abspath(source_path) in _stack:
        return None            # cycle: the caller links us, we link them

    from formal.build import compile_formal_dylib, FormalBuildError
    from formal.arm64_codegen import CodegenError

    # This module's own identity, which is also what a RELATIVE import of
    # its own is resolved against. Computed before the recursion so each
    # level qualifies the next (see the `_parent` note at the output name).
    module_identity = _module_identity(module_name, _parent)

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
            # The wording is `unresolvable_import_error`'s, shared with
            # formal/build.py so the two sites cannot drift.
            raise ImportBuildError(unresolvable_import_error(source_path, mod))
        depends.append((mod, dep_path))
    # Build the dependencies first, and keep their dylibs: they go on THIS
    # library's link line, both so cross-module calls get the right exported
    # spelling and so the load commands that let dyld bind them exist.
    dep_dylibs = []
    for _mod, dep_path in depends:
        d = build_module_dylib(_mod, dep_path, out_dir, arch,
                               project_root=project_root or source_path,
                               _stack=_stack + (os.path.abspath(source_path),),
                               _parent=module_identity)
        if d:
            dep_dylibs.append(d)

    os.makedirs(out_dir, exist_ok=True)
    # The library's identity is the module NAME the importer used, not the
    # file's basename: a package resolves to `<pkg>/__init__.mojo`, and two
    # packages would otherwise both be `_init_`.
    #
    # A RELATIVE name has to be qualified by the module that spelled it, or
    # it is not an identity at all. `pkg/__init__.mojo` saying `from .sub
    # import x` means `pkg.sub`; taken literally the name is `.sub`, which
    # normalizes to `_sub` — and then `a/__init__.mojo` and `b/__init__.mojo`
    # each importing their own `.sub` both write `_sub.dylib` into the SAME
    # directory, and whichever built second replaces the other's library. Two
    # packages' symbols, silently interchangeable. `_parent` carries the
    # importing module's own resolved identity down the recursion, which is
    # what turns `.sub` into `pkg.sub`.
    #
    # The architecture is part of the file NAME too, not only of the
    # directory: `out_dir` is per-arch (so the two do not overwrite each
    # other in the CAS), but a caller can pass any directory it likes, and a
    # name that collides across architectures would reintroduce the same
    # overwrite one level up.
    #
    # The SOURCE DIGEST is in the name as well, and that closes the last
    # overwrite. `(arch, module name)` is not an identity: two builds of a
    # module called `helper` — two checkouts, two temp trees, two concurrent
    # jobs in one `-j18` bucket — took the same path, so whichever finished
    # last replaced the other's library, and a program could be linked against
    # a dylib built from different source. It showed up as an intermittent
    # failure in test_formal_sweep.py's dyld-probe cases, which read a dylib
    # back off this shared path while other jobs were writing it.
    #
    # Hashing the source is what makes sharing safe rather than merely rare:
    # two builds whose sources agree produce byte-identical libraries, so
    # writing the same path is then harmless, and two that disagree get
    # different paths. Nothing has to take a lock, so a concurrent build
    # neither blocks nor blocks on it — the same bargain the CAS makes
    # everywhere else. The digest is the module's own source, so editing it
    # invalidates the path rather than leaving a stale library reachable
    # under a name that looks current.
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", module_identity)
    with open(source_path, "rb") as f:
        src_digest = cas.hash_parts(f.read())[:12]
    out = os.path.join(out_dir, f"{prefix}.{src_digest}.{arch}.dylib")
    # Serialise the write to this exact path.
    #
    # The digest above already separates two builds whose SOURCES differ, so
    # the only remaining collision is two builds of the SAME source onto one
    # path — and that is the common case, not a rare one: `-j18` over a bucket
    # where several jobs import the same stdlib module, or one
    # `make check-formal-sweep` beside another. Their content agrees, so
    # sharing is fine; writing it in place is not, because a reader can
    # observe the file part written.
    #
    # A lock, not a staging path with a rename. Renaming looked like the tidier
    # fix and is wrong here: a dylib's install name is derived from its output
    # path, and it is baked into the load command of everything that links it,
    # so a file built as `.../staging/foo.dylib` and moved afterwards no longer
    # matches the path its dependents were told to load. The lock leaves the
    # path — and therefore the identity — exactly as it was.
    with _dylib_lock(out):
        try:
            result = compile_formal_dylib(
                [source_path], output=out, prove=False, check=False,
                module_prefixes={source_path: prefix},
                link_dylibs=dep_dylibs, arch=arch, fmt="macho",
                reexports=reexported_names(
                    stmts, {m: declared_kinds(p) for m, p in depends}))
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
    terminates because `_seen` stops the walk.

    The architecture is recovered from `dylib_path` (the `.N.dylib` suffix
    `build_module_dylib` writes) to look dependencies up in `_BUILT`, whose key
    is (arch, path). Reading it back off the name rather than threading it
    through every call is safe because the name is the only thing that decides
    which library this is — and a suffix this function cannot parse yields no
    match, i.e. an omitted dependency, which is the same behaviour as a
    manifest with no `depends_on`, not a wrong one."""
    _seen = set() if _seen is None else _seen
    key = os.path.abspath(dylib_path)
    if key in _seen:
        return []
    _seen.add(key)
    arch = _arch_of_dylib(dylib_path)
    import json
    depends = []
    try:
        with open(_manifest_path(dylib_path)) as f:
            depends = json.load(f).get("depends_on") or []
    except OSError:
        depends = []
    out = []
    for dep in depends:
        dep_dylib = _BUILT.get((arch, os.path.abspath(dep["source"])))
        if dep_dylib:
            out.extend(dylib_chain(dep_dylib, _seen))
    out.append(dylib_path)
    return out


def _arch_of_dylib(dylib_path: str) -> str:
    """The architecture in a `<prefix>.<src-digest>.<arch>.dylib` name, or "".

    `rsplit(".", 1)` splits on the LAST dot, so the digest field in the middle
    needs no parsing of its own and this is unchanged by it.
    """
    base = os.path.basename(dylib_path)
    if base.endswith(".dylib"):
        parts = base[:-len(".dylib")].rsplit(".", 1)
        if len(parts) == 2:
            return parts[1]
    return ""


# ImportBuildError is defined in formal/build.py (a FormalBuildError subclass,
# so an unresolvable import reaches the user as "build: ..." and not a
# traceback) and re-exported here for callers that import it from either
# place.
