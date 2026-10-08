#!/usr/bin/env python3
"""`L[T]()` — a TYPE APPLICATION in CALLEE position, and the call-site
exemption that makes it build.

`formal/model.py`'s `subscript_callee_names` recognises the shape — a call whose
callee is a `SubscriptExpr` rooted at a bare name — and `formal/build.py`'s
`check_module_symbols` uses it to keep the base (and every identifier in the
bracket) out of the name-placement walk. `List[Int]()` is a TYPE APPLICATION:
the bracket is the type's argument list and the base is the symbol the call
dispatches on, so neither is a read of a value and neither may be placed.
Both backends then lower the empty container through
`model.empty_blob_constructor`, which is a different question from whether a
`List` is one word.

WHAT WAS BROKEN, and it is not a shape bug — it is DEAD CODE.

    # formal/build.py, one function, twice
    callees = {id(c.func) for c in M.iter_nodes(fn.body) ...}   # binding 1
    for c in M.iter_nodes(fn.body):
        if isinstance(c, F.CallExpr):
            for node in M.subscript_callee_names(c):            # the fix
                callees.add(id(node))
    …
    callees = set()                                             # binding 2
    for c in M.iter_nodes(fn.body): …                           # one loop, no subscript

Binding 2 discarded everything binding 1 collected, including the subscript
callee. `69f20418` ("formal: L[T]() is a type application…") added binding 1's
loop and its four paired cases in `test_formal_run.py`; `7b52a5e4`, an
integration of two branches that each carried their own version of this loop,
resolved its conflict by keeping BOTH — and the second one won. So from that
merge on, `L[T]()` was refused exactly as it had been before the fix:

    $ python3 fire.py build --formal --no-prove .tmp/t2.mojo
    build: Holder___init__: 'List' has no home: the module-level symbol table
    is empty for this unit, and the reading function declares no local or
    parameter by that spelling. This path places a name in a register or a
    spill slot allocated for THIS function …

Every clause of that sentence is false about the program. `List` is a TYPE, it
is in none of the four places a value can be, and no amount of reading
`_load_var` would have found anything — it is the `bugs/FORMAL_known_limits.md`
rule that a message false about the file is worse than no message.

THE COST OF NOTICING LATE, which is why there is a structural guard at the
bottom of this file rather than only the behavioural ones. Three of
`test_formal_run.py`'s four `TYPE_APPLICATION_CASES` were RED on master. A
fix whose own regression tests were red is not a fix that got lost; it is a fix
whose tests were never run on the merged tree, so the behavioural cases above
are necessary and not sufficient — the guard is what makes the *same* clobber
impossible to merge again without a red test.

WHAT IS PINNED HERE, and not in `test_formal_run.py`'s tables: the exact shape
`std/collections/binary_heap.mojo` writes — `List[Self.T]()` inside a GENERIC
struct's `__init__`, a method the compiler compiles and no call site ever
runs. Every one of the 80 files the 2026-09-30 sweep filed under this sentence
reached it through that one line, and the reason a build-level property needs
its own case is that it is not visible from a program's OUTPUT: the exemption
is asserted by the image existing, so the case asserts the build on both
architectures AND compares the program's own output with CPython.
"""
import argparse
import ast
import inspect
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The two helpers and the timeout come from the sibling suite rather than being
# written again here: `build_formal` is `fire.py build --formal --no-prove` with
# a per-backend switch, and `run_cpython_pair_case` is the only place that knows
# how to build BOTH architectures, run both, and compare with CPython run at
# test time. A second copy of either is a second answer to the same question.
from test_formal_run import (  # noqa: E402
    build_formal,
    run_cpython_pair_case,
)

ARCHES = ("arm64", "x86_64")


