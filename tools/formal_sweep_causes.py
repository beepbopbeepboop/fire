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
`bugs/FORMAL_sweep_work_map_2026-09-30.md` §3. The current map, which every
number below comes from, is `bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`.
Nothing here can tell you a cause's real value; only re-sweeping the files it
blocks can.

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

A MARKER IS A CONTRACT WITH A MESSAGE THAT CAN BE REWORDED, and breaking it is
invisible from here
-----------------------------------------------------------------------------
A marker is a quoted substring of a message `formal/` owns. When a worker
rewords that message — which is a routine improvement, and a good one — every
cause keyed on the old wording silently drops to zero and its files fall into
`other refusal`, which is the bucket that means "this tool has not classified
this". That is the quiet failure mode again, one level up: nothing raises, the
table still sums to the total, and the number that changed is the number a
planner would act on. It happened here for real between the two 2026-09-30
sweeps: `formal-module-attr` reworded `… so it is a module-level name of
another module` into `… and it is a module-level name of another module`, and
4 findings walked out of that row into `other refusal` with nothing to show
for it.

So this table lists BOTH wordings where a message has had one, and — the part
that keeps doing it from happening again — `test_formal_sweep.py` asserts that
every marker matches at least one refusal the sweep actually produced, by
building the message from `formal/`'s own text rather than from a copy in the
test. A reword that breaks a marker fails a test instead of quietly moving a
column.

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
    # ABOVE the broad `has no representation` cause below, and it has to be:
    # `model.multi_index_refusal` ENDS with "so a tuple index has no
    # representation on this path", so a multi-index message satisfies both and
    # first match wins. Asked the other way round this cause collects nothing
    # forever and nothing says so — the precedence failure this file's sibling
    # test (`test_refusal_taxonomy.py`) exists to catch, in the table that
    # ranks the causes rather than the one that summarises them.
    ("multi-index subscript",
     (("is a subscript whose index is a tuple",),)),
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
     # TWO wordings, because the message has been reworded once and the
     # earlier wording is what the 2026-09-30 sweep log still contains — the
     # log is an artifact, so a table that only knows the new wording silently
     # reads an old log as `other refusal`. See the module docstring.
     (("so it is a module-level name of another module",),
      ("and it is a module-level name of another module",))),

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
    # 37 files on the 2026-09-30 r2 sweep, and 36 of them are ONE stdlib host
    # module refusing on ONE comparison — the largest single construct in the
    # whole table, and it was in `other refusal` until this marker existed.
    # `other refusal` is the bucket that means "unclassified", so a construct
    # this large sitting in it is not a rounding error in a reader's
    # judgement; it is the tool declining to do the one job it exists for.
    ("`==` between two values whose kind no call site established",
     (("compares two values this path can only call numbers",),)),
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
    # (`unimplemented intrinsic` was a cause here until 2026-09-30 r2, and it
    # was DEAD twice over: its marker was the FAMILY NAME from
    # `formal_sweep.py`'s `_REFUSAL_FAMILIES` rather than anything a message
    # contains — no message anywhere in the tree says "unimplemented
    # intrinsic" — and the message it was written for is the `...`-body
    # refusal three entries above. A duplicate with a dead marker is worse
    # than no row: it reads as a cause that blocks nothing, which is
    # indistinguishable from a cause nothing is blocked by.)
    ("method call on a value receiver is not one of the lowered methods",
     (("lowers only append, close, write",),)),
    # 3 files, and below the 5-file bar a cause has to clear to be worth a
    # row — but it has a bug doc of its own
    # (`bugs/FORMAL_none_is_not_a_literal.md`), and a cause with a doc and no
    # marker is a cause nobody can find from the table.
    ("a class-level default is the NAME `None`",
     (("is a NAME rather than a literal",),)),
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
        where[label][refuser or (hops[-1] if hops else "(this file)")] += 1
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
            print(f"        example:    {r['example']}")
        shown_files = sum(r["files"] for r in shown)
        print(f"\n{shown_files} of {total} codegen/dependency lines "
              f"accounted for, in {len(shown)} cause(s) of "
              f"{len(table)}")
        print("FILES BLOCKED IS AN UPPER BOUND: a file's terminal cause is the "
              "first refusal reached,\nso fixing one usually moves it to the "
              "next. Measure a cause's real value by\nre-sweeping the files it "
              "blocks — see bugs/FORMAL_sweep_work_map_2026-09-30_r2.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
