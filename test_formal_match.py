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

**The sweep's own accounting, for completeness.** These six refusals are
`other refusal` in `tools/formal_sweep_causes.py` today, and that is correct
rather than an oversight: no file in this corpus writes a `match` (measured —
`grep` over every `*.mojo` finds only prose that happens to contain the word),
so a cause row for them would collect nothing while reading as one that blocks
nothing, which `test_refusal_taxonomy.py`'s "a cause that matches no real
message" check exists to prevent. The row to add is the day a corpus file
writes one, with a `CAUSE_SAMPLES` entry beside it.

**The structural shapes are not "unsupported" — they are REFUSED, by name.**
`case [a, b]:`, `case {"k": v}:`, `case Point(x=0):`, `case 1 | 2:`,
`case [a] as whole:` and `case .A:` all PARSE, into an ordinary `ListExpr` /
`DictExpr` / `CallExpr` / `BinaryOp` / `DottedLiteral` (measured with
`formal/build.py::parse_module`, and the node each one produces is in
`formal/model.py::match_pattern_kind`). So a backend that lowered a pattern as
"evaluate it and compare with `==`" would ANSWER them — and be wrong, silently,
in the exact way that reads as a working feature: `case 1 | 2:` computes
`1 | 2 == 3` and matches the subject against 3, `case [a, b]:` compares the
subject to a list literal whose `a` and `b` are ordinary reads rather than
bindings, and `case Point(x=0, y=1):` CONSTRUCTS a `Point` and compares it.
This compiler's own free-variable analysis already treats the first four as
BINDING structural patterns (`test_new_syntax_parsing.py::test_match`'s
`match_seq_pattern_binds`, `match_dict_pattern_binds`,
`match_or_of_literals_has_no_names`, `match_as_binds_both_and_guard_is_a_use`),
so the formal path refusing them by name is the two frontends AGREEING rather
than the formal path being narrow; the sixth is Mojo's enum dispatch, which
nothing on this path can resolve (`myinterpreter.py` refuses the same spelling).
Those rows carry `("refuse", "<substring>")` and the substring is the CONSTRUCT.

**The Lean model carries it, and that is measured rather than asserted.** The
proof section at the end compares each program with the `if` chain it lowers to:
they must agree on whether a proof is generated, and (where Lean is available) on
whether it ELABORATES. See `PROOF_PAIRS`.

