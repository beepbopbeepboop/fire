#!/usr/bin/env python3
"""What is left of the `not-answerable/host-import` wall, ranked by what each
name would TAKE rather than by how many files mention it.

    python3 tools/formal_host_import_wall.py
    python3 tools/formal_host_import_wall.py --min 1 --json
    python3 tools/formal_host_import_wall.py --sweep bugs/sweeps/sweep-arm-11.txt
    python3 tools/formal_host_import_wall.py --unmodelled glob --unmodelled fnmatch

**Why this is a tool and not a fourth document.** Three bug docs have described
this same measurement in prose — `bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md`
§5, `bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md`'s own
re-measurement, and `bugs/FORMAL_sweep_work_map_2026-10-04_b11.md` §6's closing
judgement — and the last of them says the scratch "should have become a second
tool rather than a fourth description of one". This is that tool.

## The three columns, and why they are three and not one

`reach` is how many files' closures name the module; it is what the sweep's own
`--host` ranking prints, and on its own it is the wrong number to plan with:
`abc` reaches 165 files and is the ONLY wall in none of them, because every one
of those files also wants `importlib`.

  * **`reach`** — files whose import CLOSURE names it. The closure, not the
    file's own imports: a file that never spells `unittest` reaches it through
    `fire_compiler.py`.
  * **`alone`** — files for which this name is the ONLY wall, i.e. the files
    "writing this module makes this file build" is a true statement about. This
    is the column that ranks.
  * **`sweep`** — files a sweep log reported **on this name specifically**, read
    out of the log with the sweep's own chain peel. It is a lower bound on
    `reach` (the log is one build walk over one day's tree) and it is the
    column that says what the last sweep SAW rather than what this tree holds.

**And the reason `reach` is not the ranking is the module landing.** Writing a
host module UNMASKS the row behind it and never grows one, so a wave that
measures before and after on two checkouts measures the merge, not the change.
`--unmodelled NAME` is therefore the instrument that makes a delta measurable
on ONE tree: it pretends `NAME` has no `formal/hostmods/` source, which is what
"before this module landed" means, and the difference between the two runs is
the change. This is the one ability the scratch walk had that must survive the
promotion, and it is why a before/after across two checkouts is not offered
anywhere in this file.

## The readers, and why they are the BACKEND's

Every classification below is read with the same three functions the build
itself uses, and the reason is not tidiness:

  * **`formal.build.parse_module`** for the statements. Not `ast.parse`:
    `imported_modules` takes `fire_compiler`'s node classes, so handing it
    Python's `ast` nodes returns an empty list and every row reads 0.
  * **`formal.imports.imported_modules`** for the names. It filters
    `FRONTEND_PROVIDED_MODULES` (`dataclasses` is a front-end transform, not a
    wall) and `INERT_MODULES`, and it deliberately does not descend into `if`
    or `try` bodies — a conditional import is not on the link line. That
    exclusion is the measurement and not an accident: an `ast`-based walk
    called `traceback` a 38-file row when the backend's own reader says 0.
  * **`formal.imports.host_module_verdict`** for what a name IS — the one
    classification in the tree, with every outcome named. It is asked with the
    same `relative_to`/`project_root` the build uses, so `formal/hostmods/` is
    among its roots and a file's own neighbourhood answers the way it does at
    build time. Its `'written'` answer is why this tool does not keep its own
    "is it a wall" test: a name with a source is answered, and `''` from
    `host_module_tier` cannot say so.

## What a WALL is

Five of the EIGHT answers `host_module_verdict` can give, and the three that are
not walls are the whole rule: a name the compiler answers itself is
**front-end**, a name this tree has a SOURCE for is **written** (and answered),
and a name CPython does not ship is **not-a-module** — a typo, or
a gap in this repository, which `tools/formal_sweep.py` classes as
`not-answerable/unresolved-import`. The five that remain are `modelled` (a gap
with an owner), `unreachable` (a permanent fact about the target), `admitted`
(answers under a declared contract), `unclassified` — CPython ships it and no
tier says which of the two it is, which is the queue
`bugs/FORMAL_stdlib_module_names_are_not_classified.md` carries and what the
`tier` column prints as `unclassified` — and `not-code`, which is CPython
shipping a name whose content is not code at all (`this`, `antigravity`,
`turtledemo`). **`not-code` is a wall because the BUILD refuses the import**, with
its own sentence per name; a file naming one does not build, so a table that did
not count it was reporting a file as cleaner than it is.

Nothing here builds anything, and no Lean runs: the question is what a file
IMPORTS, which is decidable from source, and a build would answer a different
question at twenty minutes a sweep.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import formal.build as FB            # noqa: E402  (after sys.path)
import formal.imports as I           # noqa: E402
import tools.formal_sweep as SW      # noqa: E402

# The host module a terminal host-import message names. The LAST one in the
# chain is the innermost, which is the one that refused — the same peel
# `tools/formal_sweep_causes.py::rank` does, and `SW._split_chain` is that
# tool's reader rather than a second spelling of it.
#
# **TWO WORDINGS, and matching one of them is a bias, not a narrowing.**
# `formal/imports.py::unresolvable_import_error` has three arms, and two of them
# name a host module: a name a tier classifies reads "is a host module (CPython
# standard library)", while a name CPython ships that no tier classifies reads
# "is a CPython standard-library module, which has no Mojo source in this tree
# and no tier …". The second arm is `bugs/FORMAL_stdlib_module_names_are_not_classified.md`'s
# whole fix, and a pattern that only knows the first arm drops exactly the files
# that are in no tier — so the `sweep` column would be silent about the rows that
# classification is for. Measured on `sweep-arm-11.txt`: 4 of the 203 host-import
# lines, and all four are the second arm.
_HOST_MODULE_RE = re.compile(
    r"imports '([^']+)', which is (?:a host module|a CPython standard-library"
    r" module)")

#: The sub-corpora the table can be scoped to, because "what is left" is a
#: different question for each and answering it over the whole repository for
#: every wave is how a number stops meaning anything. `repo` is the default and
#: is the whole walk; the rest are the directories a module landing can move,
#: by the count of files each actually owns. Deliberately keyed on the
#: REPO-RELATIVE path, so `--scope tools` does not depend on where this
#: checkout lives.
SCOPES = {
    "repo": lambda rel: True,
    "tools": lambda rel: rel.startswith("tools/") or rel.startswith("test_"),
    "formal": lambda rel: rel.startswith("formal/"),
    "runtime": lambda rel: rel.startswith("runtime/"),
    "stdlib": lambda rel: rel.startswith("std/") or "/std/" in rel
                          or rel.startswith("lib/"),
}

#: A parsed module's names, keyed by the resolved path they came from. One parse
#: per source file for the whole corpus, because the closure walk visits the
#: same module from every file that imports it and `parse_module` is the
#: expensive half. A parse FAILURE is cached as `None` and not as `[]`, because
#: "this file imports nothing" and "this file could not be read" are different
#: answers and a row that cannot tell them apart understates the corpus.
_IMPORTS_CACHE = {}


def module_imports(path: str):
    """The module names `path` imports, or None if the backend cannot read it.

    None rather than `[]` for a file that will not parse, and neither raises:
    a file the backend cannot read is one this walk knows nothing about, and a
    wall row computed over it would be narrower than the word "reach" claims.
    The count of such files is printed so the narrower answer is visible.
    """
    if path in _IMPORTS_CACHE:
        return _IMPORTS_CACHE[path]
    try:
        with open(path, "rb") as f:
            source = f.read().decode("utf-8", "replace")
        names = list(I.imported_modules(FB.parse_module(source, path)))
    except Exception:
        names = None
    _IMPORTS_CACHE[path] = names
    return names


def walls_of(path: str, unmodelled=frozenset(), seen=None) -> frozenset:
    """Every wall name in `path`'s import CLOSURE, transitively.

    Transitive because that is what the build does: `formal/build.py` compiles
    the whole closure into dylibs and links them, so a file that never spells
    `unittest` is refused on it. `seen` is the worklist guard — a diamond in the
    import graph is common in this repository and an unguarded walk is an
    exponential one.

    A module in the closure the backend cannot read contributes nothing and is
    NOT walked into, which is the one place this answer is narrower than the
    word "closure": the walls such a module carries are unknown, and the count
    of unreadable files is printed for that reason.
    """
    seen = set() if seen is None else seen
    if path in seen:
        return frozenset()
    seen.add(path)
    found = set()
    for name in module_imports(path) or ():
        if name in unmodelled:
            found.add(name)
            continue
        resolved = I.resolve_module_path(name, relative_to=path)
        if resolved:
            found |= walls_of(resolved, unmodelled, seen)
        elif _is_wall(name):
            found.add(name)
    return frozenset(found)


def _is_wall(name: str) -> bool:
    """Whether an UNRESOLVED name is a wall rather than a typo or a gap.

    **A DELEGATION, and it used to be a fourth definition.** This started as
    two questions asked here — `host_module_tier` for "has this tree classified
    the name" and `is_cpython_stdlib` for "does CPython ship it" — and
    `formal/imports.py::host_module_verdict` is now the one place that classifies
    a name, with every outcome named. The reason it has to be one place is that
    the empty answer was ambiguous: a name this tree has WRITTEN leaves its tier,
    so `''` means both "answered" and "nobody classified it", and three
    consumers had grown three ways of telling those apart.

    Two answers are NOT walls, and they are the point: a name this tree has a
    source for is answered, and a name CPython does not ship is a typo or a gap
    in this repository — which `tools/formal_sweep.py` reports as
    `not-answerable/unresolved-import`, a different class that a wall table
    counting it would misattribute to the target.

    **`'not-code'` IS a wall, and leaving it out was a measurement bug rather
    than a judgement.** `this`, `antigravity` and `turtledemo` are
    `HOST_NOT_A_MODULE` members: CPython ships all three and their content is
    not code. The build refuses an import of any of them — `measured, each with
    its own sentence`: "a CPython standard-library module with no content to
    compile — it is documentation or a demonstration, not an API" — so a file
    naming one does not build and the name is a wall by the only test that
    matters. While `host_module_verdict` answered `not-a-module` for them, this
    predicate dropped them, and the drop was visible in the columns: `reach` and
    `alone` both under-counted, and because `alone` is computed over the names
    this function recognises, a file importing `abc` AND `antigravity` read as
    though `abc` were its only wall — a false statement about the file, which is
    the whole thing the `alone` column exists to say (see
    `test_formal_imports.py::test_the_wall_instrument_separates_reach_from_alone`,
    which was red for exactly this).
    """
    answer, _detail = I.host_module_verdict(name)
    return answer in ("modelled", "unreachable", "admitted", "unclassified",
                      "not-code")


def _sweep_host_lines(sweep_path: str):
    """`(file, terminal message)` for every host-import line in a sweep log.

    The peel is `SW._split_chain`'s — the reader `tools/formal_sweep_causes.py`
    and `tools/formal_chain_probe.py` already share — so this column cannot come
    apart from the ranking tables that print the same chains.

    The class is matched UPPERCASED because that is how the sweep prints it
    (`print(f"{v.cls.upper()}: …")`), and matching the constant's own spelling
    is how a column ends up printing 0 rows against a log with 203 of them in it.
    """
    if not sweep_path or not os.path.isfile(sweep_path):
        return
    prefix = f"{SW.CLASS_HOST.upper()}:"
    with open(sweep_path, errors="replace") as f:
        for line in f:
            if not line.startswith(prefix):
                continue
            rest = line[len(prefix):].strip()
            path, _, detail = rest.partition("  (")
            yield path.strip(), SW._split_chain(detail.rstrip(")"))[1]


def sweep_rows(sweep_path: str) -> dict:
    """{file: host module the sweep reported it on} for one sweep log.

    The log is the ground truth for "what was this file BLOCKED ON" — it is one
    build walk over one day's tree, which is a different question from "what is
    in this file's closure today", and both columns are printed for that reason.
    Absent log is an empty column rather than a zero: no log is no measurement.

    A line whose terminal names no host module is DROPPED, and
    `sweep_coverage` below is what says how many were, so a column that quietly
    covered 199 of 203 lines cannot be read as a column over 203.
    """
    rows = {}
    for path, terminal in _sweep_host_lines(sweep_path):
        m = _HOST_MODULE_RE.search(terminal)
        if m:
            rows[path] = m.group(1)
    return rows


def sweep_coverage(sweep_path: str) -> tuple:
    """`(attributed, total)` host-import lines — this instrument's own reach.

    Printed in the header because a column that silently drops lines reads as a
    column over the ones it kept: measured on `sweep-arm-11.txt`, a pattern
    matching only the "is a host module" wording attributes 199 of 203 and the
    four it drops are all the no-tier wording — the files whose classification
    is `bugs/FORMAL_stdlib_module_names_are_not_classified.md`'s subject.
    """
    attributed = len(sweep_rows(sweep_path))
    total = sum(1 for _ in _sweep_host_lines(sweep_path))
    return attributed, total


def rank(files, unmodelled=frozenset()):
    """{name: {"reach": [files], "alone": [files]}} over `files`.

    `unmodelled` is `SW`'s name for the pretend-a-module-is-absent flag, passed
    through as a frozenset so a caller cannot mutate the flag between files.
    """
    reach, alone = {}, {}
    for path in files:
        found = walls_of(path, unmodelled)
        for name in found:
            reach.setdefault(name, []).append(path)
            if len(found) == 1:
                alone.setdefault(name, []).append(path)
    return {
        name: {"reach": sorted(set(v)), "alone": sorted(alone.get(name, []))}
        for name, v in reach.items()
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--roots", nargs="*", default=None,
                    help="directories or files to walk; default this repo "
                         "plus the stdlib the sweep walks")
    ap.add_argument("--sweep", default=None,
                    help="a sweep log to read the `sweep` column from "
                         "(default the newest bugs/sweeps/sweep-*.txt)")
    ap.add_argument("--unmodelled", action="append", default=[],
                    metavar="NAME",
                    help="pretend NAME has no formal/hostmods/ source, which "
                         "is what 'before this module landed' means; repeat "
                         "for several, so one tree can answer before and after")
    ap.add_argument("--scope", default="repo", choices=sorted(SCOPES),
                    help="which sub-corpus to rank (default repo, the whole "
                         "walk); 'stdlib' is the one a module landing can "
                         "actually move, so it is the one worth re-reading "
                         "after every wave")
    ap.add_argument("--min", type=int, default=1,
                    help="only print rows with at least this many files "
                         "reaching them (default 1, so nothing is hidden)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable rows instead of the table")
    args = ap.parse_args(argv)

    if args.roots:
        roots = tuple(args.roots)
        notes = []
    else:
        roots, notes = SW.default_roots()
    files = SW.find_source_files(roots)
    keep = SCOPES[args.scope]
    scoped = [f for f in files
              if keep(os.path.relpath(os.path.abspath(f), HERE))]
    if len(scoped) != len(files):
        print(f"note: --scope {args.scope} kept {len(scoped)} of "
              f"{len(files)} files", file=sys.stderr)
    files = scoped
    for note in notes:
        print(f"note: {note}", file=sys.stderr)

    unmodelled = frozenset(args.unmodelled)
    log = args.sweep if args.sweep else _newest_sweep()
    swept = sweep_rows(log)
    attributed, total = sweep_coverage(log)
    rows = rank(files, unmodelled)
    sweep_count = {}
    for name in swept.values():
        sweep_count[name] = sweep_count.get(name, 0) + 1

    # Ordered by what would move a file: the `alone` count first, because that
    # is the column a module landing actually converts, and `reach` second
    # because it is the size of the closure behind it. A row with no `alone`
    # file at all is closure, and the table says so in words rather than by
    # omitting the column.
    ordered = sorted(rows.items(),
                     key=lambda kv: (-len(kv[1]["alone"]), -len(kv[1]["reach"]),
                                     kv[0]))
    table = []
    for name, info in ordered:
        if len(info["reach"]) < args.min:
            continue
        table.append({
            "name": name,
            "tier": I.host_module_verdict(name)[0],
            "reach": len(info["reach"]),
            "alone": len(info["alone"]),
            "sweep": sweep_count.get(name, 0),
            "alone_files": [SW.rel(f) for f in info["alone"]],
        })

    if args.json:
        print(json.dumps({"files": len(files),
                          "unreadable": sum(1 for p in files
                                            if module_imports(p) is None),
                          "sweep_log": log,
                          "sweep_lines": {"attributed": attributed,
                                          "total": total},
                          "walls": table}, indent=2))
        return 0

    unparsed = sum(1 for p in files if module_imports(p) is None)
    print(f"host-import wall over {len(files)} files"
          f" ({unparsed} of which the backend cannot read)"
          + (f", pretending {sorted(unmodelled)} unmodelled"
             if unmodelled else "")
          + (f", sweep column from {log}: {attributed} of {total} host-import "
             f"lines attributed"
             if total else ", no sweep log: the sweep column is empty"))
    print()
    print(f"{'name':<24} {'tier':<13} {'reach':>6} {'alone':>6} {'sweep':>6}"
          f"  the files it is alone for")
    for row in table:
        alone_files = ", ".join(row["alone_files"][:3])
        if len(row["alone_files"]) > 3:
            alone_files += f", +{len(row['alone_files']) - 3} more"
        print(f"{row['name']:<24} {row['tier']:<13} {row['reach']:>6}"
              f" {row['alone']:>6} {row['sweep']:>6}  {alone_files}")
    return 0


def _newest_sweep() -> str | None:
    """The newest `bugs/sweeps/sweep-*.txt`, or None.

    Newest by the ROUND NUMBER IN THE NAME and not by mtime: these logs are
    committed in batches and a checkout's mtime is the checkout's, so an mtime
    order would make the column depend on when the tree was cloned. A tie
    between the two architectures of one round goes to **arm64**, because that
    is the corpus backend `tools/formal_sweep.py` sweeps by default — and the
    two arms agree class for class anyway, which is what
    `tools/formal_sweep_parity.py` exists to check.
    """
    import glob
    logs = glob.glob(os.path.join(HERE, "bugs", "sweeps", "sweep-*.txt"))

    def round_of(path):
        base = os.path.basename(path)
        m = re.search(r"sweep-([a-z0-9_]+)-(\d+)", base)
        if not m:
            return (-1, 1, "")
        arch, rnd = m.group(1), int(m.group(2))
        # `False < True`, so the arm64 log of a round beats its x86-64 twin.
        return (rnd, arch.startswith("arm"), arch)

    return max(logs, key=round_of) if logs else None


if __name__ == "__main__":
    raise SystemExit(main())