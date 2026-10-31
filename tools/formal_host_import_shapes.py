#!/usr/bin/env python3
"""What is left of the host-import wall, ranked by the SHAPE of what it spells.

    python3 tools/formal_host_import_shapes.py [-h] [--sweep LOG] [--min N]
    python3 tools/formal_host_import_shapes.py --json
    python3 tools/formal_host_import_shapes.py --files NAME

`tools/formal_sweep_causes.py --host` ranks the same rows by FILES BLOCKED and
adds a `uses:` column that answers "do the blocked files name anything the
refusing module declares". That column has two limits, and this file exists
because both of them decide what is worth writing.

**THE FIRST LIMIT: for a module with no `.py` source in this interpreter's
stdlib, `uses:` is a LOWER BOUND and says so.** `itertools`, `builtins`,
`resource` and `pwd` are frozen or builtin, so the tool cannot enumerate their
declarations by parsing a source file and prints `>=2` / `>=3` / `>=1` rather
than a count. That is the right answer to the question it asked and it is not
an answer to the question this project asks, because the question is answerable
from the other end: **the swept file's own AST says what it spells.** Every use
here is read off `ast.parse` of the blocked file, so a C module's row gets a
real count.

**THE SECOND, AND IT IS THE ONE THAT DECIDES THE QUEUE: "the file names it" is
not "a `.mojo` module can answer it".** A value on this path is ONE 64-bit word
(`doc/ABI.md`), and a module function publishes words. So:

    collections.Counter(xs)                a call whose answer is a dict
    pwd.getpwnam(n).pw_dir                 a field read through a call's result
    plistlib.load(f)["ProductVersion"]     a subscript through a call's result
    os.getenv(k) + "/x"                    a concatenation, i.e. a first-class buffer
    tokenize.STRING                        a module-level name with no call
    functools.lru_cache(maxsize=1)         a decorator, silently DROPPED

and of those only the first is even the right SHAPE, and it is still not
answerable — a dict is a frame blob. So the column this file prints is the
shape, per name, and the docstring below says exactly what a shape does and
does not license. **A `WORD` shape is NECESSARY and NOT SUFFICIENT.** A tool
that printed a "modellable" verdict would be asserting something it cannot
measure, and the two verdicts it could get wrong are both expensive: a
`Counter` shipped as a blob is the approximation `FORMAL_hashlib_sha3_and_
blake2s_absent` declined to ship, and a `pwd` shipped with the struct read
folded in would answer `0` for a field and exit 0.

WHY A NEW FILE AND NOT A COLUMN ON `formal_sweep_causes.py`
-----------------------------------------------------------
Three reasons, and the third is the one that decided it.

  * The question is a different one. That tool asks about the REFUSING module
    (what does it declare?); this asks about the BLOCKED file (what does it
    spell, and in what shape?). One oracle per question, asked where it is used,
    which is the rule `is_cpython_stdlib` was split out for.
  * `tools/formal_sweep_causes.py` and `tools/formal_host_import_wall.py` are
    both being edited by live branches (`git branch --no-merged master` lists
    five), and a wave that adds a column to a contested file merges as a
    conflict rather than as work.
  * The two existing tools print what a SWEEP found. This one prints, per row,
    how many of those files still spell the module **in the tree as it is now**
    — the `live` column — which is how a wave's effect is measured without
    re-sweeping, and the reason the file-list is the sweep's while the shapes
    are read fresh off disk. `itertools` reads `files=14 live=0` after
    `test_formal_dylib.py` and `test_module_cache.py` dropped the import, which
    is the same measurement `test_formal_dylib.py`'s commit message reports and
    is available here for any row.

THE SHAPES, AND WHAT EACH ONE NEEDS
------------------------------------
Each is measured, not guessed, from the parent chain of the `mod.name` node:

  `WORD`    `mod.f(...)` and the result is used as a value, or the call sits in
            an argument, a comparison or a return. **The only shape a module
            function can publish** — and even then the ANSWER has to be a word,
            which is a fact about the module rather than about the call site.
  `FIELD`   `mod.f(...).attr`, or `mod.Class.attr`. A read of a field through a
            value whose binding this image cannot see; measured on this tree,
            `os.getenv("HOME").size` is refused by name with a message saying
            so, and `platform.machine().upper()` builds an image that binds a
            symbol `upper` that nothing provides.
  `SUBSCRIPT` `mod.f(...)[k]`. A container behind the word.
  `CONCAT`  `mod.f(...) + x`. A buffer the answer has to be laid down in.
  `FSTRING` `f"{mod.f(...)}"`. Same buffer as `CONCAT`, and the string
            composition refusal is its own row (`FORMAL_string_composition_
            has_no_buffer`).
  `BARE`    `mod.NAME` with no call anywhere above it. Refused as a read of a
            module-level name that is not folded to a literal; measured,
            `os.sep` is refused with the module's own export list in the
            message. **A constant in a host module is a zero-argument FUNCTION
            for this reason** (`formal/hostmods/os/__init__.mojo`), so every
            `BARE` here is a caller that has to be re-spelled rather than a
            module that has to be written.
  `MODULE` the MODULE OBJECT used as a value — `dir(builtins)`,
            `importlib.util.find_spec(name)`. Measured refusal: "a module is not
            a value this path can place: there is no register, frame slot or
            `__DATA` word for it". It is the shape two whole rows need
            (`builtins`, `importlib.util`), and it is NOT a dead import however
            it reads in a column of counts.
  `STAR`   `from M import *`. Any name in the file could have come from `M`,
            so the row is reported unresolved rather than guessed at.
  `DECORATOR` the bound name is the decorator of a `def`/`class`. Measured on
            this tree, a decorator on a function OR a class is DROPPED,
            silently, by both backends
            (`bugs/COMPILE_FAIL_decorator_application_dropped.md`), so
            shipping the name would make the program build and enforce nothing
            — the outcome `formal/hostmods/enum.mojo` declines for `unique` and
            `verify`.
  `DEAD`    the module is imported and nothing is read through it. **A dead
            import is a row about nothing**: it blocks the file for the same
            reason an absent module would, and `formal_sweep_causes.py`'s
            `mentions` column is the measure that says so. `tools/
            apply_extraction.py`'s `import copy` was one, and deleting it closed
            the `copy` row's only `alone` file.

NOT A VERDICT, DELIBERATELY
---------------------------
There is no "work"/"not work" column, because deciding that needs the module's
own semantics and not the call site's syntax, and a tool that guessed would be
the `uses:`-as-a-total mistake in a new place. What this file gives a reader is
the pair the decision needs: how many files, and what shape each one is in. The
tier (`formal/imports.py::host_module_tier`, read not copied) and the model's
existence (`formal/hostmods/`) are printed beside them, because
"modelled, and every use is a `WORD`" and "unreachable" and "modelled, and the
only use is a `FIELD` through a call" are three different mornings.
"""