Run:  python3 test_formal_match.py [-v] [-k SUBSTRING] [--only-row N] [--list]
      [--no-lean] [--all-proofs]
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

    # ── the shapes a first lowering gets wrong, one row each ────────────────
    #
    # Everything above is a `match` in a straight-line function. These are the
    # shapes where a lowering that is "an if-chain, roughly" gives a wrong
    # answer or a refusal, and each one is here because of what it would take
    # to get it wrong rather than because of what it prints.
    #
    # A `return` out of an arm inside a `try`: the emitters keep a list of
    # pending `finally` bodies and flush it on every exit path
    # (`_emit_stmt`'s `ReturnStmt` arm calls `_flush_pending_finally`), so an
    # arm's `return` has to be spliced into the enclosing `try` for the flush to
    # see it. A lowering that built a separate function per arm, or that
    # lowered the arm body into a synthetic block, would skip the cleanup
    # entirely. CPython's order — the `finally` runs BEFORE the returned value
    # reaches the caller — is what this row pins. The SECOND-exit shape that
    # used to be separate (and was missing its `fin`) is now
    # `second_exit_from_a_try_runs_the_finally` just below: it was pinned as a
    # KNOWN-DEFECT row until the shared `_flush_pending_finally` stopped
    # truncating its frame list (the second-exit path used to drop the
    # `finally`).
    ("arm_return_inside_a_try_runs_the_finally", "def f(n):\n"
     "    try:\n"
     "        match n:\n"
     "            case 1:\n"
     "                print('one')\n"
     "                return 10\n"
     "            case _:\n"
     "                print('other')\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    print(f(1))\n"
     "    print('done')\n"
     "    return 0\n", ("cpython",), "module"),
    # Every `return` out of a `try` body must run the `finally`, not only the
    # first one the emitter happens to visit (source order). This is the row
    # that used to carry the missing `fin` before `20`; the fix is that
    # `_flush_pending_finally` keeps its frame list and guards re-entrancy by
    # identity instead, so both exits emit the cleanup.
    ("second_exit_from_a_try_runs_the_finally",
     "def f(n):\n"
     "    try:\n"
     "        match n:\n"
     "            case 1:\n"
     "                print('one')\n"
     "                return 10\n"
     "            case _:\n"
     "                return 20\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    print(f(1))\n"
     "    print(f(2))\n"
     "    print('done')\n"
     "    return 0\n", ("cpython",), "module"),
    # A `match` inside an arm, with BOTH subjects an EXPRESSION, so each `match`
    # allocates its own temporary. The two questions are separate and both are
    # invisible in a straight-line program: the walk has to reach a `match`
    # nested inside another `match`'s arm, and the fresh-name counter has to
    # produce two names that do not collide (a collision would be harmless here
    # — the outer temporary is dead by the time the inner arm runs — so this row
    # is not a test of that, and `_fn_spelled_names` is what covers it).
    ("match_nested_in_an_arm", "def s(v):\n"
     "    return v\n"
     "\n"
     "def main():\n"
     "    match s(1):\n"
     "        case 1:\n"
     "            match s(9):\n"
     "                case 9:\n"
     "                    print('inner-nine')\n"
     "                case _:\n"
     "                    print('inner-other')\n"
     "            print('after-inner')\n"
     "        case _:\n"
     "            print('outer-other')\n"
     "    print('after')\n"
     "    return 0\n", ("cpython",), "module"),
    # A subject whose value is a POINTER rather than a word. The temporary the
    # lowering introduces holds whatever the subject held, and for a string that
    # is a `char *` into `__TEXT,__text` — so this row is about the temporary
    # being a pointer-typed home and not about string comparison, which
    # `lit_string` already covers.
    ("string_subject_expression", "def s():\n"
     "    return 'bb'\n"
     "\n"
     "def main():\n"
     "    match s():\n"
     "        case 'aa':\n"
     "            print('first')\n"
     "        case 'bb':\n"
     "            print('second')\n"
     "    print('after')\n"
     "    return 0\n", ("cpython",), "module"),
    # A capture in an EARLIER arm makes the name BOUND for a LATER arm, so
    # `case v:` twice is a capture and then a COMPARISON. That is the
    # interpreter's `scope.has` answer — the first arm's `define` is visible
    # when the second arm is reached — and it is what makes the second `case v:`
    # here a comparison (7 == 7) rather than a second capture. CPython refuses to
    # compile this text at all ("name capture 'v' makes remaining patterns
    # unreachable", measured), so the oracle is this compiler's interpreter:
    # both print `captured`, `same-name-compare`, `after`.
    ("capture_in_an_earlier_arm_binds_a_later_pattern", "n = 7\n"
     "match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case v:\n"
     "        print('captured')\n"
     "        match n:\n"
     "            case v:\n"
     "                print('same-name-compare')\n"
     "            case _:\n"
     "                print('inner-other')\n"
     "print('after')", ("frontend",)),
    # `case True:` is a VALUE pattern in both compilers and not a capture of a
    # name called `True`. `None`/`True`/`False` are in the interpreter's every
    # scope and CPython spells them as literals, so the compile-time rule has to
    # agree with both — which it does by construction, and this row is what
    # would catch a lowering that treated every bare name in a pattern as a
    # capture.
    ("bool_patterns_are_values", "def f(flag):\n"
     "    match flag:\n"
     "        case True:\n"
     "            print('yes')\n"
     "        case False:\n"
     "            print('no')\n"
     "        case _:\n"
     "            print('other')\n"
     "\n"
     "def main():\n"
     "    f(True)\n"
     "    f(False)\n"
     "    f(7)\n"
     "    return 0\n", ("cpython",), "module"),
    # `global K` makes the name a module-level one, so a `case K:` after it is a
    # comparison in both oracles — measured, `fire.py run` prints `rest` for a
    # subject of 5 against `K = 2`. CPython would capture instead, so the
    # frontend oracle is the one that can run this text with the same answer.
    ("global_makes_a_pattern_a_comparison", "K = 2\n"
     "\n"
     "def main():\n"
     "    global K\n"
     "    n = 5\n"
     "    match n:\n"
     "        case K:\n"
     "            print('low')\n"
     "        case _:\n"
     "            print('rest')\n"
     "    print('after')\n"
     "    return 0\n", ("frontend",), "module"),
    # A pattern list that STARTS with a capture, and therefore DEAD after it.
    # `myinterpreter.py` walks `match_case.patterns` and STOPS at the first
    # that matches, and a capture always matches, so the `TBL[5]` here is never
    # evaluated — which is observable, because `TBL[5]` is one past the end of a
    # two-element list and reading it traps (`print(TBL[5])` exits 1 on both
    # architectures, measured). A lowering that collected every pattern into one
    # boolean would read it, exit 1, and answer nothing. The capture binds, so
    # the arm may read `other` on either path — which is the one shape where a
    # capture that is not in the first position is still readable, and the
    # reason the row below cannot read its own capture.
    ("capture_at_the_front_of_a_pattern_list_kills_the_rest", "TBL = [10, 20]\n"
     "\n"
     "def f(n):\n"
     "    match n:\n"
     "        case other, TBL[5]:\n"
     "            print('low')\n"
     "            print(other)\n"
     "        case _:\n"
     "            print('rest')\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    f(5)\n"
     "    f(1)\n"
     "    return 0\n", ("frontend",), "module"),
    # A capture in the SECOND position of a pattern list. The reference reaches
    # it exactly when every comparison before it failed, and it matches whatever
    # reached it — so the arm runs EITHER WAY, and only the second outcome binds.
    # A lowering that put the arm in the `then` of "one of the comparisons
    # matched" printed `rest` for `f(5)` where `fire.py run` prints `low`, and a
    # lowering that swapped the arms printed one `low` where the reference prints
    # two; both were measured, on both architectures, before the split.
    #
    # The body does NOT read `other`, and that is not modesty: on the path where
    # the first pattern matched, `other` is unbound, so a body that read it would
    # be a program the reference answers with a `NameError` and this path
    # refuses with the read-before-store message — correctly, and for a reason
    # that has nothing to do with `match`. CPython reads `case 1, other:` as a
    # two-element SEQUENCE pattern, so the oracle is this compiler's interpreter.
    ("capture_in_the_second_position_runs_the_arm_either_way", "def f(n):\n"
     "    match n:\n"
     "        case 1, other:\n"
     "            print('low')\n"
     "        case _:\n"
     "            print('rest')\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    f(5)\n"
     "    f(1)\n"
     "    return 0\n", ("frontend",), "module"),
    # …and a WILDCARD in the same position, which is the same rule with no
    # binding attached — and so with no reason the body cannot read. `case 1, _:`
    # is irrefutable, so the rest of the `match` is only reachable through a
    # guard, and `case 9:` below it is never reached.
    ("wildcard_in_the_second_position_of_a_pattern_list", "def f(n):\n"
     "    match n:\n"
     "        case 1, _:\n"
     "            print('low')\n"
     "        case 9:\n"
     "            print('rest')\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    f(5)\n"
     "    f(1)\n"
     "    return 0\n", ("frontend",), "module"),
    # `comptime __match`, the Mojo spelling, and the one place where this
    # lowering deliberately does NOT fold. Real Mojo resolves `comptime __match`
    # at compile time; this compiler's reference interpreter runs it as an
    # ordinary `match` (`myinterpreter.py::execute_MatchStmt` has no comptime
    # arm — `execute_ComptimeIfStmt` says outright that the interpreter "doesn't
    # do compile-time branch elimination, so this just evaluates like a regular
    # runtime if/elif/else"), and this lowering lowers it the same way. So the
    # observable answer is the interpreter's and the row is here to say the
    # divergence from Mojo is DELIBERATE and consistent rather than accidental:
    # a fold would need `DottedLiteral` resolution (the `case .int:` spelling is
    # refused by name, `dotted_literal_pattern_is_refused`) and nothing here has
    # it. The literal cases below fold trivially and answer the same either way.
    ("comptime_match_is_a_runtime_match_here", "def main():\n"
     "    n = 2\n"
     "    comptime __match n:\n"
     "    case 1:\n"
     "        print('one')\n"
     "    case 2:\n"
     "        print('two')\n"
     "    case _:\n"
     "        print('rest')\n"
     "    print('after')\n"
     "    return 0\n", ("frontend",), "module"),
    # A `match` with NO cases. The parser accepts it (`cases` is an empty list)
    # and every lowering has to answer "nothing matches", which means the
    # statement disappears rather than becoming a chain with an empty test. CPython
    # refuses to compile it ("expected an indented block after 'match'"), so the
    # oracle is this compiler's interpreter.
    ("match_with_no_cases", "n = 3\n"
     "match n:\n"
     "print('after')\n"
     "\n"
     "def main():\n"
     "    return 0\n", ("frontend",), "module"),
]