# ── the shapes that must BUILD, RUN, and match CPython ──────────────────────
#
# A PAIR of programs, because `List[Self.T]()` is not valid Python
# (`typing.List[str]()` raises) and `printf` is not a Python function, so "run
# the same text through both engines" is not available for this construct. The
# expected value is whatever CPython prints for the Python text, run here at
# test time — a hand-written constant would be an assertion about a lowering
# made by the same person who wrote the lowering.
PAIR_CASES = [
    # THE shape the sweep named, 80 times over: a generic struct whose
    # `__init__` builds `List[Self.T]()`. `Holder` is never instantiated — that
    # is the point, because a specialization `Holder[Int]()` is a DIFFERENT
    # construct with its own refusal — and the build still has to compile the
    # method, so the walk has to place `List` and `Self` or refuse the file.
    # `main` builds and reads a `List[String]()` of its own so the empty-blob
    # lowering is exercised by something that RUNS, and CPython says its
    # length is 0.
    ("a_type_application_in_a_generic_struct_init",
     "struct Holder[T: Copyable]:\n"
     "    var _data: List[Self.T]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._data = List[Self.T]()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var xs = List[String]()\n"
     "    printf(\"len=%d\", len(xs))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    xs = []\n"
     "    sys.stdout.write(\"len=%d\" % len(xs))\n"),
    # Two element types, two generics, one image — a walk that answered the
    # bracket by its SPELLING rather than by its position would pass the case
    # above (whose bracket is `Self.T`) and fail this one (`Int`), so the pair
    # is what makes "the bracket is a type's argument list, not an index" a
    # claim about both. Both lengths are 0 and the join is what is compared.
    ("two_element_types_in_two_type_applications",
     "struct Bag[T: Copyable]:\n"
     "    var xs: List[Self.T]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self.xs = List[Self.T]()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = List[Int]()\n"
     "    var b = List[String]()\n"
     "    printf(\"%d %d\", len(a), len(b))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a, b = [], []\n"
     "    sys.stdout.write(\"%d %d\" % (len(a), len(b)))\n"),
]


# ── the boundaries: the exemption must not reach past CALLEE position ───────
#
# `subscript_callee_names` returns NODES rather than names precisely so that a
# call-site exemption cannot leak into a genuine read of the same spelling.
# Exempting by name would build the first of these and print an address, and
# `iter_nodes` has no parent, so node identity is the only thing that can hold
# the line.
BOUNDARY_REFUSALS = [
    # The SAME function, the SAME name, one spelling in callee position and one
    # in value position. The walk reaches them in source order, so the callee
    # comes first and must be answered without making the read answerable: this
    # is the case that fails if the exemption is ever keyed on a string.
    ("the_same_name_in_a_value_position_still_refuses",
     "def main(n: Int) -> Int:\n"
     "    var xs = List[Int]()\n"
     "    var k = len(List)\n"
     "    printf(\"k=%d\", k)\n"
     "    return 0\n",
     "len(List)"),
    # The documented give-up, kept as a test rather than as a comment:
    # `subscript_callee_names` only recognises a base that is a bare
    # IdentExpr, so `xs[0](5)` — a genuine value, subscripted, then called — is
    # not a type application and is refused by the specialization refusal, which
    # names the brackets rather than the allocator. If a future change widens the
    # recogniser to every subscripted callee, this is the row that says it went
    # too far.
    ("a_subscripted_value_called_is_not_a_type_application",
     "def main(n: Int) -> Int:\n"
     "    var xs = [1, 2, 3]\n"
     "    var y = xs[0](5)\n"
     "    printf(\"y=%d\", y)\n"
     "    return 0\n",
     "calls a name this unit does not compile"),
    # …and the type's own ARGUMENT is compile-time by construction, so it is
    # exempt as part of the bracket rather than as a value. `Self.T` inside
    # `List[Self.T]()` is a MemberExpr, not an IdentExpr, and `Subscript` names
    # it differently: this case is the one that would fail if only the base were
    # collected.
    ("a_type_arguments_that_are_member_expressions_are_not_reads",
     "def main(n: Int) -> Int:\n"
     "    var xs = List[String]()\n"
     "    var d = Dict[String, List[Int]]()\n"
     "    printf(\"%d %d\", len(xs), len(d))\n"
     "    return 0\n",
     None),
]