import argparse
import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.imports as _imports  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One printed line of class `not-answerable/host-import`. The path is the first
# space-delimited token after the label, and the MODULE is the one in the LAST
# `imports 'NAME', which is a host module` of the chain: a chain reads
# `a.py imports 'x', which cannot be built either: b.py imports 'y', which is a
# host module`, so every module in it but the last is a REPOSITORY file and the
# host module is the terminal one the tier sentence belongs to.
_HOST_LINE = re.compile(
    r"^NOT-ANSWERABLE/HOST-IMPORT:\s+(\S+)\s+\((.*)$")
_TERMINAL = re.compile(
    r"imports '([A-Za-z_][\w.]*)',\s*which is a (?:host module|CPython "
    r"standard-library module)")


def default_sweep():
    """The newest sweep log, by `formal_host_import_wall.py`'s own rule.

    IMPORTED rather than reimplemented, and the reason is that the naive version
    is wrong in a way this tool would have shipped: the logs are
    `sweep-<arch>-<n>.txt`, so a plain name sort ends on `sweep-x86-9.txt` —
    round NINE, the second-oldest x86-64 log in the directory — because `9`
    sorts after `13`. That tool already answers the question, with the round
    number, the mtime argument and the arm64 tie-break all written down, so
    this file reads its answer rather than holding a second copy of a rule that
    a sweep would otherwise be ranked against the wrong snapshot of.
    """
    import tools.formal_host_import_wall as _wall
    return _wall._newest_sweep()


def parse_log(path):
    """`[(file, module)]` for every `not-answerable/host-import` line.

    A line whose terminal module cannot be found is DROPPED rather than guessed
    at, and the count is printed: a row keyed on the wrong module is worse than
    a missing row, because it names a module the file does not import.
    """
    rows, missed = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _HOST_LINE.match(line)
            if not m:
                continue
            tail = _TERMINAL.search(m.group(2))
            if not tail:
                missed += 1
                continue
            rows.append((m.group(1), tail.group(1)))
    return rows, missed


def _parents(tree):
    m = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            m[child] = node
    return m


