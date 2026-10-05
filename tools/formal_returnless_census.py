#!/usr/bin/env python3
"""Which call sites CONSUME the value of a function that returns nothing — the
list behind `model`'s `None` refusal, and the number `make gate` has to be asked
for.

    python3 tools/formal_returnless_census.py [--files N] [--rows 40]
    python3 tools/formal_returnless_census.py --paths DIR [DIR …]

`bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
§0 asks for exactly this and explains why the census it ran is not the answer:
that one was NAME-keyed per file, and every row it reported was an artefact of
it. `utils/coord.mojo` declares `def value` three times (lines 59, 150, 395) and
`_gpu/host/info.mojo` declares `normalize_target_arch` twice; at least one
definition of each RETURNS, and a `{name: has-no-return}` set cannot tell which.
`formal/build.py` already refuses to keep a by-name table whose definitions
disagree about whether they return a frame — "a name whose definitions disagree
is absent from it" — and a census that repeats that imprecision answers a
question nobody asked.

**So the index here is keyed on the NAME and carries every definition, and a
name is only DECIDED when all of its definitions agree.** A name with two
definitions that disagree is reported in its own bucket, with both files and
lines, because "three call sites of `value` consume a return-less function" and
"three call sites of a name that is sometimes return-less" are different claims
and only the first is a refusal.

**What "consumes the value" means here, and why it is the one question worth
asking.** A call's value is consumed everywhere except as the whole value of an
`ExprStmt`: `print(42)` evaluates the call and throws the word away
(`MojoStmt.exprstmt _ => evalBodyEnv callFunc rest env` discards it, which is why
`fn main(): print(42)` proved with no holes). So the walk records a call as a
candidate when its parent is anything other than that one discarding position,
and says which parent it was — an argument of another call, a return, an
assignment, an operand — so a reader can see the two shapes apart.

**What this cannot do.** A same-name function in an unrelated module is still a
candidate (the index is by NAME across the corpus, because resolving imports is
`formal/imports.py`'s job and this instrument is a parse-and-walk on purpose),
and every row prints the files its name is defined in, so a row that is a
different `value` in another module is visible rather than silent. **The list
is an UPPER BOUND on what a `None` refusal would reach**, in the same direction
as every other census in this directory.
"""
import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import fire_compiler as F                                   # noqa: E402
from formal.build import parse_module                       # noqa: E402
import formal.model as M                                    # noqa: E402

DEFAULT_PATHS = [
    os.path.join(ROOT, "formal", "hostmods"),
    ROOT,
    os.path.join(ROOT, "..", "new-modular", "Mojo", "stdlib", "std"),
]


def _returns_a_value(fn) -> bool:
    """Whether `fn`'s body has a `return` WITH a value, at any depth.

    A DELEGATION, and it is one because the rule now decides whether a build is
    refused: `formal/model.py::fn_returns_a_value` is the reader the
    `returnless_value_refusal` asks, and a census that kept a private copy of the
    question would be free to disagree with the refusal about what it measures —
    which is precisely the defect this instrument's own header complains about in
    §0's name-keyed census. Two rules, one implementation, and the docstring
    there carries the reasoning (a nested definition is a different frame; depth
    rather than control flow, because `if c: return 1` with a fall-through end
    still has no value on the other path).
    """
    return M.fn_returns_a_value(fn)


def _declares_a_return(fn) -> bool:
    """Whether `fn` states a return type — `M.fn_declares_a_return`, likewise.

    The doc's rule is "no value-returning `return` AND no declared return type",
    and the second half is what keeps `def quiet(n) -> Int: w = 1; return 0`
    (which agrees with CPython) out of the list: it states a type, so this path
    has said what it means even where the value is not what CPython's is.
    """
    return M.fn_declares_a_return(fn)


def _def_line(fn) -> int:
    """The line to report a definition at.

    `FunctionDef.line` is 0 in this tree — the parser records a line on every
    statement and expression but not on the `def` header — so a definition is
    reported at its first statement, which is the line a reader would jump to
    anyway. Zero would be worse than a small lie: it reads as "line 0" and sends
    nobody anywhere.
    """
    if getattr(fn, "line", 0):
        return fn.line
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if getattr(node, "line", 0):
            return node.line
    return 0