def run_boundary_case(name, source, needle, tmpdir, verbose):
    """Both architectures must refuse (or answer) the same way.

    `needle is None` means the program is EXPECTED TO BUILD here — the third
    boundary case is a positive one that belongs in this table because it is
    the negative of the other two: `Dict[String, List[Int]]()` nests a type
    application in a type argument, and every name in it is exempt only because
    the walk does not treat a type as a value.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ARCHES:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend=backend, tmpdir=tmpdir)
        if needle is None:
            if rc != 0:
                return False, (f"--backend={backend} refused a construct it "
                               f"answers: {text.strip()[-300:]}")
            if verbose:
                print(f"      {backend}: built")
            continue
        if rc == 0:
            return False, (f"--backend={backend} BUILT {needle!r}, which is the "
                           f"silently-wrong direction this exemption exists to "
                           f"prevent")
        if needle not in text:
            return False, (f"--backend={backend} refused without naming "
                           f"{needle!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      {backend}: refused with {needle!r}")
    return True, ""


# ── the guard that makes the clobber impossible to merge again ──────────────

def the_exemption_is_not_dead_code(verbose):
    """`check_module_symbols` must bind `callees` EXACTLY ONCE.

    The behavioural cases above are what proves the construct works; this is
    what proves it keeps working, and it is not redundant with them. The defect
    this file is about was invisible to every behavioural test for two days —
    the tests existed, and were red, and the merge that caused it reported
    green — because a binding that discards a previous binding produces no
    error, no warning and no traceback. It produces a walk that quietly stops
    asking a question. So the property worth asserting is the STRUCTURE, not
    only the outcome: one binding, in one function, for one set.

    Counted with `ast` rather than by searching the text, so a mention of
    `callees` in a comment — which this file has several of — cannot pass or
    fail the guard. Only a REBINDING counts: `callees.add(…)`, `callees |= …`
    and `callees -= …` mutate the one set and are how the function adds and
    subtracts within a single pass, so counting them would make the guard fire
    on correct code. The second binding in the defect was `callees = set()`,
    which is the only spelling that discards.
    """
    import formal.build as B

    src = textwrap.dedent(inspect.getsource(B.check_module_symbols))
    tree = ast.parse(src)
    bindings = []
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else []
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name) and n.id == "callees":
                    bindings.append(node.lineno)
    if len(bindings) != 1:
        return False, (
            f"check_module_symbols binds `callees` {len(bindings)} times (lines "
            f"{bindings}); every binding after the first DISCARDS what the first "
            f"collected, which is how the `L[T]()` exemption was live code for "
            f"one commit and dead code from the next merge on — "
            f"`model.subscript_callee_names` is asked once, at line "
            f"{src.count('subscript_callee_names')} of the function, and its "
            f"answer is thrown away unless this loop is the only binder")
    # The recogniser itself must be asked, exactly once, in that one place. A
    # second copy of the shape's recogniser is a second answer to one question,
    # and the two are free to disagree about which callees are exempt.
    asked = src.count("M.subscript_callee_names(")
    if asked != 1:
        return False, (
            f"check_module_symbols asks M.subscript_callee_names {asked} times; "
            f"it is the ONE recogniser of the shape and belongs in one place")
    if verbose:
        print(f"      callees is bound once (line {bindings[0]}), "
              f"subscript_callee_names is asked once")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    passed = failed = 0

    ok, detail = the_exemption_is_not_dead_code(args.verbose)
    print(f"  {'PASS' if ok else 'FAIL'}  the_exemption_is_not_dead_code"
          + (f": {detail}" if not ok else ""))
    if ok:
        passed += 1
    else:
        failed += 1

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, cpython_source in PAIR_CASES:
            src = os.path.join(tmpdir, name + ".mojo")
            with open(src, "w") as f:
                f.write(source)
            ok, detail = run_cpython_pair_case(name, source, cpython_source,
                                               tmpdir, args.verbose)
            print(f"  {'PASS' if ok else 'FAIL'}  {name}"
                  + (f": {detail}" if not ok else " (== CPython, both architectures)"))
            if ok:
                passed += 1
            else:
                failed += 1

        for name, source, needle in BOUNDARY_REFUSALS:
            ok, detail = run_boundary_case(name, source, needle, tmpdir,
                                           args.verbose)
            print(f"  {'PASS' if ok else 'FAIL'}  {name}"
                  + (f": {detail}" if not ok else ""))
            if ok:
                passed += 1
            else:
                failed += 1

    print(f"\nformal type application: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())