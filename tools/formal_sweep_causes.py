#!/usr/bin/env python3
"""Rank the TERMINAL causes of a `tools/formal_sweep.py` log.

`formal_sweep.py` classifies every file and prints one line per non-pass, and
its per-family breakdown groups by the SHAPE of the message. That is the right
grouping for a tool that must classify a message it has never seen, and the
wrong one for a person deciding what to work on next: `other refusal` was the
largest bucket in the 2026-09-30 run at 32 files, and it held nine different
constructs. This ranks by what a fix would have to CHANGE.

WHAT A "CAUSE" IS, and why it is not a message
----------------------------------------------
Every printed line of class `codegen` / `codegen/dependency` is peeled to its
terminal message with `formal_sweep.py`'s own `_split_chain` / `_terminal_reason`
(so the chain is followed to the end rather than read at its outermost layer),
the `<file>: <Func>:` noise is stripped, and the result is keyed on a coarse
label. One cause in six modules is one fix that moves six modules; one cause in
one module is a fix that moves one file and says nothing about the other five.

The count is FILES BLOCKED — printed lines, so a dependency chain contributes
one line to the cause at its end and nothing to the cause at its top.

THE COUNT IS AN UPPER BOUND, and this tool says so rather than implying
otherwise. A file's terminal cause is the FIRST refusal the build's walk
reaches, so a module is typically behind a stack of two to four of them, and
fixing one moves the file to the next with the count unchanged. Two causes were
measured this way on 2026-09-30 and BOTH had a ceiling of zero files — see
`bugs/FORMAL_sweep_work_map_2026-09-30.md` §3. Nothing here can tell you a
cause's real value; only re-sweeping the files it blocks can.

OF THOSE FILES, HOW MANY EVEN NAME WHAT THE REFUSING MODULE DECLARES
---------------------------------------------------------------------
`FILES BLOCKED` answers "how big is this row", which is the wrong first
question for a cause whose refusal is about a MODULE rather than about a
construct in the file that was swept. The formal backend builds a dylib for
every module in a file's EAGER import closure (`formal/imports.py`'s
`build_module_dylib`), so a module with no boundary symbol refuses every
importer of its importers — whether or not any of them binds a name in it.
The 2026-09-30 r2 sweep's second-largest row was 38 files on exactly that
refusal, 35 of them behind `std/collections/binary_heap.mojo`, and 34 of THOSE
35 do not contain the string `BinaryHeap` anywhere: they are refused for a type
in a module one line of `std/collections/__init__.mojo` re-exports.

So `uses:` below, per refusing module: how many of the files it blocks name
anything it declares. It is computed from `reflect.export_exclusions` — the one
export rule, the same function the refusal message is built from — and the
declared names are printed with it, so a reader can check the search rather
than trust it. `0 of 35` next to a row of 35 is the difference between "38
files of work" and "38 files waiting on a Stage 5 dependency", and it is the
number that says which. Measured ceilings for that row: 0 files reach `pass`
under either probe (`bugs/FORMAL_dylib_export_gate_ceiling.md`).

THE MARKERS ARE AND-WITHIN / OR-WITHIN, and both halves are load-bearing
-------------------------------------------------------------------------
Each cause is a tuple of ALTERNATIVES and an alternative is a tuple of
substrings that must ALL be present; the cause matches when ANY of its
alternatives is fully present. So `(a,)` OR `(b,)` is two wordings of one
construct, and `(a, b)` is one construct that says both.

Both halves have been got wrong here, in opposite directions, and the second
is the more dangerous one:

  * OR within an alternative, with the alternatives collapsed into one AND —
    the 2026-09-30 draft listed one cause as any of `reads '` / `out of a
    nested` / `has no such field`, matched on `reads '` alone, and reported
    11 files for a cause that has 4. The two outputs are indistinguishable and
    differ by 7, so a count is only as good as its operator.
  * AND across what were alternatives — the MLIR cause was written as three
    sub-groups, one per wording (`is initialized from an MLIR attribute
    template`, `__mlir_attr[`, `__mlir_op is an MLIR dialect construct`), so it
    required a message containing all three, matched nothing, and let 107
    findings fall through to whichever broad cause came next in the list. The
    symptom is a large cause with a nonsensical name and an example that has
    nothing to do with it, which is at least loud; the OR failure above was
    quiet.

ORDER is most specific first and first match wins, so a broad marker placed
early swallows everything under it. Two boundaries matter and both are
load-bearing: `callee has no definition on this path` is asked before
`receiver passed at argument position 0` (they share `… is passed to …`, and
asking the other way round puts 12 findings in the wrong column), and
`frame address passed where a value is wanted` is asked before the same pair.

    python3 tools/formal_sweep_causes.py .tmp/sweep.log          # the table
    python3 tools/formal_sweep_causes.py --json .tmp/sweep.log   # machine-readable
    python3 tools/formal_sweep_causes.py --min 5 .tmp/sweep.log # only above N files

Exit status is 0 whenever the log was read, including when every cause is
non-empty: this tool reports on other tools' output and has no opinion about
whether any of it is a defect.
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load_sweep():
    """`formal_sweep.py`, loaded by path.

    By path rather than by import because that file is a script whose
    `__main__` does the sweep, and importing it for its two regex helpers
    should not be able to start one.
    """
    spec = importlib.util.spec_from_file_location(
        "formal_sweep_under_test", os.path.join(HERE, "formal_sweep.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FS = _load_sweep()

# One printed line: `CLASS: path  (detail)`. The class is upper case and may
# itself contain `/` and `-` (not-answerable/host-import), which is why the
# character class has them.
LINE_RE = re.compile(
    r"^(?P<cls>[A-Z][A-Z/ -]*?): (?P<path>\S+)\s+\((?P<detail>.*)\)\s*$")
# There is deliberately NO `<Func>: ` strip, and a first version of this tool
# had one and got it wrong in a way worth recording. formal/imports.py prefixes
# a message with the file it came from and a lifted method carries its own
# `Owner_method: ` prefix, so it is tempting to strip a leading identifier
# before matching. The regex that did so also matched the first WORD of any
# message whose first word is an identifier — "the module-level comptime binding
# '_mIsSigned' is initialized from an MLIR attribute template" lost its "the",
# and 107 MLIR findings fell through to whatever came next in the list. The
# prefixes are cosmetic: every marker below is a distinctive clause that no
# prefix can hide, and the example line printed per cause keeps the whole
# message, because the file and the function the refusal really came from are
# the useful half of it.

# THE VOCABULARY. Ordered most specific first; first match wins. Every marker is
# a substring quoted from a message the 2026-09-30 arm64 sweep actually
# produced. Within a cause: the outer tuple is a set of ALTERNATIVES (any one
# matching is enough) and each alternative is an AND of substrings.
CAUSES = (
    # ── limits of the TARGET, not of the backend. ──
    # Three wordings of ONE construct, so three alternatives and not one AND.
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     (("is initialized from an MLIR attribute template",),
      ("__mlir_attr[",),
      ("__mlir_op is an MLIR dialect construct",))),
    ("inlined_assembly (a gimple-C runtime construct)",
     (("inlined_assembly:",),)),
    ("value with no representation on this path",
     (("has no representation on this path",),
      ("has no representation for",))),
    ("module exports no public functions",
     (("has no public functions",),)),
    ("a linked module exports no such name",
     (("is a linked module but it exports no",),)),

    # ── a NAME the walk cannot place. Five different reasons, five different
    #    bugs, and the one-word value model is the reason several of them say
    #    what they say. ──
    # ONE cause, not two, and the reason is a limit of the LOG rather than of
    # the taxonomy: `List[Self.T]()` and `DType.bool` produce the SAME terminal
    # message shape ("<Func>: '<Name>' has no home: …"), because the difference
    # is in the AST — whether the refused IdentExpr is the base of a SUBSCRIPT
    # callee or of a MemberExpr — and the printed line does not carry the AST.
    # Splitting them here would mean keying on the refused NAME, which is a list
    # that rots, and it would be a list this repo already has to maintain twice
    # over. So they are one row, the refused-name histogram separates them for a
    # reader who needs to, and `names` is printed per cause for exactly that.
    ("a TYPE name placed as a value (`L[T]()` or `DType.bool`)",
     (("has no home",),)),
    ("a module-global name has no storage",
     (("is bound at module level, and this path has no module-global storage",),)),
    ("a module-level name of ANOTHER module is not exported as a word",
     (("so it is a module-level name of another module",),)),

    # ── the frame / receiver families. The by-reference receiver design, and
    #    each of these is one of its bands. ──
    ("method parameter's field, with no call site to establish it",
     (("is a field access",),)),
    ("frame address escapes: returned by its creator",
     (("is returned from the function that created it",),)),
    ("frame address escapes: aliased out of a method",
     (("did not create the frame",),)),
    ("frame address passed where a value is wanted",
     (("frame address is passed to",),)),
    ("receiver stored in a container",
     (("receiver is stored in a container",),)),
    ("a field of a field: a frame slot holds one word, not a struct",
     (("reads a field of a field",),)),
    ("a field of a nested frame that the struct does not declare",
     (("out of a nested",),)),
    ("a slot's declared type is not declared by its struct",
     (("is the only thing here that could say so",),
      ("does not declare",))),
    ("a name holds a frame address in more than one shape",
     (("holds a frame address in more than one shape",),)),
    ("one parameter, two kinds of value across call sites",
     (("One parameter, two kinds of value",),)),
    ("a slot's declared type is not a value this path can supply",
     (("this slot's DECLARED type is",),)),

    # ── a callee this image has no definition of. Asked BEFORE the pair below,
    #    which shares `… is passed to …`. ──
    ("callee has no definition on this path",
     (("which is a name with no definition in hand",),)),
    ("receiver passed at argument position 0",
     (("in argument position",),)),
    ("receiver passed to a call, position not stated",
     (("is passed to",),)),

    # ── the remaining shapes, each with its own next step. ──
    ("struct construction: arity does not match the fields",
     (("does not match its fields",),)),
    ("a `...` body: no instructions to emit",
     (("stands where this path needs instructions",),)),
    ("print() cannot classify the argument's type",
     (("cannot tell whether",),)),
    ("len() of a value that has no length",
     (("is len() of a value classified as",),)),
    ("write(2) receiver is not a file descriptor",
     (("lowers to the C library's write(2)",),)),
    ("a method on a multi-field struct where a descriptor is meant",
     (("is a method on a Writer",),)),
    ("too many parameters for the arm64 register ABI",
     (("exceeds the 8",),)),
    ("comptime does not fold to a constant",
     (("does not fold to a compile-time constant",),)),
    ("variadic call has no ABI",
     (("has no variadic ABI",),)),
    ("multi-index subscript",
     (("multi-index subscript",),)),
    ("unimplemented intrinsic",
     (("unimplemented intrinsic",),)),
    ("method call on a value receiver is not one of the lowered methods",
     (("lowers only append, close, write",),)),
)

def _check_cause_shape():
    """Every cause is (label, alternatives) and every alternative is a TUPLE.

    Written because this table already carried the mistake once, and the
    failure mode is the quiet kind: an alternative written `(("marker",))` with
    one string in it is still an iterable, so `all(marker in msg for marker in
    alternatives)` tests the message for each CHARACTER of the string and every
    ordinary English message contains all of them. Nothing raises. The cause
    simply collects every message nobody earlier cause claimed — 71 files under
    a name about nested frames, with an example that has nothing to do with
    either — and the only symptom is a number that is wrong.
    """
    for label, alternatives in CAUSES:
        if not isinstance(label, str) or not label:
            raise AssertionError(f"cause label is not a string: {label!r}")
        if not isinstance(alternatives, tuple) or not alternatives:
            raise AssertionError(
                f"{label!r}: alternatives must be a non-empty TUPLE of tuples, "
                f"got {type(alternatives).__name__} — a bare string here is "
                f"iterated CHARACTER by character and matches nearly "
                f"everything")
        for alt in alternatives:
            if not isinstance(alt, tuple) or not alt:
                raise AssertionError(
                    f"{label!r}: each alternative must be a non-empty TUPLE of "
                    f"marker strings, got {type(alt).__name__}")
            for marker in alt:
                if not isinstance(marker, str) or not marker:
                    raise AssertionError(
                        f"{label!r}: marker must be a non-empty string, got "
                        f"{marker!r}")


_check_cause_shape()


# The name inside `'…' has no home` / `is a field access through` / … — the
# quoted identifier the refusal is about, which is often the fastest way to see
# that a cause is really several (`'List'` 36 against `'DType'` 4 says the
# subscript and the member-expression spellings are one row and two problems).
_REFUSED_NAME_RE = re.compile(r"'([A-Za-z_]\w*)'")

# The cause whose refusal is about a MODULE's boundary rather than about a
# construct in the file that was swept. It is named here rather than tested for,
# because the `uses:` column is computed for every cause (it is the same three
# lines) and this is the one where reading it changes what to do next: the fix
# named by the message is a project (monomorphization), and the number beside
# it says the row is not that project's priority.
CAUSE_NO_BOUNDARY_SYMBOL = "module exports no public functions"

DEFAULT_MIN = 1


def classify_message(msg):
    """The cause label for one terminal message, or `"other refusal"`.

    ANY alternative matching is enough; every marker WITHIN an alternative must
    be present. See the module docstring for what happens when either half is
    the other.
    """
    for label, alternatives in CAUSES:
        for markers in alternatives:
            if all(marker in msg for marker in markers):
                return label
    return "other refusal"


# ── `uses:` — of the files a refusing module blocks, how many name anything it
# declares. See the module docstring for why this is the first number to read
# for a cause about a module's boundary.

_decl_cache: dict = {}
_src_cache: dict = {}


def _declared_names(path: str):
    """The top-level names `path` declares, or None if it cannot be read/parsed.

    From `reflect.export_exclusions`, which is the ONE export rule:
    `formal/build.py`'s `no_public_api_reason` builds its message out of the
    same table, so the names searched for below are exactly the names the
    refusal is about and cannot drift from it. Its keys are the declarations
    the rule EXCLUDED — which is the whole population for a cause whose message
    is "this module exports nothing".
    """
    if path in _decl_cache:
        return _decl_cache[path]
    out = None
    try:
        import reflect
        with open(path, encoding="utf-8", errors="replace") as f:
            out = set(reflect.export_exclusions(f.read()))
    except Exception:                                   # noqa: BLE001
        out = None
    _decl_cache[path] = out
    return out


def _source(path: str):
    if path not in _src_cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                _src_cache[path] = f.read()
        except OSError:
            _src_cache[path] = ""
    return _src_cache[path]


_index: dict = {}


def _source_index():
    """`{basename: [paths]}` over this repository and the stdlib, built once.

    The chain in a sweep line names a refusing module by BASENAME
    (`binary_heap.mojo`) and never says where it is, so resolving it from the
    blocked file's own search roots — the obvious thing — works only when the
    module happens to sit in a directory that file can see. `dtype.mojo` is at
    `std/dtype/dtype.mojo` and `binary_heap.mojo` at
    `std/collections/binary_heap.mojo`, so neither resolves from a file under
    `std/sys/`, and the column silently reported "source not resolvable" for
    the two largest rows in the table. An index over the two trees that
    contain every source the sweep can compile is exact instead.

    A basename with more than one match resolves to NOTHING rather than to the
    first one: several stdlib packages have an `__init__.mojo`, and a count
    computed from the wrong one is a number nobody can check.
    """
    global _index
    if _index:
        return _index
    roots = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    try:
        import module_loader
        if module_loader.STDLIB_PATH:
            roots.append(os.path.abspath(module_loader.STDLIB_PATH))
    except Exception:                                   # noqa: BLE001
        pass
    skip = {".git", "__pycache__", "build", ".tmp", "node_modules"}
    idx: dict = collections.defaultdict(list)
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                if name.endswith((".mojo", ".py")):
                    idx[name].append(os.path.join(dirpath, name))
    _index = dict(idx)
    return _index


def _resolve_refuser(refuser: str, blocked_file: str):
    """The source path of a refusing module named by BASENAME in the chain, or
    None when it is absent or ambiguous. See `_source_index`."""
    hits = _source_index().get(os.path.basename(refuser))
    if hits and len(hits) == 1:
        return hits[0]
    return None


def _uses_table(rows_for_label):
    """`[(module, source, blocks, uses, declared_names)]`, biggest first.

    One entry per refusing module, `uses` counting the blocked files that
    contain any name the module declares as a WHOLE WORD. A word boundary and
    not a substring, because `BinaryHeap` inside `BinaryHeapX` is not a use of
    it; and the count is over the blocked files, never over the module itself,
    so `uses <= blocks` is an invariant a reader can check. `source` is None
    when the basename is absent or ambiguous and `uses` is then 0 — which the
    printed note says, so a 0 can never be read as a measurement.
    """
    groups = collections.defaultdict(list)
    for path, refuser in rows_for_label:
        groups[refuser].append(path)
    out = []
    for refuser, files in groups.items():
        src = _resolve_refuser(refuser, files[0])
        declared = sorted(_declared_names(src) or ()) if src else []
        uses = 0
        if declared:
            pat = re.compile(r"\b(?:%s)\b" % "|".join(
                re.escape(n) for n in declared))
            uses = sum(1 for f in files if pat.search(_source(f)))
        out.append((refuser, src, len(files), uses, declared))
    out.sort(key=lambda r: (-r[2], r[0]))
    return out


def rank(log_path):
    """`[{cause, files, in_file, refused_in, example, text}]`, biggest first."""
    rows = []
    with open(log_path, errors="replace") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if m and m.group("cls") in ("CODEGEN", "CODEGEN/DEPENDENCY"):
                rows.append((m.group("cls"), m.group("path"), m.group("detail")))

    blocked = collections.Counter()
    in_file = collections.Counter()
    where = collections.defaultdict(collections.Counter)
    refused_names = collections.defaultdict(collections.Counter)
    examples = {}
    # (path, refuser) per cause, for the `uses:` column — the same two facts
    # `where` counts, kept as rows because the column needs the file each
    # refusal was reported against, not just the count.
    per_cause = collections.defaultdict(list)
    for cls, path, detail in rows:
        hops, term = FS._split_chain(detail)
        refuser = FS._refuser(term)
        msg = FS._terminal_reason(term).strip()
        label = classify_message(msg)
        blocked[label] += 1
        if cls == "CODEGEN":
            in_file[label] += 1
        # Where the refusal really came from, which is NOT the file the sweep
        # swept: for a dependency that is the module at the end of the chain,
        # and the distinction is the whole reason the class exists.
        src = refuser or (hops[-1] if hops else "(this file)")
        where[label][src] += 1
        if src != "(this file)":
            per_cause[label].append((path, src))
        named = _REFUSED_NAME_RE.search(msg)
        if named:
            refused_names[label][named.group(1)] += 1
        if label not in examples:
            examples[label] = (path, msg)

    out = []
    for label, n in blocked.most_common():
        path, msg = examples[label]
        out.append({
            "cause": label,
            "files": n,
            "in_file": in_file[label],
            "refused_in": where[label].most_common(),
            "refused_names": refused_names[label].most_common(),
            "uses": _uses_table(per_cause[label]),
            "example": path,
            "text": msg,
        })
    return out, sum(blocked.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="a formal_sweep.py log (stdout+stderr)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable, one object per cause")
    ap.add_argument("--min", type=int, default=DEFAULT_MIN, dest="minimum",
                    help=f"only causes blocking at least N files "
                         f"(default {DEFAULT_MIN})")
    args = ap.parse_args()

    table, total = rank(args.log)
    shown = [r for r in table if r["files"] >= args.minimum]
    if args.json:
        json.dump(shown, sys.stdout, indent=1)
        print()
    else:
        print(f"{'files':>5} {'in-file':>7}  cause")
        for r in shown:
            print(f"{r['files']:>5} {r['in_file']:>7}  {r['cause']}")
            print(f"        refused in: "
                  f"{', '.join(f'{k} x{v}' for k, v in r['refused_in'])}")
            if r["refused_names"]:
                print("        names:      "
                      + ", ".join(f"{k} x{v}"
                                  for k, v in r["refused_names"][:8]))
            for refuser, src, blocks, uses, declared in r["uses"]:
                if src is None:
                    note = ("NOT MEASURED: the chain names this module by "
                            "basename only and that basename is absent or "
                            "ambiguous in this tree")
                elif not declared:
                    note = ("measured 0, and it cannot be otherwise: the "
                            "module declares no name the export rule could "
                            "exclude")
                elif uses == 0:
                    note = ("the refusal is about the import CLOSURE, not "
                            "about these files — see the module docstring")
                elif uses == blocks:
                    note = "every blocked file uses it, so the row is work"
                else:
                    note = (f"{blocks - uses} of the {blocks} name nothing it "
                            f"declares; the rest of the row is closure")
                print(f"        uses:        "
                      f"{'not measured' if src is None else uses} "
                      f"of {blocks} blocked by {refuser} name anything it "
                      f"declares"
                      + (f" ({', '.join(declared[:6])})" if declared else "")
                      + f"  [{note}]")
            print(f"        example:    {r['example']}")
        shown_files = sum(r["files"] for r in shown)
        print(f"\n{shown_files} of {total} codegen/dependency lines "
              f"accounted for, in {len(shown)} cause(s) of "
              f"{len(table)}")
        print("FILES BLOCKED IS AN UPPER BOUND: a file's terminal cause is the "
              "first refusal reached,\nso fixing one usually moves it to the "
              "next. Measure a cause's real value by\nre-sweeping the files it "
              "blocks — see bugs/FORMAL_sweep_work_map_2026-09-30.md §3.")
        print("`uses:` says how many of a module's blocked files name anything "
              "it declares at all: a row\nwhose uses are 0 is a fact about the "
              "import CLOSURE, and its fix is named in\nthe message rather "
              "than being the row's work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
