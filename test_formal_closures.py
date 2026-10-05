#!/usr/bin/env python3
"""Closures, lambdas, first-class functions, decorators and generators on the
formal backends, with CPython as the oracle.

Every other formal suite asks one of two questions: "does the proof typecheck"
(`test_formal.py`) or "does the binary compute the answer this file names"
(`test_formal_run.py`, whose expected values are CONSTANTS stated in each case's
comment). Neither can say "this construct is wrong on this backend in a way
nobody wrote down", because a constant is whatever the author believed when the
case was written, and the constructs this file is about are exactly the ones
whose right answer is not obvious from the Mojo text: a closure over a loop
variable binds LATE, a decorator replaces the function it decorates, and a
generator function does not run its body until something iterates it.

So the table here is the other shape: ONE source text per case, run three ways
— CPython (`python3`, with `main()` appended), the arm64 image, and the
x86-64 image — and the three stdouts must be identical. The Mojo subset used is
`print` of integers and integer expressions, which is what the closure,
lambda, decorator and generator questions are made of; nothing here needs a
`printf` spelling CPython cannot run.

ONE divergence found while building this table is deliberately ABSENT from it,
and is filed instead: a comprehension whose element is a container
(`[[x + y for x in [1, 2]] for y in [10, 20, 30]]`) aliases every outer
iteration's element to the LAST one and answers 93 where CPython answers 63, on
both backends, with exit 0. An answered row would have to assert that number, and
this file's premise is that an answered row EQUALS CPython's; a refusal row
would have to be a refusal, and this is not one. See
`bugs/FORMAL_a_comprehension_element_container_aliases_every_iteration.md` for the
signature (it is not B1, B2 or B4 in `bugs/OPEN_WORK.md`) and for why pinning it
here would be the wrong kind of test.

    python3 test_formal_closures.py [-v] [case ...]

A refusal case is a different assertion and has a different shape: both
backends must REFUSE, must say the SAME WORDS, and those words must name the
CONSTRUCT. The cross-backend identity is not decoration \u2014 two machines naming
one limit differently is the failure `test_formal_run.py`'s CPython-pair group
was created for, and the naming is the requirement CLAUDE.md states for this
area: a reader told "'v' has no home" has nothing to act on, while a reader
told "`sorted` with `key=` needs a callable this path has no representation
for" has the next edit.
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# ── ANSWERED cases: (name, source) ────────────────────────────────────────
#
# One text, three oracles. `main()` returns 0 and the formal entry function's
# return value is the process exit status, so both must be 0 and the stdouts
# must match byte for byte.
#
# An optional THIRD element is a needle the CPython stdout must contain. It is
# for the one case where the program cannot run here and the reason is the
# finding: CPython raises on it, so the interesting fact is which exception, and
# a case that asserted a build instead would assert a thing the tree does not do.
#
# Grouped by what each group PROVES, and each group has a member that fails if
# the mechanism it exercises is removed, because a table of cases that all pass
# for the same accidental reason is a table that proves nothing.
CASES = [
    # ── a nested `def` that CAPTURES a local of its enclosing function ──
    #
    # This is the one higher-order construct that lowers, and it lowers
    # through a by-value capture ABI rather than through a function value: the
    # nested `def` is LIFTED to module scope with the captured names prepended
    # as leading parameters (`formal/build.py`'s `_flatten_closures`, whose
    # `discover_closures` half is shared with the compiled backend through
    # `mojo/middle/closures.py`), and the call site inside the enclosing scope
    # is rewritten to pass them. So the closure is not a value anywhere, and
    # `capture_read_directly_in_the_enclosing_scope` is the row that says so: if
    # this ever starts working by materializing a function pointer instead, this
    # row is the one that would have to keep passing.
    ("capture_read_directly_in_the_enclosing_scope",
     "def make_adder(n):\n"
     "    def add(x):\n"
     "        return x + n\n"
     "    return add(5)\n"
     "def main():\n"
     "    print(make_adder(10))\n"
     "    return 0\n"),
    # Two captures, one of them a parameter and one a local, so a row that only
    # ever captured a parameter cannot be what makes this pass.
    ("capture_two_locals_one_a_parameter",
     "def outer(a):\n"
     "    b = 4\n"
     "    def both(x):\n"
     "        return x + a + b\n"
     "    return both(1)\n"
     "def main():\n"
     "    print(outer(10))\n"
     "    return 0\n"),
    # TRANSITIVE capture, which is the part a one-level pre-pass gets wrong: the
    # middle function does not use `a` itself and still has to pass it down, so
    # the answer (13) is wrong unless the capture set is closed over the chain.
    ("capture_three_levels_deep",
     "def outer(a):\n"
     "    def mid(b):\n"
     "        def inner(c):\n"
     "            return c + a + b\n"
     "        return inner(1)\n"
     "    return mid(2)\n"
     "def main():\n"
     "    print(outer(10))\n"
     "    return 0\n"),
    # A capture read inside a LOOP body, so the answer cannot come from a
    # register that happened to hold the value at function entry.
    ("capture_read_inside_a_loop_body",
     "def outer(a):\n"
     "    def add(x):\n"
     "        return x + a\n"
     "    s = 0\n"
     "    for x in [1, 2]:\n"
     "        s = s + add(x)\n"
     "    return s\n"
     "def main():\n"
     "    print(outer(10))\n"
     "    return 0\n"),
    # A nested `def` with NO capture, which is the shape that must keep working
    # for the rows above to mean anything: if the lifting machinery refused
    # every nested def, this would fail with them.
    ("nested_def_without_a_capture_is_called_in_place",
     "def outer(k):\n"
     "    def inner(x):\n"
     "        return x + 1\n"
     "    return inner(k)\n"
     "def main():\n"
     "    print(outer(4))\n"
     "    return 0\n"),
    # RECURSION through a nested def, called in the scope that defines it. The
    # recursion is by NAME, so it resolves to the lifted symbol; 120 is
    # `fact(5)` and any wrong frame gives a different number.
    ("a_nested_def_calls_itself_by_name",
     "def main():\n"
     "    def fact(n):\n"
     "        if n <= 1:\n"
     "            return 1\n"
     "        return n * fact(n - 1)\n"
     "    print(fact(5))\n"
     "    return 0\n"),

    # ── lambda ──
    #
    # Assigned to a name, which is the spelling `_lift_lambdas` has always
    # turned into a lifted module-level `def`.
    ("lambda_assigned_to_a_name_then_called",
     "def main():\n"
     "    f = lambda v: v * 2\n"
     "    print(f(3))\n"
     "    return 0\n"),
    # With a DEFAULT argument, which is the one thing a lambda's lifted form has
    # to carry across (`param_has_default`/`param_defaults`) or the second call
    # would read an unallocated slot.
    ("lambda_with_a_default_argument",
     "def main():\n"
     "    f = lambda v, m=3: v * m\n"
     "    print(f(2))\n"
     "    print(f(2, 4))\n"
     "    return 0\n"),
    # IMMEDIATELY invoked, which is the one lambda position that is not a value
    # at all: `(lambda q: q + 1)(v)` is a call whose callee is the lambda, and
    # it lowers by lifting the body and naming the symbol.
    ("lambda_called_immediately_over_a_loop",
     "def main():\n"
     "    s = 0\n"
     "    for v in [1, 2, 3]:\n"
     "        s = s + (lambda q: q + 1)(v)\n"
     "    print(s)\n"
     "    return 0\n"),

    # ── a function passed as an argument ──
    #
    # `h(g, 1)` calls `g` through the parameter, so this is an INDIRECT call and
    # the answer (2) is only right if the word in the parameter really is the
    # callee.
    ("a_top_level_function_passed_as_an_argument",
     "def g(x):\n"
     "    return x + 1\n"
     "def h(f, v):\n"
     "    return f(v)\n"
     "def main():\n"
     "    print(h(g, 1))\n"
     "    return 0\n"),
    # A LAMBDA as the argument, which is the same indirect call with the
    # callable written at the call site. This is the row the lifted-lambda naming
    # exists for: before it, `apply2(lambda v: v * 3, 7)` was refused on both
    # backends with `main: 'v' has no home`, because the name-allocation walk
    # descended into the `LambdaExpr` and demanded the lambda's own parameter as
    # a local of `main` — where it is not a local at all, it is a parameter of the
    # lifted `FunctionDef` the lambda became.
    ("a_lambda_passed_as_an_argument",
     "def apply2(f, x):\n"
     "    return f(x)\n"
     "def main():\n"
     "    print(apply2(lambda v: v * 3, 7))\n"
     "    return 0\n"),
    # The same lambda with a CAPTURE, which is the wall the row above does not
    # reach. A lambda lifts to a function of only its OWN declared parameters, so
    # `m` is a free name in the lifted body and this path has nowhere to put the
    # enclosing frame's value — a nested `def` has an environment (the by-value
    # capture parameters `_flatten_closures` prepends) and a lambda never
    # participates in it. The compiled backend answers this shape by BETA-
    # REDUCTION (`mojo/middle/lambdareduce.py`, which can only inline where the
    # lambda is called through its own name in the same function); handing one to
    # an arbitrary callee has no such call site to inline into.
    #
    # A refusal rather than an expansion, and the reason it is not the first
    # thing tried is that inlining it here would mean the lambda's body is
    # emitted once PER CALLEE with the callee's own frame — a program whose
    # answer depends on which of two call sites ran would need two copies of the
    # body and an environment either way.
    #
    # Placed in the answered group rather than the refusals on purpose: this is
    # the row that says the capture half is ABSENT rather than wrong, and a
    # future implementation has to move it out of here.
    ("a_lambda_passed_as_an_argument_captures_a_local",
     "def apply2(f, x):\n"
     "    return f(x)\n"
     "def main():\n"
     "    m = 4\n"
     "    print(apply2(lambda v: v * m, 7))\n"
     "    return 0\n",
     "a lambda has no environment to be given them"),
    # The same indirect call through TWO hops, so the answer cannot come from
    # the callee being inlined at the call site.
    ("a_function_argument_called_through_two_hops",
     "def g(x):\n"
     "    return x + 1\n"
     "def hop(f, v):\n"
     "    return f(v)\n"
     "def h(f, v):\n"
     "    return hop(f, v)\n"
     "def main():\n"
     "    print(h(g, 4))\n"
     "    return 0\n"),

    # ── generator EXPRESSIONS and comprehensions ──
    #
    # These are NOT generator functions: the parser holds a genexp as a
    # `Comprehension` with `kind == "generator"`, and both front ends build
    # `fire_compiler.py`'s `genexp_body` statement list for it. They are here as
    # the CONTROL for the generator-function refusal \u2014 the refusal offers a
    # genexp as the spelling that works, and these rows are what makes that
    # sentence true rather than merely plausible.
    ("generator_expression_over_a_range",
     "def main():\n"
     "    s = 0\n"
     "    for v in (i + 1 for i in range(4)):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n"),
    ("generator_expression_over_a_list_literal",
     "def main():\n"
     "    s = 0\n"
     "    for v in (i * 2 for i in [1, 2, 3]):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n"),
    ("generator_expression_with_a_condition",
     "def main():\n"
     "    s = 0\n"
     "    for v in (i * 2 for i in range(6) if i > 2):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n"),
    # A comprehension over a range, which is the plain integer case the
    # genexp rows are the closure-shaped spelling of.
    ("list_comprehension_over_a_range",
     "def main():\n"
     "    s = 0\n"
     "    for v in [i + 1 for i in range(4)]:\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n"),

    # ── decorators ──
    #
    # `@deco` where `deco` RETURNS ITS ARGUMENT, which is the only decoration
    # this path can be right about without applying anything (see the refusal
    # rows below for the ones it cannot) — and `model._decorator_is_identity`
    # proves it rather than guessing: the whole body is one `return f`.
    #
    # The row is here because a decorator handler that started REFUSING every
    # decorated def would take it with it, and that is what the measurement
    # rules out: 202 of this repository's 610 stdlib modules carry a decorated
    # `def`, and 2269 of the 2367 decorator spellings in them are `@inline` or
    # `@always_inline`, which select a lowering mode rather than wrapping a
    # function. So the refusal is asked only of a decorator this unit DEFINES
    # (measured population: zero stdlib modules — the one a line-scan matched
    # has its `@doc_hidden` inside a docstring) and is narrowed again to the
    # decorators that are not provably identity.
    ("a_decorator_that_returns_its_argument",
     "def deco(f):\n"
     "    return f\n"
     "@deco\n"
     "def g(x):\n"
     "    return x * 2\n"
     "def main():\n"
     "    print(g(3))\n"
     "    return 0\n"),
    # Stacked, bottom-up: CPython's order is `@a` over `@b` meaning `a(b(f))`,
    # so a stack applied top-down would still answer 6 here (both return `f`).
    ("two_decorators_that_both_return_their_argument",
     "def outer_deco(f):\n"
     "    return f\n"
     "def inner_deco(f):\n"
     "    return f\n"
     "@outer_deco\n"
     "@inner_deco\n"
     "def g(x):\n"
     "    return x * 2\n"
     "def main():\n"
     "    print(g(3))\n"
     "    return 0\n"),
]

# ── REFUSAL cases: (name, source, needles) ────────────────────────────────
#
# `needles` are substrings of the message; the assertion is that BOTH backends
# refuse and that every needle is present. The cross-backend check is that the
# two messages are the same once the ARCHITECTURE NAME is normalized away, and
# that normalization is not leniency for its own sake: this tree's convention
# puts the target in the sentence ("… on the formal arm64 path"), so a raw
# byte-comparison would fail every refusal here and prove nothing. Normalizing
# only the architecture still catches the divergences that are real — which is
# how `yield from` was two different sentences ("unsupported expression
# YieldFromExpr" on arm64, the same clause plus "the integer/boolean surface is
# lowered, container and string values are not" on x86-64) and how a case that
# pinned one needle per backend would have passed.
#
# The naming is the requirement this area is held to: a reader told "'v' has no
# home" has nothing to act on, and a reader told "`sorted` with `key=` needs a
# callable this path has no representation for" has the next edit.
REFUSALS = [
    # ── generator functions: refused, named, and identical on both ──
    ("a_generator_function_whose_value_is_iterated",
     "def gen():\n"
     "    yield 1\n"
     "    yield 2\n"
     "def main():\n"
     "    s = 0\n"
     "    for v in gen():\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["GENERATOR FUNCTION", "`yield`"]),
    # The same construct with the value READ rather than iterated, which is the
    # shape that printed a number CPython cannot print (5) instead of faulting.
    ("a_generator_function_whose_value_is_read",
     "def gen():\n"
     "    yield 1\n"
     "    return 5\n"
     "def main():\n"
     "    print(gen())\n"
     "    return 0\n",
     ["GENERATOR FUNCTION"]),
    # A generator nobody calls still refuses, because the refusal is about the
    # FUNCTION's calling convention and not about one call site: a build that
    # accepted it would leave the decorator-shaped trap one edit away.
    ("a_generator_function_that_is_never_called",
     "def gen():\n"
     "    yield 1\n"
     "def main():\n"
     "    print(7)\n"
     "    return 0\n",
     ["GENERATOR FUNCTION"]),
    # `yield from` is the same construct with a second spelling, and it is here
    # because it WAS two different messages \u2014 "unsupported expression
    # YieldFromExpr" on arm64 and a different sentence on x86-64 \u2014 so a case
    # that pins one needle per backend would have passed.
    ("yield_from_delegates_to_another_generator",
     "def inner():\n"
     "    yield 1\n"
     "def outer():\n"
     "    yield from inner()\n"
     "def main():\n"
     "    s = 0\n"
     "    for v in outer():\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["GENERATOR FUNCTION", "`inner`", "`outer`"]),
    # A `yield` in a LOOP body, which is the shape every real generator uses and
    # which reached the emitter as an expression statement exactly like the
    # straight-line one.
    ("a_generator_function_yielding_from_a_loop",
     "def gen():\n"
     "    var i = 0\n"
     "    while i < 3:\n"
     "        yield i\n"
     "        i = i + 1\n"
     "def main():\n"
     "    s = 0\n"
     "    for v in gen():\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["GENERATOR FUNCTION"]),
    # A NESTED generator: the refusal names the function that OWNS the `yield`,
    # not the one it is nested in, because that is the function whose calling
    # convention is at issue.
    ("a_nested_generator_function",
     "def main():\n"
     "    def gen():\n"
     "        yield 1\n"
     "    print(7)\n"
     "    return 0\n",
     ["GENERATOR FUNCTION", "`gen`"]),

    # ── a closure that is not called where it was defined ──
    #
    # The capture ABI is a CALL-SITE rewrite, so it needs a call site in the
    # scope that defines the closure. Handing the closure back to the caller
    # needs a VALUE, and a value is one word while a function is a code address.
    # These three refusals are the wall behind every row above.
    # `a(5)` reads the RETURNED value of `make`, and the refusal a reader has to
    # act on is about the call through a value, not about `a`. Binding `a` and
    # calling it directly is the same program and reaches the construct's own
    # refusal instead of the print-argument one.
    ("a_nested_def_handed_back_to_its_caller",
     "def make(n):\n"
     "    def add(x):\n"
     "        return x + n\n"
     "    return add\n"
     "def main():\n"
     "    a = make(10)\n"
     "    r = a(5)\n"
     "    print(r)\n"
     "    return 0\n",
     # The refusal names the NAME AT THE POINT THE CLOSURE IS HANDED BACK —
     # `make`'s `return add` is the statement that needs a value, and `a(5)` is
     # only where the missing value shows up. So the needle is the quoted
     # spelling `'add'`, which is how `model.unresolved_name_refusal` prints it,
     # and the enclosing function's name.
     #
     # That this is `unresolved_name_refusal` and NOT the more specific
     # `model.function_value_refusal` is a real gap in the diagnostic and is
     # filed as `bugs/FORMAL_a_nested_def_handed_back_names_the_allocator.md`
     # rather than papered over here: the better sentence exists in the model and
     # this call site does not reach it, because a nested def is RENAMED to its
     # lifted symbol by `_flatten_closures` before anything asks whether the name
     # is a function.
     ["'add'", "make"]),
    ("a_nested_def_without_a_capture_handed_back",
     "def make():\n"
     "    def inner(x):\n"
     "        return x + 1\n"
     "    return inner\n"
     "def main():\n"
     "    f = make()\n"
     "    r = f(1)\n"
     "    print(r)\n"
     "    return 0\n",
     ["'inner'", "make"]),
    # A lambda that CAPTURES, handed back as the function's return value — the
    # closure-as-a-value question again, and the capture is what the refusal
    # names rather than the returning.
    ("a_lambda_handed_back_from_a_function",
     "def mk(m):\n"
     "    return lambda v: v + m\n"
     "def main():\n"
     "    f = mk(4)\n"
     "    print(f(6))\n"
     "    return 0\n",
     ["`m`", "a lambda has no environment to be given them"]),

    # ── a nested `def` capturing a LOOP variable ──
    #
    # CPython answers 3 (`get()` is called inside the iteration that defined it,
    # so it reads the current `i`) and the by-value capture ABI answers exactly
    # this for an ordinary local — so the shape "should" work and does not. The
    # root cause is one arm missing from a loop in
    # `mojo/middle/closures.py::discover_closures`: a `ForStmt` target never
    # enters `enriched_scope`, which is the map every inferred capture is
    # filtered against, so the capture is dropped and the lifted body reads a
    # name with no home.
    #
    # The needle is that name in the ALLOCATOR's spelling, which is not the right
    # sentence — it is a fact about the closure pass, not about the register
    # allocator — and pinning it deliberately: the row fails loudly the moment
    # the pass learns the loop target, so whoever fixes it moves this row into the
    # ANSWERED group instead of re-deriving what it should say. Filed as
    # `bugs/FORMAL_a_nested_def_capturing_a_for_target_is_not_a_capture.md`, which
    # also records why the fix was not landed in the round that measured it (the
    # file is shared with the compiled backend and owes a full gate) and the
    # late-binding hazard a by-value capture would introduce for the STORED
    # spelling of the same construct.
    ("a_nested_def_capturing_a_loop_variable",
     "def main():\n"
     "    s = 0\n"
     "    for i in range(3):\n"
     "        def get():\n"
     "            return i\n"
     "        s = s + get()\n"
     "    print(s)\n"
     "    return 0\n",
     ["'i'", "main_get"]),

    # ── a callable stored in a container and read back ──
    # The result is BOUND before it is printed, and that is not incidental:
    # `print(fs[1]())` reaches a different refusal first \u2014 `print()` cannot
    # tell whether a `CallExpr` is a string or a number \u2014 which is a
    # limitation of `print` about its own ARGUMENT and names neither the
    # container nor the callable. Both sources are the same program; the
    # refusal a reader has to act on is the one about the construct.
    ("a_lambda_stored_in_a_list_and_called",
     "def main():\n"
     "    fs = [lambda: 1, lambda: 2]\n"
     "    r = fs[1]()\n"
     "    print(r)\n"
     "    return 0\n",
     ["`fs`"]),
    ("a_lambda_stored_in_a_dict_and_called",
     "def main():\n"
     "    d = {\"a\": lambda: 5}\n"
     "    r = d[\"a\"]()\n"
     "    print(r)\n"
     "    return 0\n",
     ["`d`"]),

    # ── `nonlocal` ──
    ("nonlocal_writes_to_a_captured_cell",
     "def make():\n"
     "    c = 0\n"
     "    def bump():\n"
     "        nonlocal c\n"
     "        c = c + 1\n"
     "        return c\n"
     "    bump()\n"
     "    return c\n"
     "def main():\n"
     "    print(make())\n"
     "    return 0\n",
     ["nonlocal"]),

    # ── higher-order builtins ──
    #
    # `sorted`, `map`, `filter`, `sum` are in `formal/model.py`'s
    # `NOT_LOWERED_BUILTINS`, which is the ONE table of what this path does not
    # implement. They are refused BY NAME: the refusal says which builtin and
    # why, rather than reaching the link audit's "the image would bind 1
    # symbol(s) that nothing provides: sorted", which names the SYMPTOM and
    # arrives after the image is built.
    # The result is READ BY A LOOP rather than subscripted, because a
    # subscript of a value whose origin this path cannot see reaches `print`'s
    # own "cannot tell whether a SubscriptExpr is a string or a number" first
    # — a limitation of `print` about its argument that names neither `sorted`
    # nor the lambda. Same program; the refusal a reader has to act on is the
    # one about the construct.
    ("sorted_with_a_key_lambda",
     "def main():\n"
     "    ys = sorted([3, 1, 2], key=lambda v: 0 - v)\n"
     "    s = 0\n"
     "    for y in ys:\n"
     "        s = s + y\n"
     "    print(s)\n"
     "    return 0\n",
     ["sorted"]),
    # Plain `sorted`, with no key at all \u2014 so the row cannot be satisfied by
    # anything about the CALLABLE half. This is the plainest instance of a name
    # in `model.NOT_LOWERED_BUILTINS` being refused, and it is refused BY THE
    # LINK AUDIT after the image is built rather than by name before it.
    ("sorted_without_a_key",
     "def main():\n"
     "    ys = sorted([3, 1, 2])\n"
     "    s = 0\n"
     "    for y in ys:\n"
     "        s = s + y\n"
     "    print(s)\n"
     "    return 0\n",
     ["sorted"]),
    ("map_over_a_literal_with_a_lambda",
     "def main():\n"
     "    s = 0\n"
     "    for v in map(lambda v: v * 2, [1, 2, 3]):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["map"]),
    ("map_over_a_literal_with_a_function",
     "def dbl(v):\n"
     "    return v * 2\n"
     "def main():\n"
     "    s = 0\n"
     "    for v in map(dbl, [1, 2, 3]):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["map"]),
    ("filter_over_a_literal",
     "def main():\n"
     "    s = 0\n"
     "    for v in filter(lambda v: v > 1, [1, 2, 3]):\n"
     "        s = s + v\n"
     "    print(s)\n"
     "    return 0\n",
     ["filter"]),
    ("sum_over_a_literal",
     "def main():\n"
     "    print(sum([1, 2, 3]))\n"
     "    return 0\n",
     ["sum"]),
    ("functools_partial_of_a_function",
     "import functools\n"
     "def add(a, b):\n"
     "    return a + b\n"
     "def main():\n"
     "    p = functools.partial(add, 2)\n"
     "    print(p(3))\n"
     "    return 0\n",
     ["functools"]),

    # ── the late-binding trap ──
    #
    # Every element of `fs` closes over the SAME loop cell in CPython, so all
    # three print 2. This is the construct where a closure ABI that binds by
    # value at lift time answers 0, 1, 2 instead \u2014 three different wrong
    # numbers rather than one, which is why it is worth a case of its own rather
    # than a footnote.
    ("a_lambda_closing_over_a_loop_variable_binds_late",
     "def main():\n"
     "    fs = []\n"
     "    for i in range(3):\n"
     "        fs.append(lambda: i)\n"
     "    print(fs[0](), fs[1](), fs[2]())\n"
     "    return 0\n",
     ["`i`", "a lambda has no environment to be given them"]),
    # The early-binding spelling: `lambda k=i: k` copies the value at each
    # iteration, so CPython answers 0 1 2. Same closure, opposite answer, and a
    # case that did not carry both would let one of them be "fixed" into the
    # other.
    ("a_lambda_default_argument_binds_early",
     "def main():\n"
     "    fs = []\n"
     "    for i in range(3):\n"
     "        fs.append(lambda k=i: k)\n"
     "    print(fs[0](), fs[1](), fs[2]())\n"
     "    return 0\n",
     ["`i`", "a lambda has no environment to be given them"]),

    # ── decorators that REPLACE the function they decorate ──
    #
    # The sharpest row in this file. `deco` prints, and its print never ran: the
    # decorator is not applied, `g` is the UNDECORATED body, and the program
    # exits 0 with 6 where CPython answers 103. A statement with an observable
    # effect that is silently absent is the failure class this whole backend's
    # refusals exist to prevent, so it is refused rather than run undecorated.
    ("a_decorator_that_replaces_the_function_it_decorates",
     "def other(x):\n"
     "    return x + 100\n"
     "def deco(f):\n"
     "    print(\"deco ran\")\n"
     "    return other\n"
     "@deco\n"
     "def g(x):\n"
     "    return x * 2\n"
     "def main():\n"
     "    print(g(3))\n"
     "    return 0\n",
     ["decorat", "deco"]),
    # A decorator that WRAPS, which is the shape the task names: `wrap` is a
    # nested def handed back to its caller, so this is refused for the closure
    # reason as well and the message has to survive both.
    ("a_decorator_that_wraps_the_function",
     "def deco(f):\n"
     "    def wrap(x):\n"
     "        return f(x) + 1\n"
     "    return wrap\n"
     "@deco\n"
     "def g(x):\n"
     "    return x * 2\n"
     "def main():\n"
     "    print(g(3))\n"
     "    return 0\n",
     ["deco", "wrap"]),
]


def build_formal(src, out, backend, tmpdir):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir, name):
    """CPython's stdout for `source` with `main()` appended."""
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(source + "\nmain()\n")
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=tmpdir)
    if p.returncode != 0:
        return None, (f"CPython itself failed on this source, so it cannot be "
                      f"the oracle: exit {p.returncode}: "
                      f"{p.stderr.strip()[-300:]}")
    return p.stdout, ""