# ── the rows that PIN a known wrong answer ───────────────────────────────────
#
# Every row above is either right or refused. These are not, and a table of
# `match` semantics that quietly left them out would be a census with the
# failures taken out — the thing CLAUDE.md calls "a fixed bug still listed is
# indistinguishable from an open one" in its worse form, the failure never
# written down at all.
#
# Each row asserts the CURRENT answer and carries CPython's in a comment. When
# the defect is fixed the row fails, which is the point: the fix and the row's
# update land in the same commit, and a silent fix cannot leave a stale claim
# behind.
#
# (name, body, the answer the image gives today, CPython's answer, the doc).
#
# EMPTY since 2026-10-05: the one row here
# (`second_exit_from_a_try_drops_the_finally`) went green when the shared
# `_flush_pending_finally` stopped truncating its frame list, and it moved to
# `ROWS` as `second_exit_from_a_try_runs_the_finally` with a CPython oracle.
# `judge_known_defect` stays so the next defect has a place to be pinned.
KNOWN_DEFECT_ROWS = []


# ── the Lean model: is a `match` as PROVABLE as the `if` it lowers to? ─────────
#
# The claim this lowering makes is that a `match` becomes ordinary compares and
# branches, so the existing conditional proof covers it and nothing new is needed
# in either proof generator. That is a claim about the MODEL, and it is only
# worth making if it is measured, so each pair below is the SAME program written
# twice: once with `match`, once with the `if` chain it lowers to.
#
# Two verdicts, and the cheap one is the one that runs always:
#
#   * GENERATION — `formal.build.compile_formal(..., prove=True, check=False)`
#     writes the `.lean` without running Lean (0.0-0.1 s per program, measured).
#     The pair must agree on whether a proof was produced AT ALL, and a produced
#     proof must be non-trivial. This is the "a generator that cannot produce
#     text is worth catching" half, and it is what runs in the gate-shaped loop.
#   * ELABORATION — `formal/lean.py::check_proof_cached` when Lean and
#     `lib/ProofLib.olean` are both present. The pair must reach the SAME
#     verdict, ok or not. This is the half that is expensive: 2 s (x86-64) to
#     48 s (arm64) per program on this tree, and the arm64 numbers are why this
#     section checks ONE pair by default (`--all-proofs` for both).
#
# **The two-case pair is the one that carries the operand-order claim.**
# `formal/build.py::_lower_one_case` emits `SUBJECT == PATTERN` rather than the
# reference's `pattern == subject`, and that is not cosmetic: measured through
# `check_proof_cached`, `if n == 0:` elaborates on arm64 and `if 0 == n:` does
# not (`Application type mismatch` on the `B.cond` block's `hcond` obligation —
# `bugs/FORMAL_arm64_proof_a_compare_with_the_immediate_on_the_left_does_not_
# elaborate.md`). A `match` whose compare had the literal on the left would
# therefore be unprovable while the `if` it lowers to is provable, and this pair
# is what catches a swap.
#
# **The three-case pair fails on arm64 and so does its `if`.** That is stated
# here rather than left to be discovered: it is a pre-existing gap in arm64's
# generator for a three-block conditional chain (both spellings — the `elif`
# chain and the nested `else: if` — were measured), it is in the family
# `bugs/FORMAL_arm64_known_proof_gaps.md` censuses, and the property this
# section asserts is PARITY with the `if`, not that every `match` elaborates.
PROOF_PAIRS = [
    ("two_cases",
     "def main() -> Int:\n"
     "    n = 3\n"
     "    match n:\n"
     "        case 0:\n"
     "            return 10\n"
     "        case _:\n"
     "            return 20\n",
     "def main() -> Int:\n"
     "    n = 3\n"
     "    if n == 0:\n"
     "        return 10\n"
     "    else:\n"
     "        return 20\n"),
    ("three_cases",
     "def main() -> Int:\n"
     "    n = 3\n"
     "    match n:\n"
     "        case 0:\n"
     "            return 10\n"
     "        case 1:\n"
     "            return 20\n"
     "        case _:\n"
     "            return 30\n",
     "def main() -> Int:\n"
     "    n = 3\n"
     "    if n == 0:\n"
     "        return 10\n"
     "    elif n == 1:\n"
     "        return 20\n"
     "    else:\n"
     "        return 30\n"),
]