def _callee_name(call):
    """`(name, through_a_receiver)` for a call's callee, or None.

    A dotted callee (`mod.f(…)`) is `through_a_receiver` for this census's
    purposes only in the sense that the method name is all there is; the caller
    prints the spelling so `self.value()` and `coord.value()` are not confused
    in the output.
    """
    func = getattr(call, "func", None)
    if isinstance(func, F.IdentExpr):
        return func.name, False
    if isinstance(func, F.MemberExpr):
        return getattr(func, "member", None), True
    return None, False


def _parent_is_discard(node, parent) -> bool:
    """Whether `node`'s parent throws its value away.

    `ExprStmt.value` is the one position that does: the AST evaluator's
    `MojoStmt.exprstmt` arm does not evaluate the expression at all, so
    `print(42)` cannot disagree with the model about it. Everything else — a
    `return`, an assignment, a call argument, a binary operand, an `if`
    condition — CONSUMES the value, which is what makes a missing `None`
    observable rather than harmless.
    """
    return isinstance(parent, F.ExprStmt) and parent.value is node


# What each consuming position MEANS for this census, in one place, because the
# report and its rows have to agree about which of them is a claim and which is
# a bound. `assigned` is the one that needs the note: nothing here does a
# liveness pass, so a local that is assigned a return-less call and never read
# is not an observable divergence at all.
POSITION_NOTES = {
    "returned": "the callee's own result is None \u2014 the clearest "
                "divergence, and CPython's",
    "argument of a call": "the doc's \u00a70 shape (one argument too deep)",
    "assigned": "WEAKEST: the local may never be read, and nothing here does a "
                "liveness pass, so this row count is an upper bound on "
                "observable ones",
}


def position_file_table(rows, same_file_only: bool = True, limit: int = 6):
    """`[(position, [(file, sites), …], (n_files, n_sites))]` for the report.

    Each row is `(same_file, path, position)` and nothing else, deliberately: the
    report's own rows are seven-tuples, and a helper that indexed a seventh
    element would be a helper whose contract is a line of someone else's loop.

    **The position count alone does not decide anything and this table is what
    does.** A `None` refusal is one decision asked at one POSITION, and what it
    costs is decided by which files it lands in: the `returned` bucket is 76
    sites over 19 files on this corpus, and 62 of them are in one host module the
    gate compiles — so the same 76 is a decision in one file or in nineteen, and
    only the second reading is the one a reader can act on. `bugs/
    FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
    §"What is still not fixed" asks for a liveness pass before any of these
    positions can be asked at; this is what it costs to learn that for one of
    them, and it costs one walk of rows already collected.

    A bucket spread over fewer than `limit` files is reported whole, so the
    spread line is only ever printed when there is something it is summarising,
    and a single-file bucket reads as the single line a decision is made from.
    """
    out = []
    def _keep(row):
        return row[0] == same_file_only or not same_file_only

    positions = collections.Counter(r[2] for r in rows if _keep(r))
    for pos, total in positions.most_common():
        here = collections.Counter(r[1] for r in rows
                                   if r[2] == pos and _keep(r))
        top = here.most_common(limit)
        out.append((pos, top,
                    (len(here) - len(top), total - sum(n for _p, n in top))))
    return out


def _position(parent) -> str:
    """The parent position a consumed call sits in, for the report."""
    p = parent
    kind = type(p).__name__
    if isinstance(p, F.CallExpr):
        return "argument of a call"
    if isinstance(p, F.ReturnStmt):
        return "returned"
    if isinstance(p, (F.AssignStmt, F.VarDecl, F.AugAssignStmt)):
        return "assigned"
    if isinstance(p, F.BinaryOp):
        return f"operand of `{p.op}`"
    if isinstance(p, F.UnaryOp):
        return f"operand of `{p.op}`"
    if isinstance(p, F.IfStmt):
        return "a condition"
    if isinstance(p, F.WhileStmt):
        return "a while condition"
    if isinstance(p, F.TernaryExpr):
        return "a conditional expression"
    if isinstance(p, F.SubscriptExpr):
        return "a subscript index"
    return kind


