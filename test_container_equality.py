#!/usr/bin/env python3
"""Container `==` / `!=` on the compiled path is VALUE equality, per CPython.

`a == b` between two containers used to lower to a raw C POINTER comparison
(`_t3 = a == b;` on two `MojoSet *`), because that is what falls out of C. It
is False for every pair of containers that are equal but not the SAME object --
which is every `while nxt != proven:` convergence test, since each round builds
a fresh one. With no GC such a loop never terminates and leaks a set per round:
the 43 GB two-line compile in bugs/CODEGEN_container_eq_is_pointer_identity.md,
and a prime suspect in the self-hosted compiler's own footprint. `is` / `is not`
keep pointer identity, which is what they mean.

Every case here is a whole PROGRAM that is run TWICE -- once compiled to an
arm64/x86-64 Mach-O executable through the GIMPLE backend, once by CPython on
the same text with the Mojo spellings stripped -- and the two must agree on
stdout AND exit status. Diffing against CPython rather than against answers
written down here is the point: the expected values are Python's, so a
divergence is the compiler's, not the test's. `test_gimple.py` only checks that
the generated C is ACCEPTED by `gcc -fgimple -fsyntax-only`, which every wrong
answer in this file's history also passed.

The cases are grouped by the lowering decision they exercise, because the three
ways the codegen can know an operand is a container are three different paths:

  typed    both operands have a container C type        -> mojo_<kind>_eq
  erased   one operand's C type was lost to int64_t     -> mojo_value_eq
  literal  the other side is a container literal/call   -> mojo_value_eq

Run:  python3 test_container_equality.py [-v] [--keep]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RUNTIME = os.path.join(HERE, 'runtime')


def _p(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# Every program below is written ONCE and used for both engines: CPython needs
# only `-> Int` and `var ` removed, which `_py_source` does in place (replacing
# the keyword, never its leading whitespace -- a body whose only statement was
# `var a = 1` would otherwise become an empty block).
#
# Every program prints one line per assertion and returns 0, so a divergence is
# a line-by-line diff rather than a single opaque exit status.
CASES = [
    # ── typed operands: the statically-typed path, and the shape the
    #    documented 43 GB compile hit (two `MojoSet *` locals) ──────────────
    ("typed-set", _p(
        "def main() -> Int:",
        "    print({1, 2, 3} == {1, 2, 3})",
        "    print({1, 2, 3} != {1, 2, 3})",
        "    print({1, 2} == {1, 3})",
        "    print({1, 2} == {2, 1})",
        "    print(set() == set())",
        "    print(set() == {1})",
        "    return 0")),
    ("typed-list", _p(
        "def main() -> Int:",
        "    print([1, 2] == [1, 2])",
        "    print([1, 2] == [2, 1])",
        "    print([1, 2] == [1, 2, 3])",
        "    print([1, 2] != [1, 3])",
        "    print([] == [])",
        "    print([] == [0])",
        "    return 0")),
    ("typed-dict", _p(
        "def main() -> Int:",
        '    print({"x": 1} == {"x": 1})',
        '    print({"x": 1} == {"x": 2})',
        '    print({"x": 1} == {"y": 1})',
        # order-insensitive: same entries, different insertion order
        '    print({"x": 1, "y": 2} == {"y": 2, "x": 1})',
        '    print({"x": 1, "y": 2} != {"y": 1, "x": 2})',
        "    print({} == {})",
        "    return 0")),
    ("typed-tuple", _p(
        "def main() -> Int:",
        "    print((1, 2) == (1, 2))",
        "    print((1, 2) == (1, 3))",
        # a tuple is NEVER equal to a list: both are a MojoList at the C level
        # and the marker is the only thing that tells them apart
        "    print((1, 2) == [1, 2])",
        "    print([1, 2] == (1, 2))",
        "    print(() == ())",
        "    print(() == [])",
        "    return 0")),
    # ── different kinds on both sides: never equal, in either order ────────
    ("typed-mixed-kinds", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        '    d = {"x": 1}',
        "    s = {1, 2}",
        "    print(d == a)",
        "    print(a == d)",
        "    print(s == a)",
        "    print(a == s)",
        "    print(d == s)",
        "    print(s == d)",
        # ...and against a non-container, which is also False
        '    print([1, 2] == "12")',
        '    print("12" == [1, 2])',
        "    print([1, 2] == 1)",
        "    print(None == [1, 2])",
        "    return 0")),

    # ── element semantics: the element CODE the codegen knows, per side ─────
    ("elem-str", _p(
        "def main() -> Int:",
        '    print(["a", "b"] == ["a", "b"])',
        '    print(["a", "b"] == ["a", "c"])',
        '    print(["a", "b"] == ["b", "a"])',
        '    print({"a", "b"} == {"b", "a"})',
        '    print({"a", "b"} != {"b", "c"})',
        "    return 0")),
    ("elem-int-float", _p(
        "def main() -> Int:",
        "    print([1.0] == [1])",
        "    print([1, 2] == [1.0, 2.0])",
        "    print([1.0, 2.0] == [1, 2])",
        "    print([1.0] == [2])",
        # a heterogeneous literal records PER-SLOT kinds, which are what the
        # comparison reads; the list-wide element ctype is lossy here
        "    print([1, 2.0] == [1.0, 2])",
        "    print([1, 2.0] == [2.0, 1])",
        "    print({1.0, 2.0} == {1.0, 2.0})",
        "    print({1.0, 2.0} == {1, 2})",
        '    print({"a": 1.0} == {"a": 1})',
        '    print({"a": 1} == {"a": 1.5})',
        "    return 0")),
    ("elem-mixed-str-int", _p(
        "def main() -> Int:",
        '    print([1, "a"] == [1, "a"])',
        '    print([1, "a"] == [2, "a"])',
        '    print([1, "a"] == [1, "b"])',
        '    print([1, "a"] != [1, "b"])',
        '    print(["a", 1] == [1, "a"])',
        "    return 0")),
    ("elem-nested", _p(
        "def main() -> Int:",
        "    print([[1], [2]] == [[1], [2]])",
        "    print([[1], [2]] == [[1], [3]])",
        '    print([{"a": 1}] == [{"a": 1}])',
        '    print([{"a": 1}] == [{"a": 2}])',
        '    print({"k": [1, 2]} == {"k": [1, 2]})',
        '    print({"k": [1, 2]} == {"k": [1, 3]})',
        "    print([[1, 2], [3]] == [[1, 2], [3]])",
        "    print([[[1]]] == [[[1]]])",
        "    print([[1]] == [[1, 1]])",
        "    return 0")),
    ("elem-built", _p(
        "def main() -> Int:",
        "    a = list()",
        "    b = list()",
        "    a.append(1)",
        "    b.append(1)",
        "    print(a == b)",
        "    b.append(2)",
        "    print(a == b)",
        "    print(set([1]) == set([1]))",
        '    print(dict({"a": 1}) == {"a": 1})',
        "    c = a[:]",
        "    print(a == c)",
        "    return 0")),

    # ── erased operands: a container handed to an unannotated parameter ─────
    # `_container_param_kinds`, from the call sites' literal arguments. Each
    # helper sees ONE container kind, because the evidence is required to be
    # unanimous -- a helper called with both a list and a set learns nothing.
    ("erased-set", _p(
        "def same(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(same({1, 2}, {1, 2}))",
        "    print(same({1, 2}, {1, 3}))",
        '    print(same({"x", "y"}, {"y", "x"}))',
        '    print(same({"x", "y"}, {"x", "z"}))',
        "    return 0")),
    ("erased-list-ints", _p(
        "def same(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(same([1, 2], [1, 2]))",
        "    print(same([1, 2], [1, 3]))",
        "    print(same([1, 2], [2, 1]))",
        "    return 0")),
    ("erased-list-strs", _p(
        "def same(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    print(same(["a", "b"], ["a", "b"]))',
        '    print(same(["a", "b"], ["a", "c"]))',
        "    return 0")),
    ("erased-dict", _p(
        "def same(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    print(same({"x": 1}, {"x": 1}))',
        '    print(same({"x": 1}, {"x": 2}))',
        '    print(same({"x": 1, "y": 2}, {"y": 2, "x": 1}))',
        "    return 0")),
    ("erased-tuple", _p(
        "def same(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(same((1, 2), (1, 2)))",
        "    print(same((1, 2), (1, 3)))",
        '    print(same((1, "x"), (1, "x")))',
        "    return 0")),
    # one erased, one a literal: the literal's element type has to reach the
    # runtime or a list of strings compares by ADDRESS. Two helpers, because
    # the call-site evidence must be UNANIMOUS about the element type too --
    # a helper called with both an int list and a str list is told nothing.
    ("erased-vs-literal", _p(
        "def same_as_list(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def same_as_strlist(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(same_as_list([1, 2], [1, 2]))",
        "    print(same_as_list([1, 2], [2, 1]))",
        '    print(same_as_strlist(["a"], ["a"]))',
        '    print(same_as_strlist(["a"], ["b"]))',
        "    return 0")),
    ("erased-vs-set-literal", _p(
        "def same_as_set(a, b) -> Int:",
        "    if a == b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(same_as_set({1}, {1}))",
        "    print(same_as_set({1}, {2}))",
        "    return 0")),

    # ── the bug itself: a convergence loop that never terminated ────────────
    # Each of these loops alternates between two DIFFERENT equal-typed values,
    # so the pointer comparison said "different" every round forever.
    ("fixed-point-dict", _p(
        "def main() -> Int:",
        "    n = 0",
        '    proven = {"a": 1, "b": 2}',
        '    nxt = {"a": 1, "b": 3}',
        "    while nxt != proven:",
        "        n = n + 1",
        "        proven = nxt",
        '        nxt = {"a": 1, "b": 2}',
        "    print(n)",
        "    return 0")),
    ("fixed-point-list", _p(
        "def main() -> Int:",
        "    n = 0",
        "    la = [1, 2, 3]",
        "    lb = [1, 2, 4]",
        "    while lb != la:",
        "        n = n + 1",
        "        la = lb",
        "        lb = [1, 2, 3]",
        "    print(n)",
        "    return 0")),
    ("fixed-point-set", _p(
        "def main() -> Int:",
        "    n = 0",
        "    sa = {1, 2}",
        "    sb = {1, 3}",
        "    while sb != sa:",
        "        n = n + 1",
        "        sa = sb",
        "        sb = {1, 2}",
        "    print(n)",
        "    return 0")),
    # ...and with the containers behind erased parameters, which is the shape
    # the 43 GB compile had (`{} == {}` where both are int64_t handles). The
    # `> 5` guard is what turns "still not terminating" into a wrong ANSWER
    # instead of a hang, so a regression fails the test rather than the run.
    ("fixed-point-erased", _p(
        "def converge(nxt, proven) -> Int:",
        "    steps = 0",
        "    while nxt != proven:",
        "        steps = steps + 1",
        "        if steps > 5:",
        "            return 99",
        "        proven = nxt",
        "        nxt = {1, 2}",
        "    return steps",
        "",
        "def main() -> Int:",
        "    print(converge({1, 2}, {9, 9}))",
        "    print(converge({1, 2}, {1, 2}))",
        "    return 0")),

    # ── what must NOT change ───────────────────────────────────────────────
    # `is` / `is not` are pointer identity in Python and must stay that way;
    # routing them through the value predicates would make `a is b` True for
    # two separately-built lists.
    ("is-is-identity", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    b = [1, 2]",
        "    c = a",
        "    print(a is b)",
        "    print(a is c)",
        "    s1 = {1}",
        "    s2 = {1}",
        "    print(s1 is s2)",
        "    d = {}",
        "    print(d is not {})",
        "    return 0")),
    # Scalars, strings and None keep whatever they answered before: a wrong
    # answer here would be a much wider blast radius than the one being fixed.
    ("scalar-unchanged", _p(
        "def main() -> Int:",
        "    n = 3",
        "    m = 3",
        "    f = 1.5",
        "    g = 1.5",
        '    s = "ab"',
        '    t = "ab"',
        "    print(n == m)",
        "    print(n != m)",
        "    print(f == g)",
        '    print(s == t)',
        "    print(n == 3)",
        '    print(s == "ab")',
        '    print(s != "ac")',
        "    print(None == None)",
        "    print(None == [1])",
        "    return 0")),
    # A chained comparison goes through the same per-link lowering, so
    # `a == b == [1]` must not read as "compare the first two only".
    ("chained", _p(
        "def main() -> Int:",
        "    a = [1]",
        "    b = [1]",
        "    print(a == b == [1])",
        "    print(a == b == [2])",
        "    print(a == b != [2])",
        "    print(a == b != [1])",
        "    return 0")),
]

# ── ORDERING ───────────────────────────────────────────────────────────────
#
# Separate from the `==`/`!=` group above, and run through the same harness,
# because these four operators are a DIFFERENT question with a different set of
# rules and used to have a different wrong answer: `<` / `>` / `<=` / `>=`
# between containers lowered to the raw C comparison of two pointers, so the
# answer was decided by where malloc put the two allocations. That was silent
# (exit 0, no diagnostic) and wrong for four of the five cases in
# bugs/CODEGEN_container_ordering_is_pointer_identity.md.
#
# The rules being pinned are NOT one rule:
#   * LIST (and tuple) is lexicographic with a SHORTER PREFIX ORDERING FIRST —
#     `[1] < [1, 2]`, `[1, 2] > [1]` — and recurses through a nested container.
#   * SET is the PROPER-SUBSET relation, in BOTH directions for `>`, which is
#     not the list rule and not a difference-emptiness test: `{1, 2}` vs
#     `{1, 3}` is neither `<` nor `>`, and the pointer comparison got
#     `s1 > s2` backwards for exactly that pair.
#   * DICT has no ordering on CPython either, so every dict case here is a
#     TypeError and the test passes only if the compiled program raises one too
#     (same stdout, same exit status as CPython).
#
# Every operator appears in every list and set case. A case that used only `<`
# would pass with `<=` and `>=` inverted, since `<=` and `>=` are `==` OR the
# strict form rather than the strict form alone — the shape
# bugs/CODEGEN_container_ordering_is_pointer_identity.md §"Exact next step"
# called out, and the reason this group exists rather than four more `==` rows.
ORDER_CASES = [
    ("order-list-lexicographic", _p(
        "def main() -> Int:",
        # all four operators, each against a list that differs from the other
        # at one position and by length
        "    print([1, 2] < [1, 3], [1, 2] > [1, 3], [1, 2] <= [1, 2], [1, 2] >= [1, 3])",
        # a SHORTER PREFIX orders FIRST: the rule lists use and sets do not
        "    print([1] < [1, 2], [1, 2] > [1])",
        "    print([] < [], [] <= [], [] < [1], [] > [1])",
        "    print([1, 2] < [1, 2, 3], [1, 2, 3] > [1, 2])",
        # neither a prefix nor equal: decided on the first differing element
        "    print([2] < [1, 3], [1, 3] > [2])",
        "    return 0")),
    ("order-list-elements", _p(
        "def main() -> Int:",
        # int vs float promotes rather than reinterpreting: `[1.0] < [1]` is
        # False (they are equal) and `[1.0] < [2]` is True
        "    print([1.0] < [1], [1.0] < [2], [1] < [1.0], [2] <= [1.0])",
        # str elements order lexicographically, not by address
        '    print(["a"] < ["b"], ["b"] < ["a"], ["a"] < ["ab"])',
        # a nested container element recurses through the same three-way
        "    print([[1]] < [[2]], [[2]] > [[1]])",
        "    print([(1, 2)] < [(1, 3)], [(1, 3)] > [(1, 2)])",
        "    print([[[1]]] <= [[[1]]])",
        "    return 0")),
    ("order-list-tuple-is-refused", _p(
        # CPython 3.14: tuple and list are both MojoList at the C level, and
        # the tuple marker is the only thing that tells them apart — which is
        # what has to answer here, because the two order the same way and must
        # NOT be interchangeable
        "def main() -> Int:",
        "    print([(1,)] < [(2,)])",
        "    print([1] < [(1,)])",
        "    return 0")),
    ("order-set-proper-subset", _p(
        "def main() -> Int:",
        # a PROPER subset orders first, in both directions
        "    print({1} < {1, 2}, {1, 2} > {1})",
        "    print({1, 2} < {1, 2, 3}, {1, 2, 3} > {1, 2})",
        # equal sets: neither strict, both non-strict
        "    print({1, 2} < {1, 2}, {1, 2} > {1, 2})",
        "    print({1, 2} <= {1, 2}, {1, 2} >= {1, 2}, {1} <= {1, 2})",
        # SAME SIZE, different contents: not a subset either way. This is the
        # pair the pointer comparison answered `s1 > s2` True for.
        "    print({1, 2} < {1, 3}, {1, 2} > {1, 3})",
        "    print({1, 2} <= {1, 3}, {1, 2} >= {1, 3})",
        # order-independent, and str elements order by content
        '    print({"a", "b"} < {"a", "b", "c"}, {"a"} > {"a", "c"})',
        '    print({"a"} <= {"a", "b"}, {"b"} > {"a", "b"})',
        "    return 0")),
    ("order-set-float-elements", _p(
        # a set of floats stores IEEE bits in an int slot, and Python says
        # `{1.0} <= {1}` — the same cross-domain promotion mojo_set_eq does
        "def main() -> Int:",
        "    print({1.0} < {1}, {1.0} <= {1}, {1} < {1.0}, {1} <= {1.0})",
        "    print({1.0} > {1}, {1.0} >= {1}, {1} >= {1.0})",
        "    return 0")),
    # Every dict case is a TypeError, on CPython and here. The harness compares
    # stdout AND exit status, so a case that COMPILED and printed a wrong
    # comparison instead of raising fails it exactly as it should — which is
    # the property that made the doc's "a dict is the one container kind with
    # no correct answer to give" implementable rather than a note.
    ("order-dict-is-refused", _p(
        "def main() -> Int:",
        '    print({"a": 1} < {"b": 2})',
        "    return 0")),
    ("order-dict-vs-list-is-refused", _p(
        "def main() -> Int:",
        '    print([1] < {"a": 1})',
        "    return 0")),
    ("order-none-element-is-refused", _p(
        # None is in no order with anything, itself included
        "def main() -> Int:",
        "    print([1] < [None])",
        "    return 0")),
    ("order-list-vs-str-is-refused", _p(
        "def main() -> Int:",
        '    print([1] < "a")',
        "    return 0")),
    # ── erased operands ────────────────────────────────────────────────────
    # The erased route (`mojo_value_order_op`) is a DIFFERENT entry point with
    # its own kind discovery, so the typed cases above say nothing about it. A
    # helper per family, for the same reason the `==` cases use one: the
    # call-site evidence must be UNANIMOUS about the container kind.
    ("order-erased-list", _p(
        "def lt(a, b) -> Int:",
        "    if a < b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(lt([1, 2], [1, 3]), lt([1, 3], [1, 2]), lt([1, 2], [1]))",
        "    return 0")),
    ("order-erased-set", _p(
        "def gt(a, b) -> Int:",
        "    if a > b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(gt({1, 2, 3}, {1, 2}), gt({1, 2}, {1, 3}))",
        "    return 0")),
    ("order-erased-nonstrict", _p(
        "def le(a, b) -> Int:",
        "    if a <= b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        # `<=` is `==` OR the strict form: an equal-but-separately-built pair
        # is the case a pointer comparison got wrong
        "    print(le([1, 2], [1, 2]), le({1, 2}, {1, 2}), le({1}, {1, 2}))",
        "    return 0")),
    ("order-erased-vs-literal", _p(
        "def lt_list(a, b) -> Int:",
        "    if a < b:",
        "        return 1",
        "    return 0",
        "",
        "def le_set(a, b) -> Int:",
        "    if a <= b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        # one operand erased, the other a literal: the erased side has no
        # static element type at all, which is a third discovery question
        "    print(lt_list([1, 2], [1, 3]), lt_list([1, 3], [1, 2]))",
        '    print(le_set({"a"}, {"a", "b"}), le_set({"a"}, {"b"}))',
        "    return 0")),
    # ── what must NOT change ──────────────────────────────────────────────
    # `is` / `is not` are pointer identity and stay that way. A change that
    # routed them through the ordering predicates would make `a is b` True for
    # two separately-built containers, which is the same bug in the other
    # direction.
    ("order-is-is-still-identity", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    b = [1, 2]",
        "    c = a",
        "    print(a is b, a is c, a < b, a > b)",
        "    s1 = {1}",
        "    s2 = {1}",
        "    print(s1 is s2, s1 < s2, s1 > s2)",
        "    return 0")),
    # Scalar and string comparison is untouched: a wrong answer there would be
    # a much wider blast radius than the one being fixed.
    ("order-scalars-unchanged", _p(
        "def main() -> Int:",
        "    print(1 < 2, 2 < 1, 1 <= 1, 1 >= 2, 2 > 1)",
        "    print(1.5 < 2, 2.0 <= 1.5, 1.0 < 1.5)",
        '    print("a" < "b", "b" < "a", "a" <= "a", "ab" < "b")',
        "    return 0")),
]


def _py_source(src: str) -> str:
    """The same program as CPython sees it: drop the Mojo annotations."""
    out = []
    for line in src.splitlines():
        line = re.sub(r"\bvar\s+", "", line)
        line = re.sub(r"->\s*Int(?!\w)", "", line)
        out.append(line)
    return "\n".join(out) + "\n\nmain()\n"


def run_cpython(src: str, tmp: str):
    path = os.path.join(tmp, "ref.py")
    with open(path, "w") as f:
        f.write(_py_source(src))
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=60)
    return p.stdout, p.returncode, p.stderr


def run_compiled(src: str, tmp: str, name: str):
    """(stdout, exitcode) of the compiled program, or raises RuntimeError."""
    from build_config import find_gcc
    from gimple_codegen import compile_to_gimple

    c = compile_to_gimple(src)
    c_file = os.path.join(tmp, name + ".c")
    exe = os.path.join(tmp, name)
    with open(c_file, "w") as f:
        f.write(c)
    sources = [c_file, os.path.join(RUNTIME, "fire_runtime.c")]
    if "__mgco_" in c or "__mojo_coro_yield_i" in c:
        import platform
        arch = ("fire_coro_ctx_aarch64.S"
                if platform.machine().lower() in ("arm64", "aarch64")
                else "fire_coro_ctx_generic.c")
        sources += [os.path.join(RUNTIME, x) for x in
                    ("fire_coro_gen.c", "fire_coro.c", "fire_async_sched.c",
                     arch)]
    r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe,
                        *sources], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("generated C rejected by gcc -fgimple:\n"
                           + r.stderr[-3000:])
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.stdout, p.returncode, p.stderr


def _is_type_error_refusal(rc: int, err: str) -> bool:
    """Is CPython's verdict for this program "raises TypeError"?

    Only TypeError counts, and only on the LAST line: a case whose reference
    program fails for any other reason (a NameError from a typo in the case, a
    SyntaxError from the `var`-stripping) is a broken TEST, and admitting it as
    a refusal would let a case whose reference never ran pass by having the
    compiled side also fail to run. A dict compared with `<` is the only thing
    in ORDER_CASES that CPython refuses, so this is a narrow test on purpose.
    """
    if rc == 0 or not err.strip():
        return False
    return err.strip().splitlines()[-1].startswith("TypeError:")


def _diff(want: str, got: str) -> str:
    wl, gl = want.splitlines(), got.splitlines()
    lines = []
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<missing>"
        g = gl[i] if i < len(gl) else "<missing>"
        if w != g:
            lines.append("      line %d: cpython %s, compiled %s"
                         % (i + 1, w, g))
    return "\n".join(lines[:12])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every case, not just failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated C and binaries")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="eqtest-", dir=HERE)
    passed = failed = 0
    try:
        for name, src in CASES + ORDER_CASES:
            py_out, py_rc, py_err = run_cpython(src, tmp)
            want_refusal = _is_type_error_refusal(py_rc, py_err)
            if want_refusal:
                # A REFUSAL case, and the verdict is still CPython's: the
                # compiled program must fail the same way. Its stderr is
                # "Unhandled exception: " plus the same message, so the
                # comparison is on the message line and the exit status, not
                # on a byte-for-byte stderr match that no runtime would make.
                # A compiled program that PRINTS a comparison instead is a
                # wrong answer, not a differently-worded refusal, and fails
                # here — which is the whole point of the dict cases.
                try:
                    c_out, c_rc, c_err = run_compiled(src, tmp, name)
                except Exception as e:                       # noqa: BLE001
                    status, note = "FAIL", str(e)
                    failed += 1
                else:
                    want_msg = py_err.strip().splitlines()[-1]
                    got_msg = (c_err.strip().splitlines() or [""])[-1]
                    if c_rc == py_rc and c_out == py_out \
                            and got_msg.endswith(want_msg):
                        status = "PASS"
                        note = "both refuse: %s" % want_msg
                        passed += 1
                    else:
                        status = "FAIL"
                        note = "compiled did not refuse the way CPython does\n" \
                            "      cpython: rc=%d out=%r msg=%r" % (
                                py_rc, py_out, want_msg) \
                            + "\n      compiled: rc=%d out=%r msg=%r" % (
                                c_rc, c_out, got_msg)
                        failed += 1
            elif py_rc != 0 or py_err.strip():
                # A reference program that cannot run makes the case
                # meaningless; say so instead of reporting a phantom failure.
                status = "BROKEN"
                note = "the reference program does not run under CPython:\n" \
                    + py_err[-1500:]
                failed += 1
            else:
                try:
                    c_out, c_rc, _c_err = run_compiled(src, tmp, name)
                except Exception as e:                       # noqa: BLE001
                    status, note = "FAIL", str(e)
                    failed += 1
                else:
                    if (c_out, c_rc) == (py_out, py_rc):
                        status, note = "PASS", "%d line(s)" % len(
                            py_out.splitlines())
                        passed += 1
                    else:
                        status = "FAIL"
                        note = "compiled answer differs from CPython's"
                        if c_rc != py_rc:
                            note += " (exit %d vs %d)" % (c_rc, py_rc)
                        note += "\n" + _diff(py_out, c_out)
                        failed += 1
            if status != "PASS" or args.verbose:
                print("%-6s %-28s %s" % (status, name, note))
        if args.keep:
            print("kept: %s" % tmp)
            tmp = None
    finally:
        if tmp is not None:
            for f in os.listdir(tmp):
                os.unlink(os.path.join(tmp, f))
            os.rmdir(tmp)

    print("PASS=%d FAIL=%d of %d" % (passed, failed,
                                     len(CASES) + len(ORDER_CASES)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())