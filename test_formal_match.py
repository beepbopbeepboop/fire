#!/usr/bin/env python3
"""`match`/`case` on the formal backends, with CPython as the oracle.

**What this file is.** The oracle table for pattern matching on the two
formal backends (`--backend=arm64`, `--backend=x86_64`). Every row is a whole
program; both architectures BUILD it and RUN the image, and the image's stdout
and exit status are compared against an oracle computed by running the SAME
text through this process's own Python. A row is therefore a claim about what
the program means, not about a hand-copied number.

**The oracle each row uses, and why a row needs one.** This compiler does not
implement PEP 634. `fire_compiler.py`'s `MatchStmt` and `myinterpreter.py`'s
`execute_MatchStmt` define `match` as SWITCH-STYLE equality dispatch: each
`case`'s pattern is evaluated as an ordinary expression and compared with `==`
against the subject, with ONE exception — a bare name that is not already bound
is a genuine capture that always matches and binds the subject. That is a
DELIBERATE divergence from CPython (`fire_compiler.py`'s own docstring), so
this file does not pretend the two agree everywhere:

  * `oracle="cpython"` — the pattern is one CPython reads the same way this
    compiler does (a literal, `case _:`, an unbound-name capture, a dotted
    value pattern). CPython's own output is the answer.
  * `oracle="frontend"` — the pattern is one CPython reads DIFFERENTLY, and the
    oracle is `python3 fire.py run` (this compiler's reference interpreter,
    `myinterpreter.py`). Every such row carries the CPython reading in its
    comment, so the divergence is written down rather than assumed.

**The three shapes are not "unsupported" — they are REFUSED, by name.**
`case [a, b]:`, `case {"k": v}:`, `case Point(x=0):`, `case 1 | 2:` and
`case [a] as whole:` all PARSE, into an ordinary `ListExpr` / `DictExpr` /
`CallExpr` / `BinaryOp`. So a backend that lowered a pattern as "evaluate it and
compare with `==`" would answer them — and be wrong, silently, in the exact way
that reads as a working feature: `case 1 | 2:` computes `1 | 2 == 3` and matches
the subject against 3, and `case [a, b]:` compares the subject to a list literal
whose `a` and `b` are ordinary reads rather than bindings. This compiler's own
free-variable analysis already treats all five as BINDING structural patterns
(`test_new_syntax_parsing.py::test_match`'s `match_seq_pattern_binds`,
`match_dict_pattern_binds`, `match_or_of_literals_has_no_names`,
`match_as_binds_both_and_guard_is_a_use`), so the formal path refusing them by
name is the two frontends agreeing, not the formal path being narrow. Those rows
carry `("refuse", "<substring>")` and the substring is the CONSTRUCT.

Run:  python3 test_formal_match.py [-v] [-k SUBSTRING] [--only-row N] [--list]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")


def prog(body):
    """A whole `main` whose body is `body` (unindented source lines)."""
    lines = ["def main():"] + ["    " + l for l in body.split("\n")] + \
            ["    return 0"]
    return "\n".join(lines) + "\n"


def mod_prog(body):
    """`body` at MODULE level — for the rows whose construct is a declaration.

    A `struct` inside a function body is not a thing this compiler has: the
    declaration is lifted by `formal/build.py::_struct_methods` from the
    module's own statement list, so a `struct` nested in `main` reaches codegen
    with a `self` that no frame declares. That is a pre-existing limit of
    declarations and not of `match`, and the rows that need a declaration say so
    by using this helper rather than by being refused.
    """
    return body + "\n"


# ── the table ─────────────────────────────────────────────────────────────────
#
# (name, body, expectation, shape).
#
#   `shape` is "in-main" (the default: the body is wrapped in `def main()`) or
#   "module" (the body IS the file's top level, for the rows whose construct is
#   a declaration). It is spelled per row rather than sniffed from the text
#   because the distinction is the difference between a row that measures
#   `match` and a row that measures something else entirely.
#
#   The expectation is one of the three shapes above.
#
#   ("cpython",)   — build+run on both backends; identical stdout AND exit
#                    status to `python3 <program>` on the same text.
#   ("frontend",)  — as above, but the oracle is `python3 fire.py run`.
#   ("refuse", s)  — the BUILD refuses on both backends and the message
#                    contains `s`. `s` names the CONSTRUCT, not the AST node:
#                    a refusal that says only "MatchStmt" leaves the reader to
#                    work out which of the pattern languages they wrote.
#
# A per-backend dict is accepted for `("refuse", …)` and for the two value
# shapes, because "the same verdict on both machines" is the property this file
# exists to keep and forcing a disagreement into one shape would hide it.

ROWS = [
    # ── literal patterns: the shape CPython and this compiler read alike ────
    ("lit_one", "n = 1\n"
     "match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case 2:\n"
     "        print('two')\n"
     "print('after')", ("cpython",)),
    ("lit_no_match_falls_through", "n = 5\n"
     "match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case 2:\n"
     "        print('two')\n"
     "print('after')", ("cpython",)),
    # A negative literal. `case -3:` is a literal pattern in CPython's own
    # grammar (the unary minus is part of the literal, not an expression), and
    # it arrives here as a `UnaryOp('-', IntLiteral)` — the one operator this
    # path classifies as a VALUE rather than as a structural pattern, because
    # `0 - 1` and `1 | 2` are both `BinaryOp`s and only one of them is an
    # arithmetic spelling of a constant. Writing it `case 0 - 3:` instead is a
    # SyntaxError in CPython and an arithmetic comparison here, which is why
    # the row uses the spelling both compilers read.
    ("lit_negative", "n = 0 - 3\n"
     "match n:\n"
     "    case -1:\n"
     "        print('one')\n"
     "    case -3:\n"
     "        print('three')\n"
     "print('after')", ("cpython",)),
    ("lit_string", "s = 'bb'\n"
     "match s:\n"
     "    case 'aa':\n"
     "        print('first')\n"
     "    case 'bb':\n"
     "        print('second')\n"
     "print('after')", ("cpython",)),
    # A string pattern is a `strcmp` and the two architectures reach it
    # differently (a word compare vs a call), so this row exists on both.
    ("lit_string_no_match", "s = 'zz'\n"
     "match s:\n"
     "    case 'aa':\n"
     "        print('first')\n"
     "print('after')", ("cpython",)),
    # The subject is an EXPRESSION and CPython evaluates it exactly once. A
    # lowering that re-reads it per pattern calls it once per pattern, and a
    # lowering that binds it to a temp must bind it before the first pattern
    # runs — this row prints from inside the subject to make the count visible.
    ("subject_evaluated_once", "def s():\n"
     "    print('subject')\n"
     "    return 2\n"
     "match s():\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case 2:\n"
     "        print('two')\n"
     "    case 3:\n"
     "        print('three')\n"
     "print('after')", ("cpython",)),

    # ── `case _:` and the capture ──────────────────────────────────────────
    ("wildcard", "n = 7\n"
     "match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("cpython",)),
    # `case v:` with `v` NOT bound anywhere is the capture: it always matches
    # and binds the subject, which is PEP 634's rule and the one CPython
    # applies, so the oracle is CPython's.
    ("capture_binds_subject", "n = 42\n"
     "match n:\n"
     "    case v:\n"
     "        print(v)\n"
     "        print(v + 1)\n"
     "print('after')", ("cpython",)),
    ("capture_with_guard_true", "n = 5\n"
     "match n:\n"
     "    case v if v > 3:\n"
     "        print('big')\n"
     "        print(v)\n"
     "    case _:\n"
     "        print('small')\n"
     "print('after')", ("cpython",)),
    # The guard is the reason the capture exists at all (`fire_compiler.py`'s
    # `MatchStmt` docstring), and a guard that FAILS must fall to the NEXT
    # case rather than to the end of the match.
    ("capture_with_guard_false_falls_to_next", "n = 1\n"
     "match n:\n"
     "    case v if v > 3:\n"
     "        print('big')\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("cpython",)),
    # The capture binds BEFORE the guard is tested, and CPython keeps the
    # binding when the guard fails. This row pins that: `v` is bound by the
    # failing guard, so the arm AFTER it reads a name that only exists because
    # the guard said no. It is the one place the two orderings differ — a
    # lowering that binds inside the arm's body would leave `v` unbound here
    # and the read would be refused.
    ("capture_survives_a_failed_guard", "n = 1\n"
     "match n:\n"
     "    case v if v > 3:\n"
     "        print('big')\n"
     "    case _:\n"
     "        print(v)\n"
     "print('after')", ("cpython",)),
    # A capture is a normal local afterwards: the arm's body can assign it and
    # the statement after the match reads the assigned value, which is the
    # read-before-store question the arm has to answer for itself.
    ("capture_assigned_in_the_arm", "n = 1\n"
     "match n:\n"
     "    case v:\n"
     "        v = v + 10\n"
     "        print(v)\n"
     "print(v)", ("cpython",)),

    # ── the or-pattern, and the spelling this compiler uses for it ─────────
    #
    # `case A, B:` is THIS compiler's or-pattern (`fire_compiler.py`'s
    # `MatchCase.patterns` docstring: "comma-separated is an 'or'"), and CPython
    # reads the same text as a two-ELEMENT SEQUENCE pattern — so for an `int`
    # subject CPython raises `TypeError: called `match` on int, should have
    # been a sequence`. The oracle is therefore this compiler's reference
    # interpreter and the CPython reading is written down beside it.
    ("or_comma_first", "n = 2\n"
     "match n:\n"
     "    case 1, 2:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),
    ("or_comma_second", "n = 5\n"
     "match n:\n"
     "    case 1, 2, 3:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),
    ("or_comma_none_match", "n = 9\n"
     "match n:\n"
     "    case 1, 2:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),
    # CPython on this exact text:
    #   TypeError: called `match` on int, should have been a sequence
    #
    # `TBL` is a list the patterns index. A CALL in a pattern is
    # not available as a way to observe evaluation order: `case p(1):` parses
    # as a plain call and is refused as a class pattern
    # (`class_pattern_is_refused`), which is deliberate — PEP 634 reads a call
    # as a type test and this compiler's own free-variable analysis agrees. A
    # subscript is the shape both compilers read as a VALUE, so it is what these
    # two rows use to observe the order instead.
    #
    # The order is observable, so it is a row: the patterns are evaluated left
    # to right and stop at the first that matches.
    ("or_comma_second_pattern_matches", "TBL = [10, 20]\n"
     "n = 20\n"
     "match n:\n"
     "    case TBL[0], TBL[1]:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),
    # …and the sharpest form of the same question. `TBL[5]` is one past the end
    # of a two-element list: read on its own it TRAPS — `print(TBL[5])` builds
    # and exits 1 on both architectures (measured) — so a lowering that
    # evaluated every pattern in the list before combining the answers would
    # exit 1 here. The reference interpreter stops at the first pattern that
    # matches, and so does the `or` chain both emitters already lower, so this
    # image prints `low` and exits 0. CPython cannot run this text at all (it
    # reads `TBL[0], TBL[5]` as a two-element SEQUENCE pattern and matching an
    # `int` against it raises `TypeError`), hence the frontend oracle.
    ("or_comma_short_circuits_before_a_bad_read", "TBL = [10, 20]\n"
     "n = 10\n"
     "match n:\n"
     "    case TBL[0], TBL[5]:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),

    # ── a bound bare name is a VALUE comparison, and that is a divergence ───
    #
    # `case K:` where `K` is ALREADY BOUND is the shape every real use in this
    # tree wants (`fire_compiler.py`'s `MatchStmt` docstring spells out
    # `case NODE_FUNCTION_DECL:`), and CPython reads it as a CAPTURE that always
    # matches. So the two disagree BY DESIGN and these rows pin the compiler's
    # reading rather than CPython's. On each of these texts CPython prints
    # `low` then `after` whatever `K` is.
    #
    # The three rows are the three places a name can be bound, and they are
    # three rows because the compile-time rule that decides "capture or
    # compare" has to answer all three the same way the interpreter's
    # `scope.has` does — and that is what `formal/build.py::_match_scope_names`
    # is for. `K = 2` at the MODULE's top level is the folded-constant case;
    # the same assignment inside the matching function is the ordinary local;
    # and the same assignment in an ENCLOSING function is the closure case,
    # where the reference interpreter's scope chain finds the name and this
    # path reads it through the lifted by-value capture.
    ("bound_module_constant_is_a_value_comparison", "K = 2\n"
     "\n"
     "def main():\n"
     "    n = 5\n"
     "    match n:\n"
     "        case K:\n"
     "            print('low')\n"
     "        case _:\n"
     "            print('rest')\n"
     "    print('after')\n"
     "    return 0\n", ("frontend",), "module"),
    ("bound_local_is_a_value_comparison", "K = 2\n"
     "n = 5\n"
     "match n:\n"
     "    case K:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("frontend",)),
    ("bound_local_of_an_enclosing_function_is_a_value_comparison", "K = 2\n"
     "def f(n):\n"
     "    match n:\n"
     "        case K:\n"
     "            print('low')\n"
     "        case _:\n"
     "            print('rest')\n"
     "f(5)\n"
     "print('after')", ("frontend",)),
    # The DOTTED spelling is the one PEP 634 also calls a value pattern: a
    # dotted name compares the value it denotes, which is exactly this
    # compiler's equality dispatch. `q.b` is a field read of a two-field struct
    # — a frame slot — so it is a value with no allocation and no storage
    # question, which is what makes it usable as a pattern here. (A dotted name
    # rooted at an IMPORTED module is not: `case os.sep:` reaches
    # `os.sep`, a module value, and this path has nowhere to keep one —
    # `bugs/FORMAL_module_state_no_storage.md`. That is a refusal about module
    # state and not about `match`, so it is not a row here.)
    # CPython equivalent: the same program with `class Q` and `q.b` — the same
    # answer, `b`, because a dotted pattern is a value pattern in both.
    ("dotted_value_pattern", "struct Q:\n"
     "    a: Int32\n"
     "    b: Int32\n"
     "\n"
     "def main():\n"
     "    q = Q(5, 7)\n"
     "    n = 7\n"
     "    match n:\n"
     "        case q.b:\n"
     "            print('seven')\n"
     "        case _:\n"
     "            print('rest')\n"
     "    print('after')\n"
     "    return 0\n", ("frontend",), "module"),

    # ── control flow: an arm's body is ordinary control flow ───────────────
    # Every one of these is a statement the emitter already knows, reached
    # through a `match` — so they are the rows that would break if the
    # lowering built a fresh frame per arm instead of splicing the body in.
    ("arm_return_exits_the_function", "def f(n):\n"
     "    match n:\n"
     "        case 1:\n"
     "            print('one')\n"
     "            return 10\n"
     "        case _:\n"
     "            print('rest')\n"
     "    print('after')\n"
     "    return 20\n"
     "print(f(1))\n"
     "print(f(2))\n"
     "print('done')", ("cpython",)),
    ("arm_break_and_continue_in_a_loop", "t = 0\n"
     "for i in range(0, 5):\n"
     "    match i:\n"
     "        case 1:\n"
     "            continue\n"
     "        case 3:\n"
     "            break\n"
     "        case _:\n"
     "            t = t + i\n"
     "print(t)", ("cpython",)),
    ("match_inside_a_while", "i = 0\n"
     "t = 0\n"
     "while i < 5:\n"
     "    match i:\n"
     "        case 4:\n"
     "            t = t + 100\n"
     "            break\n"
     "        case _:\n"
     "            t = t + i\n"
     "    i = i + 1\n"
     "print(t)", ("cpython",)),
    ("match_inside_an_if_arm", "n = 3\n"
     "if n > 1:\n"
     "    match n:\n"
     "        case 3:\n"
     "            print('three')\n"
     "        case _:\n"
     "            print('rest')\n"
     "else:\n"
     "    print('small')\n"
     "print('after')", ("cpython",)),
    # An `elif` after a `match` in the same block: `IfStmt.elifs` is a list of
    # TUPLES and is the one statement container a `list`-shaped walk misses, so
    # a match under an `elif` is the row that finds a rewrite which only
    # descends `then_body`/`else_body`.
    ("match_under_an_elif", "n = 2\n"
     "if n > 9:\n"
     "    print('big')\n"
     "elif n > 1:\n"
     "    match n:\n"
     "        case 2:\n"
     "            print('two')\n"
     "        case _:\n"
     "            print('rest')\n"
     "else:\n"
     "    print('small')\n"
     "print('after')", ("cpython",)),
    # A `match` whose arm bodies assign, and whose arms are reached from
    # several directions, is the read-before-store question: the capture is a
    # binding that exists only on the arm that took it.
    ("capture_then_read_after_the_match", "n = 1\n"
     "match n:\n"
     "    case 9:\n"
     "        print('nine')\n"
     "    case v:\n"
     "        print('v')\n"
     "print('after')", ("cpython",)),

    # ── two `match` statements, and a `match` over a loop's variable ──────
    ("two_matches_in_one_function", "n = 2\n"
     "match n:\n"
     "    case 1:\n"
     "        print('a1')\n"
     "    case _:\n"
     "        print('a2')\n"
     "match n:\n"
     "    case 2:\n"
     "        print('b2')\n"
     "    case _:\n"
     "        print('b1')\n"
     "print('after')", ("cpython",)),
    ("match_in_a_loop_over_a_list", "t = 0\n"
     "for v in [1, 2, 3]:\n"
     "    match v:\n"
     "        case 2:\n"
     "            t = t + 20\n"
     "        case _:\n"
     "            t = t + v\n"
     "print(t)", ("cpython",)),

    # ── Mojo syntax: the oracle is this compiler's interpreter ─────────────
    #
    # These rows use a `struct`, which CPython cannot parse, so the oracle is
    # `python3 fire.py run`. The CPython equivalent is one class + one method
    # and it is written out in the row's comment, because "the oracle is the
    # reference interpreter" is only honest if the reader can check what it
    # says.
    #
    # `struct P:` with a method that matches on a field: the method is LIFTED
    # out of the struct by `formal/build.py::_struct_methods`, so its body is
    # a function body of its own by the time anything walks it.
    # CPython equivalent: a class P with __init__ and kind(), kind() matching
    # on self.x — same answers (10, 20, 30).
    ("match_in_a_struct_method", "struct P:\n"
     "    x: Int32\n"
     "    y: Int32\n"
     "\n"
     "    fn kind(self) -> Int32:\n"
     "        match self.x:\n"
     "            case 0:\n"
     "                return 10\n"
     "            case 1:\n"
     "                return 20\n"
     "        return 30\n"
     "\n"
     "def main():\n"
     "    p = P(0, 2)\n"
     "    print(p.kind())\n"
     "    q = P(1, 2)\n"
     "    print(q.kind())\n"
     "    r = P(5, 2)\n"
     "    print(r.kind())\n"
     "    return 0\n", ("frontend",), "module"),
    # A `match` inside a NESTED `def`, which `formal/build.py::_flatten_closures`
    # turns into a lifted function with by-value captures. The match is in the
    # lifted body, so a rewrite that ran only over the module's own functions
    # would leave it in the lifted one and the lifted one would refuse.
    # CPython equivalent: the same nested def, called — same answers (5, 6).
    ("match_in_a_nested_def", "def outer(n: Int) -> Int:\n"
     "    def inner(k: Int) -> Int:\n"
     "        match k:\n"
     "            case 0:\n"
     "                return 5\n"
     "            case _:\n"
     "                return 6\n"
     "        return 7\n"
     "    return inner(n)\n"
     "\n"
     "print(outer(0))\n"
     "print(outer(3))", ("frontend",)),
    # A `match` in a module-level body (not inside a `def`). The formal front
    # end compiles the module body as one synthetic entry function
    # (`formal/build.py::_module_body_function`), so this is a `match` in an
    # ordinary function body by the time anything walks it — and it is a row
    # because the module body's `bound` set starts from the module's names
    # rather than from a parameter list, which is the one place the two starts
    # differ.
    ("match_at_module_level", "n = 2\n"
     "match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case 2:\n"
     "        print('two')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')\n"
     "\n"
     "def main():\n"
     "    return 0\n", ("cpython",), "module"),
    # `__match`, the Mojo layout: the cases at the SAME indent as the keyword.
    # `fire_compiler.py::_parse_match` accepts both layouts and tells them apart
    # by whether an INDENT follows the header, so they produce the same
    # `MatchStmt` — which is the point of the row: a lowering that walked the
    # arms positionally, or that assumed a body per `case`, would work for one
    # layout and not the other. CPython cannot parse this text at all (the
    # flat layout is a dedent out of the `match` block), so the oracle is this
    # compiler's own interpreter.
    ("mojo_flat_case_layout", "n = 2\n"
     "__match n:\n"
     "case 1:\n"
     "    print('one')\n"
     "case _:\n"
     "    print('rest')\n"
     "print('after')\n"
     "\n"
     "def main():\n"
     "    return 0\n", ("frontend",), "module"),

    # ── the shapes that are REFUSED, and the refusal has to name them ──────
    #
    # Every one of these PARSES (measured with `formal/build.py::parse_module`
    # and recorded in this file's docstring), so a lowering that treated a
    # pattern as an ordinary expression would answer all of them. Each row
    # pins the CONSTRUCT in the refusal text, so a backend that falls back to
    # "unsupported statement MatchStmt" fails the row rather than passing it.
    #
    # `case 1 | 2:` — PEP 634's or-pattern, one `BinaryOp('|')` here. Lowered
    # as an expression it is `1 | 2 == 3`, so a subject of 3 would match an
    # arm that CPython and this compiler's own free-variable analysis both say
    # means "1 or 2" (`test_new_syntax_parsing.py`'s
    # `match_or_of_literals_has_no_names`).
    ("or_pattern_pipe_is_refused", "n = 1\n"
     "match n:\n"
     "    case 1 | 2:\n"
     "        print('low')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "or-PATTERN")),
    # `case [a, b]:` — a sequence pattern, one `ListExpr` here. Lowered as an
    # expression it compares the subject to `[a, b]`, which is a value
    # comparison and not a decomposition: it binds nothing, and it is wrong
    # about LENGTH (`case [a]` must not match `[1, 2]`).
    ("sequence_pattern_is_refused", "s = [1, 2]\n"
     "match s:\n"
     "    case [a, b]:\n"
     "        print(a)\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "SEQUENCE PATTERN")),
    ("sequence_pattern_with_star_is_refused", "s = [1, 2, 3]\n"
     "match s:\n"
     "    case [a, *rest]:\n"
     "        print(a)\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "SEQUENCE PATTERN")),
    # A parenthesised pair is the same pattern with different spelling, and the
    # refusal must not be a list-literal test that `(` slips past.
    ("tuple_pattern_is_refused", "s = (1, 2)\n"
     "match s:\n"
     "    case (1, 2):\n"
     "        print('pair')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "SEQUENCE PATTERN")),
    # `case {"k": v}:` — a mapping pattern, one `DictExpr` here.
    ("mapping_pattern_is_refused", "d = {'k': 3}\n"
     "match d:\n"
     "    case {'k': v}:\n"
     "        print(v)\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "MAPPING PATTERN")),
    # `case Point(x=0):` — a class pattern with keywords, one `CallExpr` here.
    # Lowered as an expression it CONSTRUCTS a `Point` and compares it, which
    # reads as a working feature and answers `match Point(0, 1): case
    # Point(x=0, y=1)` with a construction instead of a match.
    ("class_pattern_is_refused", "struct Point:\n"
     "    x: Int32\n"
     "    y: Int32\n"
     "\n"
     "def main():\n"
     "    p = Point(0, 1)\n"
     "    match p:\n"
     "        case Point(x=0, y=1):\n"
     "            print('origin-x')\n"
     "        case _:\n"
     "            print('rest')\n"
     "    print('after')\n"
     "    return 0\n", ("refuse", "CLASS PATTERN"), "module"),
    # `case [a] as whole:` — the `as` binding, one `BinaryOp('as')` here.
    ("as_binding_is_refused", "s = [1]\n"
     "match s:\n"
     "    case [a] as whole:\n"
     "        print(a)\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "`as`-BINDING")),
    # The dot-relative enum pattern, `case .A:`. This one is not a PEP 634
    # structural pattern — it is Mojo's enum dispatch, and the value it names
    # has no spelling this path can resolve (`myinterpreter.py` refuses it
    # too: "cannot resolve the dot-relative value '.A'"). It is here because a
    # `DottedLiteral` reaching the pattern reader as an ordinary expression is
    # a refusal about a NAME, and the construct the reader wrote is an enum
    # case.
    ("dotted_literal_pattern_is_refused", "n = 1\n"
     "match n:\n"
     "    case .A:\n"
     "        print('a')\n"
     "    case _:\n"
     "        print('rest')\n"
     "print('after')", ("refuse", "ENUM CASE")),
]


# ── the runner ───────────────────────────────────────────────────────────────

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print("FAIL  %s" % what + ((": " + detail) if detail else ""),
              flush=True)
    return bool(ok)


def build_run(tmpdir, name, source, backend):
    """Build `source` for `backend` and RUN the image. Returns a verdict tuple."""
    src = os.path.join(tmpdir, "%s_%s.py" % (name, backend))
    out = os.path.join(tmpdir, "%s_%s.bin" % (name, backend))
    with open(src, "w") as f:
        f.write(source)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            "--backend=%s" % backend, "-o", out, src]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        return ("BUILD-FAIL", (r.stderr or r.stdout).strip())
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ("RAN", run.stdout, run.returncode)


def oracle(source, tmpdir, kind):
    """`(stdout, exit status)` for `source` under the named oracle.

    `main()` is appended for BOTH oracles and for the same reason: the formal
    driver CALLS the entry function itself (`fire.py build` synthesises the
    startup stub around `functions[0]`), and `fire.py run` calls it too, so the
    two runners differ only in which ENGINE reads the text. Without the
    appended call the CPython oracle imports a module, defines `main`, and
    prints nothing — which every row would then compare against an empty
    expectation.
    """
    src = os.path.join(tmpdir, "oracle_%s.py" % kind)
    with open(src, "w") as f:
        f.write(source + "\nmain()\n")
    argv = ([sys.executable, src] if kind == "cpython"
            else [sys.executable, FIRE, "run", src])
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return (r.stdout, r.returncode)


def _want(want, backend):
    return want.get(backend, want.get("default")) \
        if isinstance(want, dict) else want


def judge(name, backend, res, want, tmpdir, source):
    tag = "[%s] %s" % (backend, name)
    if res[0] == "BUILD-FAIL":
        text = res[1]
        if want[0] != "refuse":
            return check(False, tag + " builds", text[-400:])
        return check(want[1] in text,
                     tag + " refuses naming %r" % want[1], text[-400:])
    if want[0] == "refuse":
        return check(False, tag + " is refused, not answered",
                     "it printed %r and exited %d" % (res[1], res[2]))
    if want[0] not in ("cpython", "frontend"):
        return check(False, tag + " has a row shape this runner knows",
                     repr(want))
    out, rc = oracle(source, tmpdir, want[0])
    if rc != 0:
        return check(False, "the %s oracle for %s runs" % (want[0], name),
                     "exit %d, stderr %r" % (rc, out[-300:]))
    return check((res[1], res[2]) == (out, rc),
                 tag + " matches the %s oracle" % want[0],
                 "printed %r exit %d; the oracle printed %r exit %d"
                 % (res[1], res[2], out, rc))


def row_source(row):
    """The text of one row: `prog`-wrapped, or the module's own top level."""
    body = row[1]
    return mod_prog(body) if row[3:4] == ("module",) else prog(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", dest="substring", default=None)
    ap.add_argument("--only-row", type=int, default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for i, row in enumerate(ROWS):
            print("%3d %-46s %-9s %s"
                  % (i, row[0], row[3] if len(row) > 3 else "in-main",
                     row[2][0]))
        return 0

    rows = list(enumerate(ROWS))
    if args.only_row is not None:
        rows = [(i, r) for i, r in rows if i == args.only_row]
    if args.substring:
        rows = [(i, r) for i, r in rows if args.substring in r[0]]

    with tempfile.TemporaryDirectory(prefix="formal-match-") as tmp:
        for _i, row in rows:
            name, want = row[0], row[2]
            source = row_source(row)
            for backend in BACKENDS:
                judge(name, backend, build_run(tmp, name, source, backend),
                      _want(want, backend), tmp, source)
            if args.verbose:
                print("ran %s" % name, flush=True)

    passed = sum(1 for ok, _ in RESULTS if ok)
    print("%d/%d verdicts passed over %d rows"
          % (passed, len(RESULTS), len(rows)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())