def collect(paths):
    """`{name: [(file, line, returns_a_value, declares_a_return)]}`, plus rows.

    The index is over the WHOLE corpus, not per file, because a call into an
    imported module is one of the two shapes the doc's census could not see and
    it is a large share of what a `None` refusal would reach.
    """
    index: dict = collections.defaultdict(list)
    structs: set = set()
    call_rows: list = []
    files = []
    for base in paths:
        if os.path.isfile(base):
            files.append(base)
            continue
        for dirpath, dirs, names in os.walk(base):
            if "/build/" in dirpath or dirpath.endswith("/build"):
                continue
            # `.tmp` and `.git` are not CORPUS, they are this worktree's
            # scratch and its history, and a census whose numbers move with
            # whatever a scratch build left behind cannot be quoted in a bug
            # doc \u2014 which is the only reason this instrument exists.  It is
            # pruned in place because `DEFAULT_PATHS` includes the repository
            # root, so the walk descends into `.tmp/<test tmpdir>/` and finds
            # `.mojo` files a test wrote an hour ago.
            dirs[:] = [d for d in dirs if d not in (".tmp", ".git", "__pycache__")]
            files += [os.path.join(dirpath, n) for n in sorted(names)
                      if n.endswith(".mojo")]
    seen = set()
    n_defs = n_returnless = 0
    for path in sorted(files):
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                stmts = parse_module(f.read(), filename=path)
        except Exception:                                  # noqa: BLE001
            continue
        # `iter_nodes_with_parent` is THE walker for this (`formal/model.py`'s
        # own note: three private copies of this loop are three chances for one
        # of them to see a node the others do not), and it hands over the parent,
        # which is the whole of what "is this value consumed" is a question
        # about.
        for node, parent in M.iter_nodes_with_parent(list(stmts)):
            if isinstance(node, F.StructDef):
                # A call to a STRUCT name is a construction, not a call to a
                # function that returns nothing — `Foo(1)` binds a frame and
                # `formal/model.py` has a whole value model for it. Counting
                # constructions here is what put 456 rows in
                # `formal/hostmods/argparse.mojo` on the first run of this
                # instrument: that file constructs a hundred action objects.
                structs.add(node.name)
                continue
            if isinstance(node, F.FunctionDef):
                # A GENERATOR yields rather than returns, and its "return
                # value" is the generator object — so `def _flatten(…)` with a
                # `yield` in it and no `return` is NOT a function that returns
                # nothing, and counting it would put every `for x in _flatten(y)`
                # in the list. `is_generator` is the parser's own answer and
                # `is_async` is the same question for a coroutine.
                if getattr(node, "is_generator", False) or \
                        getattr(node, "is_async", False):
                    returns = declares = True
                else:
                    returns = _returns_a_value(node)
                    declares = _declares_a_return(node)
                index[node.name].append(
                    (os.path.relpath(path, ROOT), _def_line(node), returns,
                     declares))
                n_defs += 1
                n_returnless += not (returns or declares
                                     or getattr(node, "is_generator", False)
                                     or getattr(node, "is_async", False))
                continue
            if not isinstance(node, F.CallExpr):
                continue
            name, through_recv = _callee_name(node)
            if not name or name in structs or _parent_is_discard(node, parent):
                continue
            call_rows.append((os.path.relpath(path, ROOT), node.line, name,
                              through_recv, _position(parent)))
    return index, call_rows, n_defs, n_returnless, len(structs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--paths", nargs="*", default=None,
                    help="files or directories to walk (default: this "
                         "repository, formal/hostmods and the stdlib)")
    ap.add_argument("--rows", type=int, default=40,
                    help="how many candidate rows to print")
    args = ap.parse_args(argv)

    index, calls, n_defs, n_returnless, n_structs = collect(
        args.paths or DEFAULT_PATHS)
    decided = {name: defs[0][2] and defs[0][3]
               for name, defs in index.items()
               if len(defs) == 1 or all(d[2] == defs[0][2]
                                        and d[3] == defs[0][3]
                                        for d in defs)}
    undecided = sorted(n for n in index if n not in decided)

    print(f"definitions: {n_defs}   "
          f"of which return nothing: {n_returnless}   "
          f"structs (construction sites, excluded): {n_structs}")
    print(f"names: {len(index)}   decided: {len(decided)}   "
          f"undecided (definitions disagree): {len(undecided)}")
    if undecided:
        print("  the undecided names — a refusal cannot be asked about "
              "these, and they are where a by-name census goes wrong:")
        for name in undecided[:12]:
            sites = ", ".join(f"{f}:{ln}"
                              for f, ln, _r, _d in index[name][:6])
            print(f"    {name:24s} {sites}")

    kinds = collections.Counter()
    rows: list = []
    for path, line, name, through_recv, position in calls:
        if name not in decided:
            kinds["callee's name is undecided"] += 1
            continue
        if decided[name]:
            kinds["callee returns something"] += 1
            continue
        defs = index[name]
        # SAME FILE or not is the difference between a candidate a refusal would
        # really reach and one that is a different function of the same name
        # elsewhere in the corpus: a module dylib refuses on what its own
        # imports resolve to, and a name defined only in another module is
        # exactly the ambiguity this index cannot settle without `formal/
        # imports.py`'s binding table.
        same_file = any(d[0] == path for d in defs)
        kinds["CANDIDATE (same file)"
              if same_file else "CANDIDATE (same name, other file)"] += 1
        rows.append((same_file, path, line, name, through_recv, position,
                     defs))
    rows.sort(key=lambda r: (not r[0], r[1], r[2]))
    print()
    print("call sites whose value is consumed, by what the callee is:")
    for k, v in kinds.most_common():
        print(f"   {k:38s} {v:5d}")
    n_same = sum(1 for r in rows if r[0])
    per_file = collections.Counter(r[1] for r in rows if r[0])
    by_position = collections.Counter(r[5] for r in rows if r[0])
    print()
    print("the same-file candidates by where the value goes, which is not one "
          "claim:")
    for pos, n in by_position.most_common():
        print(f"   {pos:24s} {n:5d}  {POSITION_NOTES.get(pos, '')}")
    print("…and each bucket by FILE, because the position count alone decides "
          "nothing\n   and the file list is what a decision is made from. A "
          "bucket is printed when it is\n   spread over more than one file, "
          "when it is large, or when it is `returned`\n   \u2014 the last "
          "because that is the one with no other\n   observable escape (see "
          "`position_file_table`).")
    for pos, top, (n_files, n_sites) in position_file_table(
            [(r[0], r[1], r[5]) for r in rows]):
        total = sum(n for _p, n in top) + n_sites
        if pos != "returned" and n_files == 0 and total < 20:
            continue
        print()
        print(f"the `{pos}` sites, by file \u2014 what a refusal asked HERE "
              f"would reach:")
        for path, k in top:
            print(f"   {k:5d}  {path}")
        if n_files:
            print(f"   {'':5s}  {n_files} further file(s), {n_sites} sites, "
                  f"one or two each")
        print()
    print()
    print(f"files with at least one same-file candidate: {len(per_file)}   "
          f"candidate sites: {n_same}")
    for path, n in per_file.most_common(12):
        print(f"   {n:5d}  {path}")
    print(f"candidates: {len(rows)}   of which the definition is in the SAME "
          f"FILE as the call: {n_same}")
    print("   The same-file number is what a refusal asked per module would "
          "reach;\n   the rest is the same NAME resolving to a return-less "
          "function elsewhere in the\n   corpus, which is this instrument's "
          "stated upper bound (an import resolution is\n   `formal/imports."
          "py`'s job and a parse-and-walk cannot do it).")
    for same_file, path, line, name, through_recv, position, defs in \
            rows[:args.rows]:
        how = "through a receiver" if through_recv else "bare name"
        where = ", ".join(f"{f}:{ln}" for f, ln, _r, _d in defs[:4])
        tag = "same file" if same_file else "OTHER FILE, same name"
        print(f"   [{tag}] {path}:{line}: {name}(…) [{position}, {how}] "
              f"defined at {where}")
    if len(rows) > args.rows:
        print(f"   … and {len(rows) - args.rows} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())