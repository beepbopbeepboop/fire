#!/usr/bin/env python3
"""The formal value model's shapes, measured against CPython rather than pinned.

Two families, both of which were wrong on at least one of the two architectures
and neither of which any existing suite could see:

  * `a == b` did not reach the struct's OWN `__eq__`.  On two struct receivers it
    was one flag-setting compare of two WORDS, and for a multi-field struct a
    word is the ADDRESS of a frame of 8-byte slots — so the operator answered
    "are these the same object", which is CPython's INHERITED `__eq__` and is
    correct for a struct that declares none, and a silent bypass of the one it
    does.  The method was found, called and ignored: a class whose `__eq__`
    returned unconditionally True gave `eq=0 direct=1` against CPython's
    `eq=1 direct=1`, so a program took the wrong branch and said nothing about
    it, on both architectures.
  * `h.a, h.b = x, y` was refused on x86-64 while arm64 lowered it, which is the
    one thing two architectures of one language implementation are not allowed to
    do about a legitimate program.  See `TUPLE_STORE_CASES`.

    python3 test_formal_value_model.py [-v] [case ...]

**Why this file exists separately from `test_formal_run.py`**, which also builds
and runs and also covers these programs with fixed expected values: this one
holds no expectations of its own.  It derives the CPython program from the SAME
text, runs it, and requires the image's stdout and exit status to be identical —
so a case cannot be pinned to a value that was wrong in the first place, which is
exactly the failure mode of the bugs it guards (a hardcoded `1` where the source
says `1` and the image says `0` reads as a regression in the image, not as the
pre-existing wrong answer it is).  The split is the one `test_runtime_diff.py`
and `test_interp_oracle.py` already make: fixed expectations in the suite that
gates every commit, an oracle in a file that is run when the construct changes.

The `printf` shim is the one line that makes the two texts runnable by both
engines, and it is deliberately `sys.stdout.write(fmt % a)` rather than
`print`: this backend's string literals do not process `\\n` (measured — a
`printf("A[%d]\\n", 7)` image writes a literal backslash and an `n`, 12 bytes,
no newline), so a format string carrying an escape would make the two engines
disagree about bytes that have nothing to do with the construct under test.
Every case here prints one line with no escape in it, and the two outputs are
compared byte for byte, exit status included.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# The CPython translation of a case: a `printf` shim, the same text with the
# `var` declaration keyword dropped (fire_compiler parses both spellings and
# CPython only one), and the call that starts `main`.
_SHIM = ("import sys\n"
         "def printf(fmt, *a):\n"
         "    sys.stdout.write(fmt % a)\n")
_VAR = re.compile(r"^(\s*)var (\w)", re.M)


def cpython_source(source: str) -> str:
    return _SHIM + _VAR.sub(r"\1\2", source) + "\nsys.exit(main(1))\n"


# (name, source, expected stdout)
#
# `expected` is what CPython prints, and it is asserted against CPython as well
# as against both images: a case whose expectation does not match CPython is a
# case whose expectation is wrong, and saying so is more useful than reporting
# the image.
#
# ── the comparison dunders ──
CASES = [
    # A dict subscript's kind is THE KIND OF THE PAIR UNDER THAT KEY, and this
    # is where a refusal became an answer. It used to be
    # `a_dict_whose_values_disagree_is_refused` and the source is this one:
    # `{"a": 10, "b": "text"}` states two kinds for the TABLE, and the old rule
    # wanted them unanimous, so every subscript of it was unclassified.
    #
    # A subscript is a key scan and its answer is ONE element word, so
    # unanimity is required over the pairs carrying that key and not over the
    # whole table — and the source says exactly which word each key holds. So
    # the program is answerable, CPython agrees, and the case is an ORACLE row
    # (`expected` is what CPython prints for the same text) rather than a
    # refusal: the old refusal was true about the old rule and false about the
    # program. The two shapes the gate still refuses are in `REFUSALS`, and one
    # of them is the same dict with one key spelled twice.
    ("a_dict_subscript_is_the_kind_of_the_pair_under_that_key",
     "def main(n):\n"
     "    var d = {\"a\": 10, \"b\": \"text\", \"c\": [1, 2, 3]}\n"
     "    print(\"v:\", d[\"a\"], \"w:\", d[\"b\"], \"n:\", len(d[\"c\"]))\n"
     "    return 0\n",
     "v: 10 w: text n: 3\n"),
    # THE REPRODUCER.  A class whose `__eq__` ignores its argument, compared
    # through the operator and through the explicit spelling, in one printf: the
    # two numbers are the same question asked twice and CPython makes them equal.
    ("operator_reaches_a_declared_eq",
     "class Plain:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def eq(a, b):\n"
     "    if a == b:\n"
     "        return 1\n"
     "    return 0\n"
     "\n"
     "def main(n):\n"
     "    var a = Plain(1, 2)\n"
     "    var b = Plain(3, 4)\n"
     "    printf(\"eq=%d direct=%d\", eq(a, b), 1 if a.__eq__(b) else 0)\n"
     "    return 0\n",
     "eq=1 direct=1"),
    # `!=` is the SECOND spelling of one question, and the language reaches it
    # through `__ne__` when there is one and through the negation of `__eq__`
    # when there is not.  Both halves, because "reached through `__eq__`" and
    # "reached through `__ne__`" are different callables and a rewrite that
    # spelled the callee from the operator would call the wrong one for `HasNe`.
    ("ne_prefers_a_declared_ne_and_negates_a_declared_eq",
     "class Yes:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "class HasNe:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "    def __ne__(self, other):\n"
     "        return False\n"
     "\n"
     "def main(n):\n"
     "    var a = Yes(1, 2)\n"
     "    var b = Yes(3, 4)\n"
     "    var c = HasNe(1, 2)\n"
     "    var d = HasNe(3, 4)\n"
     "    printf(\"eq=%d ne=%d hne=%d same=%d\",\n"
     "           1 if a == b else 0, 1 if a != b else 0,\n"
     "           1 if c != d else 0, 1 if a == a else 0)\n"
     "    return 0\n",
     "eq=1 ne=0 hne=0 same=1"),
    # THE GUARD, and it is the direction the fix must NOT move: a struct that
    # declares no `__eq__` keeps CPython's INHERITED identity comparison, which
    # on this path is the address compare that was always there.  `a == a` is
    # True, `a == b` is False for two live objects (their frames are at
    # different addresses), and `a == c` is False for two objects that hold the
    # same field values — which is what Python says too, and what a
    # field-wise `__eq__` would get wrong.  A rewrite that fired on every
    # comparison rather than on a declared dunder would break all three.
    ("no_declared_eq_stays_an_identity_compare",
     "class Bare:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "def main(n):\n"
     "    var a = Bare(1, 2)\n"
     "    var b = Bare(3, 4)\n"
     "    var c = Bare(1, 2)\n"
     "    printf(\"same=%d diff=%d cross=%d\",\n"
     "           1 if a == a else 0, 1 if a == b else 0, 1 if a == c else 0)\n"
     "    return 0\n",
     "same=1 diff=0 cross=0"),
    # A CHAIN is one `CompareChain` in the AST and `a AND b AND c` in the
    # language, so it lowers as the `and` of its pairwise comparisons and
    # short-circuits on the first false one.  It also needs the SECOND
    # parameter of the dunder to be a frame the method can read a field
    # through: `self.x == other.x` is the reason an equality method exists, and
    # it was refused by name ("`other.x` is a field access through `other`")
    # until the rewritten call's argument was followed into the callee's
    # parameter list by the holder fixpoint.
    ("chain_of_two_comparisons",
     "class Tri:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return self.x == other.x\n"
     "\n"
     "def main(n):\n"
     "    var a = Tri(1, 2, 3)\n"
     "    var b = Tri(1, 5, 6)\n"
     "    var c = Tri(9, 5, 6)\n"
     "    printf(\"chain=%d same=%d\", 1 if a == b == c else 0, 1 if a == a else 0)\n"
     "    return 0\n",
     "chain=0 same=1"),
    # The `__eq__` RESULT is a value, and it has to survive being stored,
    # returned and tested — the three positions a rewritten call can land in.
    # A rewrite that produced a boolean only in a condition would pass every
    # case above and fail this one.
    ("the_result_is_an_ordinary_value",
     "class Flag:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return self.x < other.x\n"
     "\n"
     "def is_less(a, b):\n"
     "    return 1 if a == b else 0\n"
     "\n"
     "def main(n):\n"
     "    var a = Flag(1, 2)\n"
     "    var b = Flag(9, 9)\n"
     "    var r = is_less(a, b)\n"
     "    printf(\"r=%d back=%d\", r, 1 if is_less(b, a) else 0)\n"
     "    return 7\n",
     "r=1 back=0"),
    # ── what a SUBSCRIPT yields ──
    #
    # A container's ELEMENT kind is a fact the literal states and the use site
    # was not asking.  `print()` is where it is first demanded, because `print`
    # is the one builtin that must decide between two renderings before it emits
    # anything, and refusing it was the visible half of a gap that also made
    # `printf`'s classification and every other pre-emit decision unanswerable
    # for the same expression.
    #
    # A DICT is the case that was missing, and the reason is visible in the kind
    # table rather than in the emitter: a list literal classified as
    # `list:<elem>` and a dict literal as a bare `list`, so `list_elem_kind` had
    # nothing to hand a subscript of one and every use site had to refuse.
    # Measured before the fix, on both architectures, for all three of these:
    #
    #     build: print() cannot tell whether SubscriptExpr is a string or a
    #     number on the formal arm64 path
    ("a_local_dict_element_prints",
     "def main(n):\n"
     "    var d = {\"a\": 10, \"b\": 20}\n"
     "    print(\"v:\", d[\"a\"])\n"
     "    return 0\n",
     "v: 10\n"),
    # The SAME literal at MODULE level, which is a different reader of it: the
    # kind comes from the `__DATA` slot's initializer rather than from the
    # function's flow.  One spelling working and the other refusing would make
    # the answer depend on where a name was spelled, which is the one thing a
    # value model exists to prevent.
    ("a_module_global_dict_element_prints",
     "D = {\"a\": 10, \"b\": 20}\n"
     "\n"
     "def main(n):\n"
     "    print(\"v:\", D[\"a\"])\n"
     "    return 0\n",
     "v: 10\n"),
    # And the STRING row, because the two kinds are what `print` is choosing
    # between and a fix that only answered the integer one would have narrowed
    # a refusal rather than removed it.  The element is a `char *` to interned
    # bytes (`GlobalDataImage.string_cells`), so the `%s` conversion is the
    # whole of what the word is.
    ("a_module_global_list_of_strings_element_prints",
     "L = [\"x\", \"y\"]\n"
     "\n"
     "def main(n):\n"
     "    print(\"v:\", L[0])\n"
     "    return 0\n",
     "v: x\n"),
    # ── what a CONSTRUCTION puts in a field ──
    #
    # The same shape of question as the two above, one level down: a field's
    # kind, where the DECLARATION is usually silent.  `class_jit.mojo` is this
    # case exactly — a two-field class whose fields are annotated nowhere, built
    # from literals, and read through `print`.
    #
    # The evidence is the construction, because that is where the VALUE is: the
    # store `init_body_stores` is going to perform is what the kind is read off,
    # so the two cannot disagree.  `struct_field_kind`'s own gate — a kind is a
    # claim about the VALUE in the slot, and `S()` leaves every slot at its
    # class default — is right about `S()` and irrelevant about a frame this
    # function built with arguments.  Measured before this, on both
    # architectures: refused with "print() cannot tell whether MemberExpr is a
    # string or a number".
    ("a_constructed_field_prints",
     "class Point:\n"
     "    def __init__(self, x, y):\n"
     "        self.x = x\n"
     "        self.y = y\n"
     "\n"
     "def main(n):\n"
     "    var p = Point(3, 4)\n"
     "    print(\"p:\", p.x, p.y)\n"
     "    return 0\n",
     "p: 3 4\n"),
    # AND THE STRING ROW, which is the dangerous direction and so the one that
    # has to be in the oracle's file rather than only in a suite: a kind claimed
    # for a field that holds a `char *` is what `%s` dereferences, so a wrong
    # one here is a fault or an address printed as text rather than a wrong
    # number.  Both fields in one `print` so the two conversions are in the same
    # image and the integer half cannot be quietly rendering the string one.
    ("a_constructed_string_field_prints",
     "class Pair:\n"
     "    def __init__(self, s, n):\n"
     "        self.s = s\n"
     "        self.n = n\n"
     "\n"
     "def main(n):\n"
     "    var p = Pair(\"hi\", 7)\n"
     "    print(\"p:\", p.s, p.n)\n"
     "    return 0\n",
     "p: hi 7\n"),
]

# ── the tuple-store target shapes ──
#
# `a, b = rhs` is one construct with four target shapes, and the two
# architectures used to disagree about two of them.  arm64's `_tup_slot` already
# routed a `MemberExpr` element through `_store_var`, which is the frame-slot
# store; x86-64's `_emit_tuple_assign` built a list of NAMES and refused anything
# that was not one, so `h.x, h.y = p, q` was refused by name on x86-64 and
# answered correctly on arm64.  The fix is that the target element becomes
# whatever `_store_var` can store into — the same store, through the same
# function, so a tuple unpack and a plain `h.x = v` cannot disagree about where a
# field's value lands.
#
# The fourth shape is a SUBSCRIPT element (`a[0], b = 1, 2`), and it is the one
# that is not a `_store_var` key at all: an element of a blob has no frame home to
# name.  x86-64 refused it by node type (`got SubscriptExpr`) while arm64 routed
# it to its own `_emit_subscript_store_reg`, so one machine answered the program
# and the other declined it — and nothing in the suite exercised the shape, which
# is why it survived every merge that touched either half of the table.  It is
# now the same `("sub", el)` tag and the same store on both, so the tuple target's
# out-of-range index also exits(1) on both.
TUPLE_STORE_CASES = [
    # A receiver-relative field target OUTSIDE any constructor, which is the
    # reproducer the filing used and the shape `_store_var`'s frame-slot arm is
    # for.  Three targets so an off-by-one in the element pairing would show: the
    # answer is 3 + 4 + 7 and nothing else.
    ("tuple_store_to_receiver_fields",
     "class Tail:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "        self.z = 0\n"
     "    def total(self):\n"
     "        return self.x + self.y + self.z\n"
     "def main(n):\n"
     "    var t = Tail()\n"
     "    t.x, t.y, t.z = 3, 4, 7\n"
     "    printf(\"total=%d\", t.total())\n"
     "    return 0\n",
     "total=14"),
    # The same statement with `self` as the receiver, which is the spelling in
    # this repository's own code (`tools/procrun.py` has
    # `self.limit, self._chunks, self._size = limit, [], 0`) and which reaches a
    # DIFFERENT store: the method's own receiver frame rather than a local
    # holder's.  Pair it with a field target on a local too, so a pass that
    # handled only one of the two receiver shapes would answer one and not the
    # other.
    ("tuple_store_to_self_and_to_a_local",
     "class Pair:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def swap(self, p, q):\n"
     "        self.x, self.y = p, q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    var a = Pair(1, 2)\n"
     "    a.swap(9, 8)\n"
     "    var b = Pair(0, 0)\n"
     "    b.x, b.y = 5, 6\n"
     "    printf(\"a=%d b=%d\", a.total(), b.total())\n"
     "    return 0\n",
     "a=17 b=11"),
    # A MIXED target: one field and one plain name.  The two shapes have
    # different homes (a frame slot and a register) and the pairing has to hold
    # across them, which is the case that would catch a rewrite that turned every
    # element into a field store.
    ("tuple_store_mixes_a_field_and_a_name",
     "class Pair:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    var a = Pair(0, 0)\n"
     "    var b = 0\n"
     "    a.x, b = 7, 8\n"
     "    printf(\"a=%d b=%d\", a.total(), b)\n"
     "    return 0\n",
     "a=7 b=8"),
    # A NESTED group, which is the third shape and the one that was silently
    # miscounted rather than refused: x86-64 flattened it, so the outer arity
    # check compared the RHS blob's count (2) against a target count that
    # included the group's own elements (3) and the image exited(1) with nothing
    # printed — where arm64 and CPython both answer a=1 b=2 c=3.  Now the group
    # is a second unpack against the element at its position, and the arity
    # check at each level counts that level's elements and no other.
    ("tuple_store_to_a_nested_group",
     "def main(n):\n"
     "    var a = 0\n"
     "    var b = 0\n"
     "    var c = 0\n"
     "    a, (b, c) = 1, (2, 3)\n"
     "    printf(\"a=%d b=%d c=%d\", a, b, c)\n"
     "    return 0\n",
     "a=1 b=2 c=3"),
    # A SUBSCRIPT element target, the FOURTH shape and the one this backend used
    # to refuse by node type (`got SubscriptExpr`) while arm64 lowered it.  Two
    # targets on purpose, and in this order: the subscript store computes an
    # address through R10, which is the register this loop is walking the RHS
    # blob with, so `b` — read from `R10 + 8` AFTER the subscript store — is the
    # assertion that R10 survived it.  A version that stored the subscript
    # element's ADDRESS (the value-clobbering bug `_emit_subscript_store_reg`
    # exists for) still prints `a0=0`; a version that let the address
    # computation take R10 prints `b` as something else entirely.
    ("tuple_store_to_a_subscript_element_and_a_name",
     "def main(n):\n"
     "    var a = [0]\n"
     "    var b = 0\n"
     "    a[0], b = 1, 2\n"
     "    printf(\"a0=%d b=%d\", a[0], b)\n"
     "    return 0\n",
     "a0=1 b=2"),
    # Two subscript targets in ONE statement, out of order, with a plain name
    # after them: the second store's address computation reads a second base and
    # writes a second element, and the name after it is still read out of the
    # same blob — so this pins that the target loop's bookkeeping is per-element
    # and not per-statement, and that a swap is a swap (`a[1], a[0], b = 1, 2, 3`
    # leaves the list REVERSED, which is what CPython's parallel assignment
    # does and what a store that read the index first would not).
    ("tuple_store_to_two_subscript_elements_out_of_order",
     "def main(n):\n"
     "    var a = [0, 0]\n"
     "    var b = 0\n"
     "    a[1], a[0], b = 1, 2, 3\n"
     "    printf(\"a0=%d a1=%d b=%d\", a[0], a[1], b)\n"
     "    return 0\n",
     "a0=2 a1=1 b=3"),
    # A subscript target INSIDE a nested group, with a CALL in the index.  Both
    # halves are there for a reason: the group makes the outer unpack recurse,
    # and the recursion is the arm that has to save R10 across code that can
    # call — so this is the case that catches a bare `push %r10` there (RSP at 8
    # mod 16 at the call, which `otool -tvV` shows and no callee measured here
    # faulted on) as well as a store that loses either the value or the blob base.
    ("tuple_store_subscript_target_inside_a_nested_group",
     "def pick():\n"
     "    return 1\n"
     "def main(n):\n"
     "    var a = [0, 0]\n"
     "    var b = 0\n"
     "    var c = 0\n"
     "    var d = 0\n"
     "    a[pick()], (b, c) = 7, (2, 3)\n"
     "    d = 4\n"
     "    printf(\"a0=%d a1=%d b=%d c=%d d=%d\", a[0], a[1], b, c, d)\n"
     "    return 0\n",
     "a0=0 a1=7 b=2 c=3 d=4"),
]

# ── the GUARD for a refusal that is about a name, not about a construct ──
#
# `String()` on its own IS correct on this path — it is the address of an
# interned empty `char *`, and `printf("[%s]", a)` prints `[]` — so only a name
# that is ALSO used as a receiver can be refused.  A check that fired on the
# construction alone would refuse 11 stdlib files for binding a `char *`.
#
# **No CPython oracle for this one, and the reason is the point**: `String` is a
# builtin this path defines and CPython does not, so the oracle program is a
# different program.  That is why the expected value is pinned instead — the
# assertion is "this builds and prints the empty string", which is a fact about
# the REPRESENTATION and not about the language, and there is no CPython run that
# could confirm it.  It is a separate group rather than a `want_stdout` on an
# oracle case so the difference is visible in the file rather than hidden in a
# flag.
FIXED_CASES = [
    ("a_conversion_is_fine_until_something_writes_a_field_through_it",
     "def main(n):\n"
     "    var a = String()\n"
     "    printf(\"[%s]\", a)\n"
     "    return 0\n",
     "[]"),
    # ── a container in a field, put there by the CONSTRUCTOR ──
    #
    # The container row of the same question.  A container has no LITERAL
    # class-level default on this path (`struct_frame_representable` refuses one
    # by name: "the default is not a literal"), so the CONSTRUCTOR is the only
    # thing that can give the slot a value, and for a long time that door was
    # shut: `len(self._data)` was refused with "this slot's DECLARED type is
    # 'List[Int]' … what is missing is the VALUE", which is TRUE of a struct with
    # no constructor and FALSE of this one, whose `__init__` is inlined at the
    # construction site and stores `[1, 2, 3]`.
    #
    # `std/collections/binary_heap.mojo` is the shape this was found on, and its
    # two halves are the two halves of the value: `len(self._data)` through a
    # `__len__` (the receiver IS the one field), and `len(b)` through a bare
    # name.  Both are here, and BOTH containers are in ONE image, so a
    # classification that answered one and not the other would show up as two
    # numbers that must agree.
    #
    # A PINNED expectation rather than the oracle the cases above carry, and
    # the reason is the one `a_conversion_is_fine_until_something_writes_a_field_
    # through_it` gives for being in FIXED_CASES: the program uses constructs
    # CPython cannot parse at all (`struct`, `out self`, `List[Int]()`), so there
    # is no oracle text to derive.  4 and 0 are what the SOURCE says — four
    # elements and an empty container — and both architectures were measured to
    # return them.
    ("a_one_field_container_struct_measures_its_own_len",
     "struct Sized:\n"
     "    var _data: List[Int]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._data = [1, 2, 3, 4]\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return len(self._data)\n"
     "\n"
     "    def __len__(self) -> Int:\n"
     "        return len(self._data)\n"
     "\n"
     "def main(n):\n"
     "    var s = Sized()\n"
     "    printf(\"m=%d l=%d\", s.size(), len(s))\n"
     "    return 0\n",
     "m=4 l=4"),
    # The EMPTY container, which is the same program with a different blob: a
    # zero-operand construction rather than a display.  It is here because
    # `BinaryHeap.__init__` is `self._data = List[Self.T]()` and not a display,
    # and because the two are lowered by DIFFERENT emitters (`_emit_empty_blob`
    # and `_emit_list`) — a kind claimed for one says nothing about the other.
    # 0 rather than 4 is the whole difference between the cases.
    ("a_one_field_container_struct_built_empty_measures_zero",
     "struct Sized:\n"
     "    var _data: List[Int]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._data = List[Int]()\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return len(self._data)\n"
     "\n"
     "def main(n):\n"
     "    var s = Sized()\n"
     "    printf(\"z=%d\", s.size())\n"
     "    return 0\n",
     "z=0"),
]

# ── what a holder MAY be assigned, which is what the refusal above is about ──
#
# The check exists because a name that holds a frame address is never removed
# from the holder set, so a later store of a plain word leaves every field access
# through it reading `[word + 8·slot]`.  These three are the shapes that must
# keep working, and each is one of the three the refusal names: a CONSTRUCTION
# under a branch (a frame the analysis cannot see the path to, so it must be
# accepted on both paths), a COPY under a different name, and a field write
# through a method's own `self` — which is a `self.x` store and not a rebinding
# of `self`, and is the shape a too-eager check would break first.
HOLDER_ASSIGN_CASES = [
("holder_may_be_construction_copy_and_self_write",
     "class R:\n"
     "    def __init__(self, v):\n"
     "        self.a = v\n"
     "        self.b = 0\n"
     "    def get(self):\n"
     "        return self.a\n"
     "    def swap(self, other):\n"
     "        self.a = other.a\n"
     "        self.b = other.b\n"
     "    def total(self):\n"
     "        return self.a + self.b\n"
     "\n"
     "def pick(r, n):\n"
     "    if n:\n"
     "        var r2 = R(9)\n"
     "        return r2.get()\n"
     "    return r.get()\n"
     "\n"
     "def main(n):\n"
     "    var r = R(7)\n"
     "    var s = R(3)\n"
     "    t = s\n"
     "    r.swap(s)\n"
     "    printf(\"a=%d b=%d c=%d\", pick(r, n), t.get(), r.total())\n"
     "    return 0\n",
     "a=9 b=3 c=3"),
]

# ── what a module-level binding may be used for, which is what the two
#    read/assign refusals below are about ──
#
# Both refusals are about a function and a module-level name COLLIDING, and a
# check that fired on the collision rather than on the shape would refuse the
# case CPython is happy with: a local that shadows a module global without
# writing it.  That is the one the path already gets right — a folded module
# constant is SUBSTITUTED at every read, and a local that shadows it never
# reaches the module's storage — so it is pinned here, together with the
# shadow-free read beside it.
MODULE_GLOBAL_CASES = [
    ("a_local_may_shadow_a_module_global_and_the_module_keeps_its_value",
     "G = 5\n"
     "\n"
     "def shadow():\n"
     "    G = 99\n"
     "    return G\n"
     "\n"
     "def rd():\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    printf(\"s=%d r=%d g=%d\", shadow(), rd(), G)\n"
     "    return 0\n",
     "s=99 r=5 g=5"),
    # THE SAME NAME, WRITTEN through a `global` declaration — which the
    # language allows and which used to have nowhere to live.
    #
    # This case was a REFUSAL (`REFUSALS`, below, with the needle "G is
    # declared `global` in bump() and assigned there") and it moved HERE
    # because the refusal became the wrong answer, not because the test grew
    # tired of it. Two branches fixed the same construct in the same batch
    # without ever meeting (`git merge-base` of `81b6d101` and `4b5629aa` is
    # `a0c09694`, and neither is an ancestor of the other):
    #
    #   * `formal-value-model` added `mutated_module_global_refusal` and this
    #     case with it. Its measurement is in that function's docstring and is
    #     still exactly right about the tree IT saw: CPython answers 6 and 6,
    #     and this path answered 10601485 and 5 on arm64, 11 and 5 on x86-64.
    #   * `formal-module-globals` gave every name a function writes a real
    #     `__DATA` slot, and its own `formal/build.py` comment says what that
    #     does to this check: "`formal-module-globals` landed the slot, so
    #     refusing it now refuses a program this path computes exactly".
    #
    # So the storage arrived, the refusal's premise went with it, and the
    # refusal itself was narrowed to `declared_globals & assigned -
    # module_slots()` — which is right, and which makes this case a program the
    # path now computes. Measured on the merged tree, both architectures, the
    # image built and printed `bump=6 read=6`, which is what CPython prints.
    #
    # It is here rather than deleted because a wrong answer is worse than no
    # answer and the fix is exactly the kind one regression undoes: pin what
    # the path computes now, so the day a `global` write stops reaching its
    # slot this reads as `bump=<garbage> read=5` against CPython instead of
    # passing.
    ("a_module_global_a_function_declares_global_and_assigns_it",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    global G\n"
     "    G = G + 1\n"
     "    return G\n"
     "\n"
     "def rd():\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    printf(\"bump=%d read=%d\", bump(), rd())\n"
     "    return 0\n",
     "bump=6 read=6"),
    # ── a dict that arrives from a CALL, and a string subscript over it ──
    #
    # `d["a"]` has two readings on this path and the INDEX chooses neither of
    # them: a dict KEY scan or a byte offset into a `char *`, and which one it
    # is comes from the BASE. Every container is one word with an 8-byte count
    # header here, so the KIND of the base cannot say — which is why
    # `_is_dict_subscript` is a separate question from `kind_of`, and why the
    # three spellings below were three separate faults:
    #
    #   * `D = {"a": 1}` at module level  — worked (the slot's initializer)
    #   * `D = mk()` at module level       — fixed 2026-10-02 (the callee's
    #                                          declared return type)
    #   * `d = mk()` as a LOCAL, and `def show(d: dict)` — BOTH exited 1 with
    #     nothing printed, from a green build, on both architectures: the
    #     binding held no dict literal for `_note_binding` to see, so the
    #     subscript took the SEQUENCE path and read the key's interned ADDRESS
    #     as an element offset.
    #
    # The two value cases are the two halves of that, and the second one is the
    # row that says the fix is not annotation-only: an UNANNOTATED callee whose
    # `return` states a dict literal has as much evidence as an annotated one.
    ("a_dict_from_a_call_with_a_declared_return_type",
     "def mk() -> dict:\n"
     "    var d = {\"a\": 1}\n"
     "    return d\n"
     "\n"
     "def main(n):\n"
     "    var d = mk()\n"
     "    printf(\"%d|\", d[\"a\"])\n"
     "    return 0\n",
     "1|"),
    ("a_dict_from_an_unannotated_call_whose_return_states_one",
     "def mk():\n"
     "    var d = {\"a\": 1}\n"
     "    return d\n"
     "\n"
     "def main(n):\n"
     "    var d = mk()\n"
     "    printf(\"%d|\", d[\"a\"])\n"
     "    return 0\n",
     "1|"),
    # A PARAMETER, which is the spelling with no BINDING statement at all:
    # `_note_binding` never sees it, so the annotation is the only evidence
    # there is. This is the row `declared_type_is_dict` exists for.
    ("a_dict_subscript_through_a_dict_annotated_parameter",
     "def show(d: dict):\n"
     "    printf(\"%d|\", d[\"a\"])\n"
     "    return 0\n"
     "\n"
     "def main(n):\n"
     "    show({\"a\": 1})\n"
     "    return 0\n",
     "1|"),
]

# (name, source, needle the refusal must contain)
#
# AGREE-OR-REFUSE, and both of these are the shape the rule exists for: the
# name holds a different frame on each path that binds it, and only ONE of the
# candidates declares a dunder, so which call the comparison lowers to depends
# on the path and this analysis has no path sensitivity.  The pre-change tree
# answered both of them with a flag-setting compare of two addresses and no
# diagnostic — and for `cross_struct` that was a wrong answer, because CPython
# asks the RIGHT operand's `__eq__` when the left one's returns NotImplemented,
# and this path has no representation for NotImplemented to be returned as.
REFUSALS = [
    # THE GATE that `a_dict_subscript_is_the_kind_of_the_pair_under_that_key`
    # earns by being answered: unanimity is over the pairs under ONE KEY, so a
    # literal that spells the same key twice with values of two kinds has no
    # answer. CPython keeps the LAST pair (`{"a": 1, "a": [2]}` makes `d["a"]` a
    # list); this path cannot claim a kind for a word whose two writers
    # disagree, which is the same refusal `own_shape_kind` makes for a local.
    #
    # The needle is the INTEGER row rather than the unclassified one, and that
    # is worth saying because it is the fallback showing through: with no
    # per-key answer the subscript falls back to the whole dict's element kind,
    # which the pre-existing `_kind_of_elements` computes over every value and
    # which does NOT see the nested list — so it reads "int" and the integer row
    # is what refuses. A different sentence, the same refusal, and the shape
    # that reaches it is one whose answer no reader could have had anyway.
    ("a_dict_whose_one_key_holds_two_kinds_is_refused",
     "def main(n):\n"
     "    var d = {\"a\": 1, \"a\": [2, 3]}\n"
     "    print(\"n:\", len(d[\"a\"]))\n"
     "    return 0\n",
     "an integer has no length"),
    # …and the two shapes the gate exists for. A dict subscript whose element
    # word no store wrote is a count read from address 0, so a key the literal
    # does not contain, and a key this path cannot COMPARE with the literal's,
    # both stay refused. Measured in the field spelling of this as a build that
    # ran and died with SIGSEGV — `struct_field_kind`'s docstring has it.
    ("a_dict_subscript_of_a_key_the_literal_lacks_is_refused",
     "def main(n):\n"
     "    var d = {\"a\": [1, 2]}\n"
     "    print(\"n:\", len(d[\"b\"]))\n"
     "    return 0\n",
     "the source does not say what this operand holds"),
    ("a_dict_subscript_of_a_name_key_is_refused",
     "def main(n):\n"
     "    var d = {\"a\": [1, 2]}\n"
     "    var k = \"a\"\n"
     "    print(\"n:\", len(d[k]))\n"
     "    return 0\n",
     "the source does not say what this operand holds"),
    ("one_name_two_candidate_structs_is_refused",
     "class A:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "class B:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def main(n):\n"
     "    var v = A(1, 2)\n"
     "    if n:\n"
     "        v = B(1, 2, 3)\n"
     "    printf(\"r=%d\", 1 if v == v else 0)\n"
     "    return 0\n",
     "compares two FRAME ADDRESSES"),
    ("two_structs_only_one_with_a_dunder_is_refused",
     "class A:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "class B:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def main(n):\n"
     "    var a = A(1, 2)\n"
     "    var b = B(1, 2, 3)\n"
     "    printf(\"r=%d\", 1 if a == b else 0)\n"
     "    return 0\n",
     "does not settle it"),
    # A NAME THAT STOPS BEING A FRAME.  The holder set is additive — nothing
    # ever removes a name from it — so `r = 5` after `r = R()` leaves every
    # `r.<field>` lowered as a load at `[5 + 8·slot]`.  Measured on both
    # architectures from a green build: SIGSEGV, exit 139, where the source says
    # 5.  Refused, by name, with the binding that disagrees in the message.
    #
    # The CONDITIONAL form is in the same case on purpose: `if n: r = 5` is the
    # same finding, because the analysis has no path sensitivity and the whole
    # refusal family rests on that rather than on it.
    ("holder_rebound_from_a_word_is_refused",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r = 5\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     "r is assigned 5 in main()"),
    ("holder_rebound_under_a_condition_is_refused",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    if n:\n"
     "        r = 5\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     "r is assigned 5 in main()"),
    # A NAME THAT IS BOTH A LOCAL FRAMED STRUCT AND A TYPE CONVERSION.  The
    # emitters intercept `String()` as a string CONVERSION before
    # `_emit_struct_constructor` is reached, so the value is the address of an
    # interned `char *`, while the build pass's constructor-binding recognition
    # saw a call to a name in `framed_struct_names` and made the local a
    # three-slot frame HOLDER — and the field store landed in read-only `__TEXT`.
    # Measured before the fix on both architectures: SIGBUS, exit 138, from a
    # green build, on the stdlib's own three-field `String` verbatim.
        ("a_name_that_is_both_a_struct_and_a_conversion_is_refused",
     "struct String:\n"
     "    var _ptr_or_data: Pointer[UInt8]\n"
     "    var _len_or_data: Int\n"
     "    var _capacity_or_data: Int\n"
     "    def size(self) -> Int:\n"
     "        return self._len_or_data\n"
     "def main(n: Int) -> Int:\n"
     "    var a = String()\n"
     "    a._len_or_data = 5\n"
     "    return a.size()\n",
     "a = String(...) binds a to a value this path holds as TEXT"),
    # A LOCAL READ BEFORE IT HAS BEEN ASSIGNED, where the name is also a
    # module-level binding.  The right-hand `G` does NOT resolve in module
    # scope: a name assigned anywhere in a function body is local to that body
    # from its first line, so CPython raises UnboundLocalError and the program
    # has no number.  What this path did was read the local's register, which
    # holds whatever the allocator left there — 11 on x86-64 and 78152773 on
    # arm64 from identical source.  The refusal is also where the filing's
    # proposed fix is corrected: making the gate order-dependent would answer 6,
    # which is a number CPython never produces.
    ("a_local_read_before_its_first_assignment_is_refused",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    G = G + 1\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    printf(\"local=%d global=%d\", bump(), G)\n"
     "    return 0\n",
     "G is read in bump() at `G + 1`"),
    # A `global G; G = G + 1` was HERE, next to the read-before-assign case
    # above, with the needle "G is declared `global` in bump() and assigned
    # there". It moved to `MODULE_GLOBAL_CASES` — same program, now pinned for
    # what it computes rather than for a refusal that stopped being the right
    # answer when `formal-module-globals` gave the name a real `__DATA` slot.
    # That comment, and the measurement behind the move, are on the case.
    # AN ELEMENT OF AN INTEGER.  Every container lowering reads the blob's count
    # from offset 0 of its base and then reads or writes at `base + 8 + 8k`, so
    # for `a = 5` the element address is 13 and the image faults: measured on
    # both architectures from a GREEN build, SIGSEGV, exit 139.  This is here
    # and not only in `test_formal_run.py` because `run_refusal` builds BOTH
    # architectures and requires the identical message from each, and for this
    # refusal "identical on both" is the whole assertion — the defect is SHARED
    # by the two backends, so a two-architecture comparison cannot see it.
    ("an_element_of_an_integer_is_refused",
     "def main(n):\n"
     "    var a = 5\n"
     "    a[0] = 1\n"
     "    printf(\"a=%d\", a)\n"
     "    return 0\n",
     "asks for a container element"),
    # `%s` OF AN INTEGER, and the same argument for putting it here: the
    # defect is SHARED by the two backends, so only a refusal that is required
    # to read identically from each can see it.  `%s` is the one printf
    # conversion that dereferences its argument — every other one renders the
    # word — so `a = 5; printf("[%s]", a)` walked bytes at address 5 looking
    # for a NUL.  Measured on both architectures from a GREEN build: nothing
    # printed, SIGSEGV, exit 139.  The evidence is the same
    # `ValueKinds.own_shape_kind` the container-element refusal above asks,
    # which is why one predicate answers both.
    ("a_percent_s_of_an_integer_is_refused",
     "def main(n):\n"
     "    var a = 5\n"
     "    printf(\"[%s]\", a)\n"
     "    return 0\n",
     "conversion in printf's format string reads"),
    # `%s` OF A ONE-FIELD STRUCT, the same fault through the one shape that has
    # no frame for a frame check to refuse. `P(7)` binds a word that IS `P`'s
    # only field, so `%s` walked bytes at address 7: SIGSEGV, exit 139, on both
    # architectures from a green build. The needle is the DECLARATION the
    # refusal quotes rather than the generic clause, because the evidence here
    # is a declaration and not a statement — `model.one_word_value_text_evidence`
    # — and a needle the two evidences share would let one of them regress into
    # the other's message.
    ("a_percent_s_of_a_one_field_struct_is_refused",
     "struct One:\n"
     "    var x: Int\n"
     "\n"
     "def main(n):\n"
     "    var c = One(7)\n"
     "    printf(\"[%s]\", c)\n"
     "    return 0\n",
     "struct of ONE field has no frame at all"),
    # ORDERING A FRAME ADDRESS, and the reason a wrong BRANCH belongs in the
    # oracle's file rather than only in the suite:  `x < y` on two multi-field
    # structs reached the flag-setting compare of two ADDRESSES, so which way it
    # went was decided by where the allocator put them.  Measured on both
    # architectures for two objects holding EQUAL field values: `lt=1 gt=0
    # le=1 ge=0`.  Both backends agreed, so a two-architecture comparison
    # cannot see it and only a CPython oracle can — CPython raises
    # `TypeError: '<' not supported between instances`, which is the answer
    # this path now gives as a build error.
    ("ordering_a_frame_address_is_refused",
     "class Pair:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, a, b):\n"
     "        self.x = a\n"
     "        self.y = b\n"
     "    def __eq__(self, other):\n"
     "        return self.x == other.x and self.y == other.y\n"
     "\n"
     "def main(n):\n"
     "    var p = Pair(1, 2)\n"
     "    var q = Pair(1, 2)\n"
     "    printf(\"lt=%d\", 1 if p < q else 0)\n"
     "    return 0\n",
     "orders the ADDRESS of a Pair FRAME"),
    # A DICT WHOSE VALUES DISAGREE, and the case is here rather than only in
    # the passing ones because it is the SAFETY PROPERTY of the element kind
    # they carry: `{"a": 10, "b": "text"}` states two kinds, and a kind table
    # that picked either one would print an interned address as a number or a
    # number as text — the failure mode the whole element-kind work is arranged
    # to prevent.  `run_refusal` is the instrument for the rows below, because a
    # defect in that table would be SHARED by the two backends (they read one
    # table) and so cannot be seen by requiring them to agree.
    # ── the four gates on a field kind read off a construction ──
    #
    # Each of these is a case where claiming a kind from `p = S(args)` would be
    # a claim the source does not support, and each is a REFUSAL rather than a
    # number because the wrong answer is a fault: `run_refusal` builds BOTH
    # architectures and requires the identical message from each, and that is
    # the only instrument that can see a defect both backends share.
    #
    # The one that is not theoretical is the first.  The construction says what
    # went into the slot WHEN THE OBJECT WAS BUILT, and a statement after it in
    # the same function puts something else there; measured on both
    # architectures from a GREEN build, with the classification claiming a
    # string and the store making it the integer 5:
    #
    #     p = P("hi", 7)
    #     p.s = 5
    #     print("s:", p.s)        ->  SIGSEGV, exit 139
    #
    # which is the same fault `a_percent_s_of_an_integer_is_refused` exists to
    # keep out, reached through a field rather than through a name.
    ("a_field_written_after_its_construction_is_refused",
     "class P:\n"
     "    def __init__(self, s, n):\n"
     "        self.s = s\n"
     "        self.n = n\n"
     "\n"
     "def main(n):\n"
     "    var p = P(\"hi\", 7)\n"
     "    p.s = 5\n"
     "    print(\"s:\", p.s)\n"
     "    return 0\n",
     "cannot tell whether MemberExpr"),
    # The argument is one of this function's own unannotated PARAMETERS: a word
    # arriving from a caller, which this model calls an integer everywhere else
    # but which says nothing about what `p.s` holds, and the two hops from the
    # caller to a struct field are exactly where a "a word is an integer"
    # default becomes a wrong number rather than a harmless one.
    ("a_field_built_from_an_unannotated_parameter_is_refused",
     "class P:\n"
     "    def __init__(self, s, n):\n"
     "        self.s = s\n"
     "        self.n = n\n"
     "\n"
     "def main(q):\n"
     "    var p = P(q, 7)\n"
     "    print(\"s:\", p.s)\n"
     "    return 0\n",
     "cannot tell whether MemberExpr"),
    # A METHOD writes the field, so the constructor's argument is a statement
    # about the past.  `ValueKinds` is flow-INsensitive by construction, so
    # without this gate `p.s` would answer the same everywhere in the function
    # including after the setter ran.
    ("a_field_written_by_another_method_is_refused",
     "class P:\n"
     "    def __init__(self, s, n):\n"
     "        self.s = s\n"
     "        self.n = n\n"
     "    def set_s(self, v):\n"
     "        self.s = v\n"
     "\n"
     "def main(n):\n"
     "    var p = P(\"hi\", 7)\n"
     "    p.set_s(\"bye\")\n"
     "    print(\"s:\", p.s)\n"
     "    return 0\n",
     "cannot tell whether MemberExpr"),
    # TWO constructions that disagree, on two arms of the same `if`.  Flow
    # insensitivity is what makes this the right question: one name, one slot,
    # two stated kinds, so the slot is undecided rather than whichever arm the
    # reader happened to look at first.
    ("a_field_whose_constructions_disagree_is_refused",
     "class P:\n"
     "    def __init__(self, s, n):\n"
     "        self.s = s\n"
     "        self.n = n\n"
     "\n"
     "def main(k):\n"
     "    if k:\n"
     "        var p = P(\"hi\", 7)\n"
     "    else:\n"
     "        var p = P(3, 7)\n"
     "    print(\"s:\", p.s)\n"
     "    return 0\n",
     "cannot tell whether MemberExpr"),
    # A STRING INDEX AGAINST A BASE NOTHING DESCRIBES — the residue after the
    # three value cases above, and the last spelling of one expression that
    # used to be four faults.  It is here rather than left to exit 1 because
    # what it did was WORSE than an exit: the emitter fell back to "a blob",
    # the blob walk took the key's interned address as an ELEMENT offset, and
    # the program printed whatever followed in __TEXT.  A refusal is the honest
    # answer when the two readings are a scan over pair slots and `base + i`.
    #
    # The needle is the INDEX sentence rather than the message's opening, so a
    # reworded preamble does not fail this and a reworded REASON does.
    ("a_string_index_against_an_unstated_base_is_refused",
     "def show(d):\n"
     "    printf(\"%d|\", d[\"a\"])\n"
     "    return 0\n"
     "\n"
     "def main(n):\n"
     "    show({\"a\": 1})\n"
     "    return 0\n",
     "the INDEX is a string and nothing in the source says what `d` holds"),
]



def run_cpython(source, tmpdir, verbose):
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(cpython_source(source))
    proc = subprocess.run([sys.executable, path], capture_output=True,
                          text=True, timeout=RUN_TIMEOUT)
    if verbose:
        print(f"      cpython: {proc.stdout!r} exit={proc.returncode}"
              + (f" stderr={proc.stderr.strip()[:200]}" if proc.stderr else ""))
    return proc.returncode, proc.stdout


def build_formal(src, out, backend):
    proc = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return proc.returncode, (proc.stdout + proc.stderr)


def run_case(name, source, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    want_exit, want_out = run_cpython(source, tmpdir, verbose)
    if want_out != want_stdout:
        return False, (f"the case's own expectation ({want_stdout!r}) is not "
                       f"what CPython prints ({want_out!r}); the expectation is "
                       f"the wrong half, not the image")
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc != 0:
            return False, f"--backend={backend} refused: {text.strip()[-300:]}"
        proc = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT)
        if proc.stdout != want_out or proc.returncode != want_exit:
            return False, (
                f"--backend={backend} answered {proc.stdout!r} exit="
                f"{proc.returncode} where CPython answers {want_out!r} exit="
                f"{want_exit}"
                + (f" (stderr {proc.stderr.strip()[:160]})" if proc.stderr
                   else ""))
        if verbose:
            print(f"      {backend}: {proc.stdout!r} exit={proc.returncode}")
    return True, ""


def run_fixed_case(name, source, want_stdout, tmpdir, verbose):
    """Build and run both architectures, against a PINNED expectation.

    The only difference from `run_case` is that there is no oracle, and the only
    member of FIXED_CASES that needs one is there because the program uses a
    builtin this path defines and CPython does not.  Everything else — the
    comparison, the exit status, the refusal-is-a-failure rule — is identical,
    so a second code path would be a second thing to keep right."""
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc != 0:
            return False, f"--backend={backend} refused: {text.strip()[-300:]}"
        proc = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT)
        if proc.stdout != want_stdout:
            return False, (f"--backend={backend} answered {proc.stdout!r} "
                           f"where this case pins {want_stdout!r}")
        if verbose:
            print(f"      {backend}: {proc.stdout!r}")
    return True, ""


def run_refusal(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a comparison whose "
                           f"answer depends on which of two structs the name "
                           f"holds at run time; the binary is the real answer "
                           f"here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not naming "
                           f"{needle!r}: {text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on both architectures, naming "
              f"{needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    everything = ([(c, False) for c in CASES]
                  + [(c, False) for c in TUPLE_STORE_CASES]
                  + [(c, False) for c in HOLDER_ASSIGN_CASES]
                  + [(c, False) for c in MODULE_GLOBAL_CASES]
                  + [(c, "fixed") for c in FIXED_CASES]
                  + [(c, True) for c in REFUSALS])
    selected = [c for c in everything if not args.cases or c[0][0] in args.cases]
    known = {c[0][0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): "
              f"{sorted(set(args.cases) - known)}", file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for entry, kind in selected:
            try:
                if kind == "fixed":
                    ok, detail = run_fixed_case(entry[0], entry[1], entry[2],
                                                tmpdir, args.verbose)
                elif kind:
                    ok, detail = run_refusal(entry[0], entry[1], entry[2],
                                             tmpdir, args.verbose)
                else:
                    ok, detail = run_case(entry[0], entry[1], entry[2], tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {entry[0]}")
            else:
                failed += 1
                print(f"  FAIL  {entry[0]}: {detail}")

    print(f"\nformal value model: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