#: Pairs whose ELABORATION is checked when Lean is available. The two-case one
#: is the operand-order claim; the three-case one is here for the parity check
#: and costs 48 s on arm64, so it is opt-in.
PROOF_CHECKED = ("two_cases",)


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


def generate_proof(tmpdir, name, source, arch):
    """`(proof_path, None)` or `(None, why)` — generation only, no Lean.

    `check=False` is what keeps this cheap: `formal/build.py` writes the `.lean`
    and returns its path without elaborating it (measured 0.0-0.1 s per program
    for both architectures). A generator that RAISES here is the failure worth
    catching without a 27 MB library build, which is why this half runs even
    where Lean does not.
    """
    import formal.build as fb
    src = os.path.join(tmpdir, "%s_%s_gen.mojo" % (name, arch))
    out = os.path.join(tmpdir, "%s_%s_gen.bin" % (name, arch))
    with open(src, "w") as f:
        f.write(source)
    try:
        r = fb.compile_formal(src, arch=arch, output=out, prove=True,
                              check=False)
        return r["proof_path"], None
    except Exception as e:                       # noqa: BLE001 — reported
        return None, "%s: %s" % (type(e).__name__, str(e)[:200])


def _lean_ready():
    """`(ready, why)` — Lean and a built `ProofLib.olean`, or why not."""
    from formal.lean import find_lean
    if not find_lean(HERE):
        return False, "lean is not on PATH"
    olean = os.path.join(HERE, "lib", "ProofLib.olean")
    if not os.path.isfile(olean):
        return False, "lib/ProofLib.olean is not built"
    return True, ""