def run_answered(name, source, tmpdir, verbose, needle=None):
    if needle is not None:
        return run_answered_as_refusal(name, source, [needle], tmpdir, verbose)
    want, why = run_cpython(source, tmpdir, name)
    if want is None:
        return False, why
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)

    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend, tmpdir)
        if rc != 0:
            return False, (f"--backend={backend} refused a construct CPython runs: "
                           f"{text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success but wrote no binary"
        try:
            run = subprocess.run([out], capture_output=True, text=True,
                                 timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"--backend={backend} image hung (a {RUN_TIMEOUT}s timeout)"
        if run.returncode != 0:
            return False, (f"--backend={backend} exited {run.returncode} "
                           f"(CPython exits 0); stderr: {run.stderr.strip()[:160]}")
        if run.stdout != want:
            return False, (f"--backend={backend} printed {run.stdout!r} where "
                           f"CPython prints {want!r}")
        if verbose:
            print(f"      {backend}: {run.stdout!r} == CPython")
    return True, ""


def normalize_arch(message):
    """The message with the TARGET's name folded out, for the cross-backend check.

    FOUR spellings, because the tree uses four and they are not
    interchangeable: the arm64 backend's messages say "the formal arm64 path"
    and the x86-64 one's say "the formal x86-64 path" \u2014 underscored in some
    sentences and HYPHENATED in others, and `fire.py`'s own `--backend` value is
    `x86_64`. Folding all of them means the comparison is about the DECISION
    and its wording, which is the thing that must not differ between two
    machines running one language; folding only one pair of them would fail
    every refusal whose message names the target and pass every divergence that
    does not, which is the shape of a check that proves nothing.
    """
    for spelling in ("arm64", "aarch64", "x86_64", "x86-64"):
        message = message.replace(spelling, "ARCH")
    return message


def run_answered_as_refusal(name, source, needles, tmpdir, verbose):
    """The variant above: CPython raises on this program, so the formal refusal
    is the answer and the assertion is that it names why.

    `run_refusal` already is exactly that assertion; the separate name exists so
    the CASES table can carry the row where it belongs (with the other answered
    cases, and the comment that says what would have to change for it to move)
    without this file growing a second table of refusals to keep in step.
    """
    return run_refusal(name, source, needles, tmpdir, verbose)


def run_refusal(name, source, needles, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    said = {}
    for backend in ("arm64", "x86_64"):
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend, tmpdir)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation on this path; the binary that runs is "
                           f"the real answer here, and it is not the program in "
                           f"the file")
        said[backend] = text.strip()
    if normalize_arch(said["arm64"]) != normalize_arch(said["x86_64"]):
        return False, (f"the two backends refused DIFFERENTLY about one source "
                       f"file:\n    arm64: {said['arm64'][-300:]}\n"
                       f"    x86_64: {said['x86_64'][-300:]}")
    text = said["arm64"]
    missing = [n for n in needles if n not in text]
    if missing:
        return False, (f"the refusal does not name {missing} — a reader told "
                       f"only this has nothing to act on: {text[-300:]}")
    if verbose:
        print(f"      refused identically on both, naming {needles}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the formal images this suite RUNS are the host's "
              f"architecture; host is {platform.machine()}")
        return 0

    wanted = set(args.cases)
    passed, failed = 0, 0
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, ".tmp")) as td:
        for entry in CASES:
            name, source = entry[0], entry[1]
            source_or_needle = entry[2] if len(entry) > 2 else None
            if wanted and name not in wanted:
                continue
            if args.verbose:
                print(f"  {name}")
            try:
                ok, detail = run_answered(name, source, td, args.verbose,
                                          needle=source_or_needle)
            except Exception as e:                       # report, never mask
                ok, detail = False, f"{type(e).__name__}: {e}"
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")
        for name, source, needles in REFUSALS:
            if wanted and name not in wanted:
                continue
            if args.verbose:
                print(f"  {name}")
            try:
                ok, detail = run_refusal(name, source, needles, td, args.verbose)
            except Exception as e:                       # report, never mask
                ok, detail = False, f"{type(e).__name__}: {e}"
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    print(f"\nformal closures: PASS={passed} FAIL={failed} "
          f"({len(CASES)} answered, {len(REFUSALS)} refused)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())