def _shapes_from(node, parent):
    """Every shape on the chain from `node` outward, as a SET.

    The walk keeps going after a shape is recorded, because
    `mod.f(x).attr[k]` is two shapes and reporting only the outermost would say
    a `SUBSCRIPT` where the thing standing in the way is also a `FIELD`.

    `BARE` is the shape when NO CALL was crossed, and that is the whole reason
    this is a walk rather than a parent lookup: `os.sep` and `os.getenv("HOME")`
    have the same immediate parent shape to a reader who only looks one step
    out, and they are different problems — one is refused as a read of a
    module-level name and the other lowers. `tokenize.STRING` used as an operand
    of `==`, and `resource.RUSAGE_SELF` used as an argument, are both `BARE`
    here for the same reason: nothing on either chain is a call OF them.
    """
    shapes, cur, called = set(), node, False
    while True:
        p = parent.get(cur)
        if p is None:
            break
        if isinstance(p, ast.Call) and p.func is cur:
            shapes.add("WORD")
            called = True
        elif isinstance(p, ast.Attribute) and p.value is cur:
            shapes.add("FIELD")
        elif isinstance(p, ast.Subscript) and p.value is cur:
            shapes.add("SUBSCRIPT")
        elif isinstance(p, ast.BinOp) and isinstance(p.op, ast.Add):
            shapes.add("CONCAT")
        elif isinstance(p, ast.JoinedStr):
            shapes.add("FSTRING")
        elif isinstance(p, ast.FormattedValue):
            # CPython 3.12+ parses `f"{f(x)}"` as
            # JoinedStr(FormattedValue(value=Call(...))), so the f-string is one
            # step further out than the chain reaches and a walk that stopped
            # here would report a plain `WORD` — which is the shape that reads
            # as work for something the string-composition refusal owns.
            cur = p
            continue
        else:
            break
        cur = p
    if not called:
        shapes.add("BARE")
    return shapes


def _attr_path(node, parent):
    """`node.attr` plus every attribute above it, in SOURCE order.

    `node` is the innermost (`a.b` in `a.b.c`) and the walk goes outward, so
    appending is already the source order — `a.b.c` gives `["b", "c"]`, which is
    what "consume the dotted tail of `import a.b`" compares against. Reversing it
    is the bug that reads `importlib.util.spec_from_file_location` as a name
    called `spec_from_file_location.util`.
    """
    parts, cur = [node.attr], node
    while True:
        p = parent.get(cur)
        if isinstance(p, ast.Attribute) and p.value is cur:
            parts.append(p.attr)
            cur = p
            continue
        return parts


