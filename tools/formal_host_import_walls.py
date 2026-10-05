#!/usr/bin/env python3
"""The host-import wall, ranked by what a file's own import closure still names.

**What this is for.** The sweep classifies a file by the refusal it PRINTS, and
one of its classes is `not-answerable/host-import`. That class is a single
bucket over a queue of unrelated capabilities, so the question "what is left of
it, and what would writing one module move" has no instrument: a module landing
unmasks the row behind it, and the row behind it is larger than the one that was
measured. Three documents have described this measurement in prose and each had
to re-derive it (`bugs/sweeps/sweep-arm-11.txt`'s own notes are the third).
This is the instrument; the documents should read it rather than restate it.

**It must be read with the BACKEND'S readers, not Python's `ast`.** That is not a
preference, it is the whole measurement:

* `formal.build.parse_module` for the statements, because the nodes are
  `fire_compiler`'s and nothing else here accepts them;
* `formal.imports.imported_modules`, which FILTERS `FRONTEND_PROVIDED_MODULES`
  (so `dataclasses`, a front-end transform, is not a wall — a plain `ast` walk
  puts it on 176 files) and which deliberately does not descend into `if`/`try`
  bodies, because a conditional import is not on the link line;
* `formal.imports.resolve_module_path`, the resolver the BUILD ITSELF uses, so
  the tool and the build cannot disagree about what resolves;
* `formal.imports.host_module_tier` and `sys.stdlib_module_names` to decide
  whether a name is a WALL at all rather than a target module or a sibling.

Handing `imported_modules` an `ast.parse(...).body` returns **nothing at all**,
and every row of such a table reads 0. The first version of this walk did that.

**`--pretend-unmodelled` is not a convenience; it is the only way to measure a
delta.** A before/after across two checkouts measures the merge, not the change.
Pretending a module is absent, on ONE tree, is what makes "writing this module
makes these N files build" a measurement rather than an assertion.

    tools/formal_host_import_walls.py                       # the table
    tools/formal_host_import_walls.py --files tools/        # one scope
    tools/formal_host_import_walls.py --pretend-unmodelled signal,traceback
    tools/formal_host_import_walls.py --sweep bugs/sweeps/sweep-arm-11.txt
    tools/formal_host_import_walls.py --explain importlib    # why is it a wall

`reach` is the number of files whose closure names the module; `alone` is the
number for which it is the ONLY such name, i.e. the files "writing this module
makes this file build" is a true statement about. `sweep` is how many times the
sweep log reported on that name specifically, read with the same peel
`tools/formal_sweep_causes.py::rank` uses — the LAST host module named in the
chain that refused the file. `alone` is the column that decides what to write
next, and it is the one a sweep count cannot give you.

A note on scope, because it is the tool's main limit and it is not a bug in it:
this ranks what is LEFT, not what a fix would buy. A file whose only remaining
wall is a constant vocabulary prints no refusal at all — `formal/hostmods/ast.mojo`
says so about its own literals — so it is invisible to the sweep's instruments
and visible only here.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.getcwd())

import formal.build as B                                  # noqa: E402
import formal.imports as I                                # noqa: E402


#: The scopes `--files` understands, as (label, predicate on a repo-relative
#: path). The default is the whole repository, which is what the wave notes were
#: measured over; `--stdlib` is the other scope any of them uses.
SCOPES = {
    "repo": lambda p: True,
    "tools": lambda p: p.startswith("tools/") or p.startswith("test_"),
    "formal": lambda p: p.startswith("formal/"),
    "runtime": lambda p: p.startswith("runtime/"),
    "stdlib": lambda p: p.startswith("std/") or "/std/" in p
                        or p.startswith("lib/"),
}


#: The extensions the formal path compiles, which is what the sweep feeds it
#: (`tools/formal_sweep.py`: "Sweep every *.py / *.mojo under the repo"). Both
#: matter here and dropping either would change the table: the three files
#: `bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md` §2 says left the
#: wall on a wave are `test_memslot.py`, `tools/memcap.py` and `tools/procrun.py`,
#: none of which is Mojo.
SUFFIXES = (".mojo", ".py")


def source_files(roots):
    """Every compilable source file under `roots`, sorted, repo-relative."""
    out = []
    for root in roots:
        if os.path.isfile(root):
            out.append(os.path.relpath(root))
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in (".git", "build", "__pycache__", ".tmp"))
            for name in sorted(filenames):
                if name.endswith(SUFFIXES):
                    full = os.path.join(dirpath, name)
                    out.append(os.path.relpath(full))
    return sorted(set(out))


#: Import lists, by path. A closure walk parses the same module once per
#: IMPORTER — `fire_compiler.py` is imported by 170 files — and this tool is
#: measured over the whole repository, so the cache is not an optimisation but
#: the difference between seconds and hours. It is keyed by path, which is the
#: identity that matters: the same file always yields the same import list.
_IMPORTS_CACHE = {}


def _module_imports(path):
    """`imported_modules` for one file, or `None` when it cannot be read.

    `None` is cached as well as a list: a file that cannot be parsed must not be
    re-read once per importer either, and a cache that only remembered successes
    would make the broken file the slowest thing in the run.
    """
    if path in _IMPORTS_CACHE:
        return _IMPORTS_CACHE[path]
    try:
        with open(path, "r") as f:
            stmts = B.parse_module(f.read(), path)
        names = I.imported_modules(stmts)
    except Exception:                                       # noqa: BLE001
        names = None
    _IMPORTS_CACHE[path] = names
    return names


def closure(path, pretend_unmodelled=frozenset()):
    """`(host walls, error)` for one file: the host modules its closure names.

    `error` is a string when the file itself could not be parsed, so a broken
    file is reported as itself rather than silently counted as a file with no
    walls — which would rank it as the easiest thing in the corpus. A module
    reached THROUGH an import that cannot be parsed is not an error: the walk
    records what it could and moves on, because the question is what is left at
    the WALL and not whether the file above it is readable.

    `pretend_unmodelled` is the delta instrument: a name in it is treated as a
    wall even if `resolve_module_path` finds a source for it, which is exactly
    "this module is absent from this tree".
    """
    walls = set()
    names = _module_imports(path)
    if names is None:
        return walls, "could not be parsed"
    seen_files = {path}
    work = list(names)
    while work:
        name = work.pop()
        if name in seen_files or name in I.FRONTEND_PROVIDED_MODULES:
            continue
        if name in pretend_unmodelled:
            walls.add(name)
            continue
        resolved = I.resolve_module_path(name, relative_to=path)
        if resolved is None:
            if name in sys.stdlib_module_names - I.INERT_MODULES:
                walls.add(name)
            continue
        # A real module: its own imports are part of this file's closure.
        if resolved in seen_files:
            continue
        seen_files.add(resolved)
        sub = _IMPORTS_CACHE.get(resolved, ...)
        if sub is ...:
            sub = _module_imports(resolved)
        if sub:
            work.extend(sub)
    return walls, ""


def sweep_counts(sweep_log):
    """`{module: files the sweep log refused ON that name}`, or `{}`.

    Read with the same peel `tools/formal_sweep_causes.py::rank` uses: the LAST
    `imports '…'` in the chain that refused the file is the host module the
    refusal is about. A `none`/absent log is not an error — it just means this
    column is empty — so the tool is usable before a sweep has been taken.
    """
    if not sweep_log or not os.path.exists(sweep_log):
        return {}
    counts = {}
    with open(sweep_log) as f:
        for line in f:
            names = re.findall(r"imports '([A-Za-z_][\w.]*)'", line)
            if not names:
                continue
            counts[names[-1]] = counts.get(names[-1], 0) + 1
    return counts


def measure(paths, pretend_unmodelled=frozenset()):
    """`({module: reach}, {module: alone}, {module: [files]}, (clean, errs))`.

    `clean` is the number of files with NO unmodelled host module left, and it is
    returned rather than recomputed: it is a second full walk of the corpus if
    the caller derives it, and it is the number the wave notes quote first.
    """
    reach = {}
    alone = {}
    files_of = {}
    errors = []
    clean = 0
    for path in paths:
        walls, err = closure(path, pretend_unmodelled)
        if err:
            errors.append((path, err))
        if not walls and not err:
            clean += 1
        for name in walls:
            reach[name] = reach.get(name, 0) + 1
            files_of.setdefault(name, []).append(path)
        if len(walls) == 1:
            only = next(iter(walls))
            alone[only] = alone.get(only, 0) + 1
    return reach, alone, files_of, (clean, errors)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="rank the host-import wall by what a closure still names")
    ap.add_argument("roots", nargs="*", default=None,
                    help="files or directories to measure (default: the "
                         "whole repository)")
    ap.add_argument("--scope", default="repo", choices=sorted(SCOPES),
                    help="restrict to a named scope when no ROOT is given")
    ap.add_argument("--pretend-unmodelled", default="",
                    help="comma-separated module names to treat as ABSENT on "
                         "this tree, which is how a delta is measured")
    ap.add_argument("--sweep", default=None,
                    help="a sweep log to read the `sweep` column from")
    ap.add_argument("--explain", default=None,
                    help="print the files that name one module and stop")
    ap.add_argument("--min-reach", type=int, default=1,
                    help="hide rows whose reach is below this")
    args = ap.parse_args(argv)

    pretend = frozenset(
        n.strip() for n in args.pretend_unmodelled.split(",") if n.strip())
    if args.roots:
        paths = source_files(args.roots)
    else:
        paths = source_files(["."])
        keep = SCOPES[args.scope]
        paths = [p for p in paths if keep(p)]

    if args.explain:
        reach, _alone, files_of, _rest = measure(paths, pretend)
        name = args.explain
        for path in files_of.get(name, []):
            print(path)
        print(f"{name}: reach {reach.get(name, 0)}, "
              f"{len(files_of.get(name, []))} listed")
        return 0

    reach, alone, files_of, (clean, errors) = measure(paths, pretend)
    swept = sweep_counts(args.sweep)

    total = len(paths)
    print(f"{total} files, {len(reach)} host module(s) named, "
          f"{clean} with no unmodelled host module left"
          + (f", pretending {', '.join(sorted(pretend))} absent"
             if pretend else ""))
    if errors:
        print(f"{len(errors)} file(s) could not be read:")
        for path, err in errors[:10]:
            print(f"  {path}: {err}")
    print()
    print(f"{'module':22s} {'reach':>6s} {'alone':>6s} {'sweep':>6s}  tier")
    for name in sorted(reach, key=lambda n: (-alone.get(n, 0), -reach[n], n)):
        if reach[name] < args.min_reach:
            continue
        tier = I.host_module_tier(name) or "unclassified"
        print(f"{name:22s} {reach[name]:6d} {alone.get(name, 0):6d} "
              f"{swept.get(name, 0):6d}  {tier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