def check_proofs(tmpdir, pairs, with_lean):
    """Generation parity always; elaboration parity when Lean is available."""
    for name, match_src, if_src in pairs:
        for arch in BACKENDS:
            got = {}
            for spelling, text in (("match", match_src), ("if", if_src)):
                path, why = generate_proof(tmpdir, "%s_%s" % (name, spelling),
                                           text, arch)
                got[spelling] = (path, why)
            m_path, m_why = got["match"]
            i_path, i_why = got["if"]
            tag = "[%s] proof %s" % (arch, name)
            if (m_path is None) != (i_path is None):
                check(False, tag + " generates for both spellings",
                      "match: %s / if: %s" % (m_why or "ok", i_why or "ok"))
                continue
            if m_path is None:
                check(True, tag + " refuses to generate for both spellings "
                                "(a shared pre-existing gap)")
                continue
            m_size, i_size = os.path.getsize(m_path), os.path.getsize(i_path)
            check(m_size > 1000,
                  tag + " generates a non-trivial model for the match "
                        "(%d bytes, the if spelling is %d)" % (m_size, i_size))
            if not with_lean or name not in PROOF_CHECKED:
                continue
            from formal.lean import check_proof_cached
            verdicts = {}
            for spelling, path in (("match", m_path), ("if", i_path)):
                ok, _detail, _cached, _n = check_proof_cached(
                    path, repo_root=HERE)
                verdicts[spelling] = bool(ok)
            check(verdicts["match"] == verdicts["if"],
                  tag + " is as provable as the if it lowers to",
                  "match elaborates=%s, if elaborates=%s"
                  % (verdicts["match"], verdicts["if"]))


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
    ap.add_argument("--no-lean", action="store_true",
                    help="skip the Lean elaboration check (generation only)")
    ap.add_argument("--all-proofs", action="store_true",
                    help="elaborate every pair, not just PROOF_CHECKED")
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

    ready, why_not = (False, "--no-lean") if args.no_lean \
        else _lean_ready()
    if args.no_lean:
        print("lean elaboration: SKIPPED (%s)" % why_not)
    elif not ready:
        print("lean elaboration: SKIPPED (%s) — the GENERATION half still "
              "runs, and a generator that raises is worth catching without "
              "Lean" % why_not)
    elif args.all_proofs:
        print("lean elaboration: every pair (48 s per arm64 program on this "
              "tree)")

    with tempfile.TemporaryDirectory(prefix="formal-match-") as tmp:
        for i, row in rows:
            name, want = row[0], row[2]
            source = row_source(row)
            for backend in BACKENDS:
                judge(name, backend, build_run(tmp, name, source, backend),
                      _want(want, backend), tmp, source)
            if args.verbose:
                print("ran %s" % name, flush=True)
        check_proofs(tmp, PROOF_PAIRS, ready and not args.no_lean)

    passed = sum(1 for ok, _ in RESULTS if ok)
    print("%d/%d verdicts passed over %d rows"
          % (passed, len(RESULTS), len(rows)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())