def uses_in(path, module):
    """`{spelled_name: {shape, …}}` for one file's uses of `module`, or `None`.

    `None` means the file could not be read or parsed, which is a different
    fact from "uses nothing" and is reported as `?` rather than as a zero — a
    sweep log names paths relative to the tree it ran in, and a file that has
    moved is not a file that stopped importing the module.

    Four spellings are followed, because CPython has four and reading only some
    of them is how a row looks busy when it is not:

      * `import M`         then `M.f(...)`   — the attribute is the use;
      * `import M as A`    then `A.f(...)`   — the same, through the ALIAS;
      * `import a.b`       then `a.b.f(...)` — binds `a`, not `a.b`, and the name
        is spelled relative to the MODULE, so `importlib.util.find_spec` is a
        name out of `importlib.util` and not out of `importlib`;
      * `from M import f`  then `f(...)`     — the bound NAME is the use, and a
        reader that only looks for `M.something` reports `f` as unused.

    A name bound and never read is `DEAD`, which is the reading
    `tools/apply_extraction.py`'s `import copy` got: a dead import blocks a file
    for the same reason an absent module does, and
    `tools/formal_sweep_causes.py`'s `mentions` column is the measure that says
    so. `from M import *` is reported as `STAR` and not resolved, because any
    name in the file could have come from `M` and guessing which is worse than
    saying so.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None
    parent = _parents(tree)
    out = {}

    def note(name, shapes):
        out.setdefault(name, set()).update(shapes)

    loads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
    attrs = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)]

    # `(local, spelled, is_module, dotted_tail)` per binding.
    bindings, star = [], False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module:
                for alias in node.names:
                    if alias.name == "*":
                        star = True
                        continue
                    bindings.append((alias.asname or alias.name,
                                     "%s.%s" % (module, alias.name), False, []))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b` imports `a` too, so a row keyed on `a` is a row
                # this file is in. Matching only `alias.name == module` would
                # miss it — and a row that quietly omits a file reads as a row
                # that shrank.
                if alias.name != module and not alias.name.startswith(
                        module + "."):
                    continue
                # The dotted tail is consumed only when the ROW is that exact
                # dotted module, because only then is the tail part of the
                # module's own path rather than a path THROUGH it. For row
                # `importlib.util` the file's `import importlib.util` makes
                # `find_spec` a name out of the module; for row `zlib` the same
                # line is a path through `zlib.util`, and `zlib.util.crc32` is
                # what the file spells.
                dotted = alias.name.split(".")
                bindings.append((alias.asname or dotted[0], module, True,
                                 dotted[1:] if module == alias.name else []))

    # A Name that is the `.value` of an Attribute is the module being REACHED
    # THROUGH, not used: `zlib.crc32` does not also read `zlib` as a value, and
    # counting it would put a `MODULE` on every row in the table.
    attr_bases = {a.value for a in attrs if isinstance(a.value, ast.Name)}
    for local, spelled, is_module, tail in bindings:
        read = False
        for attr in attrs:
            if attr.value.id != local:
                continue
            read = True
            path = _attr_path(attr, parent)
            if tail and path[:len(tail)] == tail:
                path = path[len(tail):]
            note(".".join([spelled] + path), _shapes_from(attr, parent))
        for name in loads:
            if name.id != local or name in attr_bases:
                continue
            read = True
            if is_module:
                # `dir(builtins)`, the module `importlib.util.find_spec` is
                # reached through: the MODULE OBJECT as a value, which is its
                # own shape and the one two whole rows need. Measured refusal,
                # for `os.sep`: "a module is not a value this path can place:
                # there is no register, frame slot or `__DATA` word for it".
                note(spelled, {"MODULE"})
            else:
                note(spelled, _shapes_from(name, parent))
        if not read:
            note(spelled, {"DEAD"})

    # Decorator position, for every name this file binds or reads out of the
    # module. A dropped decorator is a program that builds and enforces nothing,
    # so it is its own shape even where the same name is also called.
    local_to_spelled = {local: spelled for local, spelled, _, _ in bindings}
    for node in ast.walk(tree):
        for attr in ("decorator_list", "decorators"):
            for dec in getattr(node, attr, None) or []:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Name):
                    spelled = local_to_spelled.get(target.id)
                    if spelled:
                        note(spelled, {"DECORATOR"})
                elif (isinstance(target, ast.Attribute)
                      and isinstance(target.value, ast.Name)):
                    spelled = local_to_spelled.get(target.value.id)
                    if spelled:
                        note("%s.%s" % (spelled, target.attr), {"DECORATOR"})
    if star:
        note("%s.*" % module, {"STAR"})
    return {k: (v or {"DEAD"}) for k, v in out.items()}


def dead_host_imports(root="."):
    """Every `.py` file under `root` with a host import nothing reads through it.

    `rows_for` reads the files a SWEEP blocked, which is the right set for
    ranking a row and the wrong set for this: **a dead host import blocks its
    file for exactly the reason an absent module does**, whether or not the
    sweep ever got as far as naming the module — a file that stops on
    `collections` before it reaches `itertools` is invisible in the `itertools`
    row and just as blocked. So this walks the tree instead, which is what found
    the four `collections` files in §3 of the bug doc and the four below it.

    `.py` ONLY, and the restriction is not a shortcut: a `.mojo` file is not
    Python, so `ast.parse` on one either fails or succeeds on a syntax that is
    not the file's — which is why
    `tools/formal_sweep_causes.py::_host_mentions_module` returns `None` for a
    Mojo path rather than answering. A `.mojo` file's imports are read by the
    backend's own reader (`formal/imports.py::imported_modules`, over
    `fire_compiler`'s node classes), so a Mojo dead import is a real gap and
    this tool deliberately says nothing about it.

    `.git`, `build/`, `bugs/`, `.tmp/` and every dotted directory are skipped:
    the first two are not source, the third is prose and the last is scratch.
    """
    import glob as _glob
    skipped = {".git", "build", "bugs", ".tmp", "__pycache__", "node_modules"}
    out = []
    for path in _glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        parts = set(os.path.normpath(path).split(os.sep))
        if parts & skipped or any(p.startswith(".") for p in parts):
            continue
        found = _dead_in(path)
        if found:
            out.append((os.path.relpath(path, root), found))
    return out


def _dead_in(path):
    """`[(module, bound_local)]` for the host imports `path` never reads."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return []
    binds = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module or not _is_host(node.module):
                continue
            for alias in node.names:
                if alias.name != "*":
                    binds[alias.asname or alias.name] = (
                        "%s.%s" % (node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if _is_host(top):
                    binds[alias.asname or top] = top
    if not binds:
        return []
    reads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            reads.add(node.id)
        elif (isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Name)):
            reads.add(node.value.id)
    return sorted({v for k, v in binds.items() if k not in reads})


def _is_host(name):
    try:
        return bool(_imports._is_host_module(name))
    except Exception:                                    # noqa: BLE001
        return False


def rows_for(sweep, min_files=1):
    parsed, missed = parse_log(sweep)
    by_module = {}
    for path, module in parsed:
        by_module.setdefault(module, set()).add(path)
    out = []
    for module in sorted(by_module, key=lambda m: (-len(by_module[m]), m)):
        files = sorted(by_module[module])
        if len(files) < min_files:
            continue
        names, unreadable, live = {}, 0, 0
        for path in files:
            found = uses_in(path, module)
            if found is None:
                unreadable += 1
                continue
            if found:
                live += 1
            for name, shapes in found.items():
                names.setdefault(name, set()).update(shapes)
        shapes = sorted({s for v in names.values() for s in v})
        out.append({
            "name": module,
            "files": len(files),
            "live": live,
            "unreadable": unreadable,
            "needs": shapes,
            "names": {k: sorted(v) for k, v in sorted(names.items())},
            "tier": _tier(module),
            "model": _model(module),
        })
    return out, missed, len(parsed)


def _tier(module):
    try:
        return _imports.host_module_tier(module) or "unclassified"
    except Exception:                                    # noqa: BLE001
        return "unclassified"


def _model(module):
    path = os.path.join(HERE, "formal", "hostmods", module + ".mojo")
    return "formal/hostmods/" + module + ".mojo" if os.path.isfile(path) else "-"


def _fmt(shapes):
    return ",".join(shapes) if shapes else "-"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sweep", default=None,
                    help="a sweep log to read the blocked files from "
                         "(default: the newest bugs/sweeps/sweep-*.txt)")
    ap.add_argument("--min", type=int, default=1,
                    help="only print rows with at least this many blocked "
                         "files (default 1, so nothing is hidden)")
    ap.add_argument("--files", metavar="NAME", default=None,
                    help="print every blocked file for one module and stop")
    ap.add_argument("--dead", action="store_true",
                    help="instead of the ranking: every .py file in the tree "
                         "with a host import nothing reads through it. This is "
                         "the set the ranking CANNOT see, because a file that "
                         "stops on `collections` before it reaches `itertools` "
                         "is invisible in the `itertools` row and just as "
                         "blocked")
    ap.add_argument("--root", default=".", metavar="DIR",
                    help="what --dead walks (default: the repository root)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable rows instead of the table")
    args = ap.parse_args(argv)

    if args.dead:
        found = dead_host_imports(args.root)
        for path, names in found:
            print(f"{path}\t{', '.join(names)}")
        print(f"\n{sum(len(n) for _, n in found)} dead host import(s) in "
              f"{len(found)} file(s) under {args.root} (`.py` only; a `.mojo` "
              f"file's imports are read by the backend's own reader, so this "
              f"tool says nothing about them)")
        return 1 if found else 0

    sweep = args.sweep or default_sweep()
    if not sweep:
        print("no sweep log found; pass --sweep", file=sys.stderr)
        return 2
    rows, missed, total = rows_for(sweep, args.min)
    if args.files:
        parsed, _ = parse_log(sweep)
        for path, module in sorted(parsed):
            if module != args.files:
                continue
            found = uses_in(path, module)
            if found is None:
                print(f"{path}\t(unreadable)")
            elif not found:
                print(f"{path}\t(imports it, reads nothing through it)")
            else:
                for name in sorted(found):
                    print(f"{path}\t{name}\t{_fmt(sorted(found[name]))}")
        return 0
    if args.json:
        print(json.dumps({"sweep": sweep, "lines": total, "unparsed": missed,
                          "rows": rows}, indent=1))
        return 0
    print(f"host-import shapes from {sweep}: {total} line(s), "
          f"{missed} with no terminal module in them")
    print()
    print("module            tier           model  files live  needs"
          "          what the files spell")
    for r in rows:
        spells = "; ".join(f"{k}[{_fmt(v)}]" for k, v in r["names"].items())
        model = "written" if r["model"] != "-" else "-"
        print(f"{r['name']:<16} {r['tier']:<14} {model:<7} {r['files']:>5} "
              f"{r['live']:>4}  {_fmt(r['needs']):<18} {spells[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())