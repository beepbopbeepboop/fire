#!/usr/bin/env python3
r"""The builtin functions, measured against CPython rather than pinned.

    python3 test_formal_builtins_conformance.py [-v] [--list] [--cases] [group ...]
    python3 test_formal_builtins_conformance.py --only <group>

WHAT THIS FILE IS, AND WHY IT IS NOT `test_formal_value_model.py`
------------------------------------------------------------------
`test_formal_value_model.py` already holds a builtin group, and it is not a
smaller version of this one: it holds ELEVEN cases, one per name, chosen because
each one was a bug. This file holds a TABLE, and the table is GENERATED from two
places rather than written down:

  * CPython's OWN regression suite (`Lib/test/test_builtin.py`, found through
    `import test` rather than searched for, so the cases and the oracle come from
    the same interpreter), harvested with the harvester
    `test_formal_hostmods_conformance.py` already owns — imported, not copied,
    because a second constant propagator over a CPython test file is a second
    thing to be right about and that file's own docstring gives the reason at
    length;
  * a declared `GROUPS` table of the SHAPES CPython's suite cannot express as a
    literal call, which is most of them: CPython builds its builtin vectors in
    loops and through `self.assertEqual` over computed expectations, so a harvest
    of the file finds 189 calls of which 156 are `pow`/`round`/`ord`/`chr` — all
    three of which this path refuses — and nothing at all for `sorted(key=…)`,
    `min(default=…)`, `zip(strict=…)` or `enumerate(xs, 3)`.

Every case runs the SAME TEXT under CPython and on BOTH backends and requires
byte-identical stdout and exit status. There is no table of expected values in
this file, for the reason `test_formal_value_model.py`'s header gives at length:
a case pinned to a value that was wrong in the first place reads as a regression
in the image rather than as the pre-existing wrong answer it is, and the failure
this project treats as worse than a refusal is an image that answers a different
number.

THE THREE VERDICTS, AND WHY A REFUSAL IS NOT A PASS
--------------------------------------------------
Every case gets exactly one of three verdicts, and the middle one is the point:

  `agree`    both images print what CPython prints and exit as it exits.
  `refuse`   the build refuses, and it refuses BY NAME at a chokepoint that
             says what lowering the name would take — `model.not_lowered_`
             `builtin_refusal`, quoting `model.NOT_LOWERED_BUILTINS`.
  `DIVERGE`  anything else, and every kind of it is a failure:
               * an image that answers a different number than CPython;
               * an image that crashes (a negative exit status is a SIGSEGV or
                 a SIGBUS, and an image that died has not answered anything);
               * the two backends disagreeing with EACH OTHER, which no oracle
                 can see because both would have to be wrong the same way;
               * a refusal that arrives at the WRONG chokepoint — the link
                 audit's "the image would bind 1 symbol(s) that nothing
                 provides", whose advice is about the link line when the truth
                 is that no library provides a Python builtin's semantics, or a
                 `len()` refusal blaming an integer for a name that was never
                 lowered. Both are failures and both were, in bulk: 26 of
                 CPython's builtin names reached the link audit and 7 more were
                 refused for a construct that was not the problem.

A refusal that carries the right name is COUNTED and PRINTED, never swallowed,
because a table that could not say how many of CPython's own cases this engine
declines would be reporting a smaller number than it measured.

WHAT IS ACTUALLY IN THE TABLE, AND WHY SO MUCH OF IT IS A REFUSAL
-----------------------------------------------------------------
A value on this path is ONE 64-bit integer word, or a frame address, or a
`char *` to interned literal bytes (`formal/model.py`, and
`bugs/FORMAL_the_value_model_is_one_word.md`). That single fact decides most of
the table before a case is even built: `sorted` needs a comparison call per
element, `map`/`filter` need a call through a value, `enumerate`/`zip`/`reversed`
need a run-time-sized container or a cursor (a sequence AND a position, two
words), and `divmod` needs a pair. Those are refusals with a REASON, they are
the correct answer for this backend, and they are what the table exists to
state rather than to work around.

`range` is the opposite case and is why this file was worth writing: it lowers,
and before this table it diverged from CPython in three ways on BOTH
architectures — see the `range` group's notes, which carry the measurements.

GROUPING, AND WHAT EACH GROUP IS A MEASUREMENT OF
-------------------------------------------------
Each group is one BUILTIN FAMILY, so a failure says which family moved rather
than which of 300 rows happened to be checked first, and so `--list` can print
how many cases each family actually yielded — which is the number that says what
this file is worth per family. The families are the ones CPython's own
`test_builtin.py` is organised around plus the ones this backend's value model
makes the interesting ones.

A NOTE ON SCOPE, WHICH IS A MEASUREMENT AND NOT AN APOLOGY
----------------------------------------------------------
`hash` of a `str` is refused BY NAME and deliberately so: CPython randomises it
per process unless `PYTHONHASHSEED` is fixed, so two runs of one program disagree
by design and there is no oracle to compare against. `hash` of an `int` IS the
identity below `sys.hash_info.modulus` and is therefore answerable, and the
table asks it — with the modulo stated rather than assumed, because a value here
is 64 bits and CPython's is 2**61 - 1, so the two agree on every ordinary
integer and neither of them is wrong.
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

sys.path.insert(0, HERE)

# The pass/fail helper and the `fire.py` driver, imported rather than copied, for
# `test_formal_hostmods_conformance.py`'s reason: this file's cases are built and
# run the same way that file's are, so a second driver is a second thing that can
# disagree about what an image did.
from test_formal_dylib import (Failure, TestFailure, check, rosetta,  # noqa: E402
                               run_fire)

# ── the CPython translation of a case ───────────────────────────────────────
#
# The `printf` shim is `test_formal_value_model.py`'s with ONE addition, and the
# addition is load-bearing rather than cosmetic: **CPython's `%` has no `l`
# length modifier**, so `"L%lld" % 3` raises `ValueError: unsupported format
# character 'l'` and every case in this table would have no oracle at all. The
# translation `%lld` → `%d` is the spelling difference between C's integer
# conversion and Python's, and it is the only one any case needs — this backend's
# `printf` is libc's and wants the `l` because a value here is one 64-bit word
# while CPython's `%d` formats an unbounded `int`. Measured on both backends, a
# case using `%lld` and the same case using `%d` print the same bytes for every
# value in this table.
#
# The `var` keyword is dropped (fire_compiler parses both spellings and CPython
# only one) and `sys.exit(main())` is appended. Nothing else: a case that needed
# a rewrite beyond that would be a case comparing two different programs.
_SHIM = ("import sys\n"
         "def printf(fmt, *a):\n"
         "    sys.stdout.write(fmt.replace('%lld', '%d') % a)\n")
_VAR = re.compile(r"^(\s*)var (\w)", re.M)


def cpython_source(body: str) -> str:
    """The case's own text, runnable by CPython.

    The `var` keyword is dropped (fire_compiler parses both spellings and
    CPython only one) and `sys.exit(main())` is appended. Nothing else: a case
    that needed a rewrite to be expressible in CPython would be a case comparing
    two different programs.
    """
    return _SHIM + _VAR.sub(r"\1\2", body) + "\nsys.exit(main())\n"


# ── the case table ──────────────────────────────────────────────────────────
#
# `body` is the text INSIDE `main`, one statement per list entry, and it is the
# whole case: the same string is written to the `.mojo` file and translated for
# CPython, so there is exactly one spelling of every case in this file.
#
# `kind` is what a case asserts about the BUILD, and it is the column that makes
# the refusals a measurement rather than a gap:
#
#   "run"     the image must build, run, and print what CPython prints.
#   "refuse"  the build must refuse BY NAME, quoting the model's own row for the
#             builtin. The needle is the refusal's opening clause, so a refusal
#             that starts naming a DIFFERENT construct is a failure — which is
#             the case that was 26 names wide before `NOT_LOWERED_BUILTINS` grew.
#
# A case with no `kind` is a `run` case.

# Every case prints `L<field> <field> …` so a mismatch says WHICH field differs,
# and ends with `\n` — the one escape, written once so the reason it is the only
# one is in one place.


def R(*fields):
    """A `run` case's expectation shape: nothing. CPython decides it."""
    return {"kind": "run"}


def F(name, needle):
    """A `refuse` case: the build must refuse BY NAME, naming `name`."""
    return {"kind": "refuse", "name": name, "needle": needle}


GROUPS = []


def group(name, note, cases):
    GROUPS.append({"name": name, "note": note, "cases": cases})


# ── range ───────────────────────────────────────────────────────────────────
#
# The only builtin in this table that LOWERS and that was wrong, and all three
# of its failures were invisible to `range(n)` and `range(a, b)` — the two shapes
# every range test in the tree writes. They are pinned here with the shape that
# finds each one.
group(
    "range",
    "`range` is the one builtin that materialises (`EMITTER_BUILTINS`'s "
    "`range_list`), so it is the one this table can hold to an ANSWER rather "
    "than a refusal, and it is where the three divergences this file was written "
    "for were found: the x86-64 fill loop clobbered its own index through "
    "`imul`'s two-operand form (SIGSEGV for a negative step, wrong elements "
    "for any step != 1); the x86-64 count negated the span only for a LITERAL "
    "negative step, so a descending range pointing away from its stop exited 1 "
    "where CPython's is empty; and `kind_of` had no row for `range`, so a NAME "
    "bound to one was classified an integer and `len()` refused a list the line "
    "above had built. Every case below is a `run` case: a refusal here would be "
    "a regression, not a limit.",
    [
        # The three shapes every range test in the tree writes, so a rewrite
        # that broke them is caught before the interesting ones are read.
        ("one_argument", ["printf(\"L%lld %lld\\n\", len(range(5)), range(5)[4])"]),
        ("two_arguments", ["printf(\"L%lld %lld\\n\", len(range(2, 9)), range(2, 9)[0])"]),
        # A NEGATIVE step: count, first element, last element and a middle one.
        # This is the SIGSEGV case — the fill loop's index oscillated and never
        # reached the count, so the image ran off the end of the blob.
        ("negative_step_count_and_ends",
         ["var r = range(5, 0, -1)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[4])"]),
        ("negative_step_from_a_non_default_start",
         ["var r = range(9, 0, -1)",
          "printf(\"L%lld %lld %lld %lld\\n\", len(r), r[0], r[3], r[8])"]),
        ("negative_step_over_negatives",
         ["var r = range(-1, -6, -1)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[4])"]),
        ("negative_step_crossing_zero",
         ["var r = range(5, -5, -3)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[3])"]),
        # A POSITIVE step other than 1: the early-exit half of the same bug.
        # The index walked 0, 1, 3, 7 and overshot the count after three
        # iterations, so the count field said 5 while three elements existed.
        ("positive_step_of_two",
         ["var r = range(0, 10, 2)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[4])"]),
        ("positive_step_uneven_into_the_last_element",
         ["var r = range(0, 10, 3)",
          "printf(\"L%lld %lld %lld %lld\\n\", len(r), r[0], r[2], r[3])"]),
        ("positive_step_of_seven",
         ["var r = range(1, 29, 7)",
          "printf(\"L%lld %lld %lld %lld\\n\", len(r), r[0], r[2], r[3])"]),
        ("positive_step_of_three_from_a_non_zero_start",
         ["var r = range(3, 20, 5)",
          "printf(\"L%lld %lld %lld %lld\\n\", len(r), r[0], r[1], r[3])"]),
        # A step in a NAME, positive and negative. `_static_int` cannot fold
        # either, which is what made the count formula's literal-only negation
        # wrong: `None or 1` is 1, so nothing was negated at all.
        ("step_held_in_a_name",
         ["var s = 3", "var r = range(0, 12, s)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[3])"]),
        ("negative_step_held_in_a_name",
         ["var s = 0 - 3", "var r = range(9, 0, s)",
          "printf(\"L%lld %lld %lld\\n\", len(r), r[0], r[2])"]),
        # EMPTY ranges, all three ways. `range(0, 5, -1)` is the one that exited
        # 1: it is descending AND empty, so the count formula negated a span
        # that was already pointing the wrong way.
        ("empty_by_a_zero_bound", ["printf(\"L%lld\\n\", len(range(0)))"]),
        ("empty_because_the_bounds_are_equal",
         ["var r = range(4, 4)", "printf(\"L%lld\\n\", len(r))"]),
        ("empty_descending_with_the_stop_above_the_start",
         ["var r = range(0, 5, -1)", "printf(\"L%lld\\n\", len(r))"]),
        ("empty_ascending_with_the_stop_below_the_start",
         ["var r = range(5, 0)", "printf(\"L%lld\\n\", len(r))"]),
        ("empty_descending_uneven",
         ["var r = range(10, 3, -2)", "printf(\"L%lld\\n\", len(r))"]),
        ("empty_descending_from_a_negative_step_in_a_name",
         ["var s = 0 - 3", "var r = range(0, 9, s)", "printf(\"L%lld\\n\", len(r))"]),
        # A step of zero is `ValueError` in CPython and a refusal here, on both
        # backends and identically — so it is a `refuse` case, and the needle is
        # the message the emitter already had.
        ("a_step_of_zero_is_refused",
         ["var r = range(0, 5, 0)"], "refuse:range() step must not be zero"),
        # The walk, because `for … in range(…)` is the shape every corpus uses
        # and it is a DIFFERENT loop from materialising the range.
        ("a_for_over_a_negative_step_range_walks_down",
         ["var t = 0",
          "for i in range(5, 0, -1):",
          "    t = t * 10 + i",
          "printf(\"L%lld\\n\", t)"]),
        ("a_for_over_a_positive_step_range",
         ["var t = 0",
          "for i in range(0, 20, 5):",
          "    t = t * 10 + i",
          "printf(\"L%lld\\n\", t)"]),
        ("a_for_over_an_empty_range_binds_nothing",
         ["var i = 7", "var hits = 0",
          "for i in range(0, 5, -1):",
          "    hits = hits + 1",
          "printf(\"L%lld %lld\\n\", hits, i)"]),
        # Two range() calls in ONE function. The x86-64 label table keeps one
        # address per NAME, and a shared label name silently re-points every
        # earlier branch at the LAST range's block — which is why these labels
        # are rid-suffixed. A single-range corpus cannot see that.
        ("two_ranges_in_one_function",
         ["var a = range(3)", "var b = range(0, 9, 2)",
          "printf(\"L%lld %lld %lld\\n\", a[2], b[1], b[4])"]),
        ("a_negative_and_a_positive_range_in_one_function",
         ["var a = range(5, 0, -1)", "var b = range(0, 9, 2)",
          "printf(\"L%lld %lld %lld\\n\", a[0], b[1], len(a))"]),
    ],
)

# ── len ─────────────────────────────────────────────────────────────────────
#
# The one builtin with three lowerings (`model.len_operand_lowering`: a blob's
# count field, a string's `strlen` over a literal, and a folded CODE POINT count
# for a literal whose bytes the build can see), and the third is the one CPython
# disagrees with most often, because a `strlen` counts bytes and `len` counts
# characters. `string_codepoint_verdict` folds the right answer for a literal —
# these cases are what says it still does.
group(
    "len",
    "`len` is the one builtin with THREE lowerings, so it is the one where "
    "CPython's answer and this path's most easily differ: a blob's count field "
    "and a string's `strlen` agree with CPython, and a LITERAL's folded code "
    "point count is the only one that can, because `strlen` counts bytes and "
    "`len` counts characters.",
    [
        ("of_a_list_literal", ["var xs = [1, 2, 3, 4, 5]",
                               "printf(\"L%lld\\n\", len(xs))"]),
        ("of_a_list_of_lists", ["var xs = [[1, 2], [3]]",
                                "printf(\"L%lld\\n\", len(xs))"]),
        ("of_a_dict_literal", ["var d = {\"a\": 1, \"b\": 2}",
                               "printf(\"L%lld\\n\", len(d))"]),
        ("of_a_tuple_literal", ["var t = (1, 2, 3)", "printf(\"L%lld\\n\", len(t))"]),
        ("of_an_empty_list", ["var xs = []", "printf(\"L%lld\\n\", len(xs))"]),
        ("of_a_literal_bound_first",
         ["var xs = [1, 2]", "var n = len(xs)", "printf(\"L%lld\\n\", n)"]),
        # The STRING half. An ASCII literal is the one shape where `strlen` and
        # the character count are the same number, so it is the shape that cannot
        # see the third lowering — which is why the next four are here.
        #
        # **THE CHARACTERS ARE WRITTED OUT, not spelled as `\uXXXX`, and that is
        # a decision rather than a style one.** A `\uXXXX` escape in a literal is
        # not decoded by this tree's lexer, so `len("h\\u00e9llo")` counts TEN
        # characters where CPython counts five — measured on both backends. That
        # is `bugs/LEXER_unicode_escapes_are_not_decoded.md`, it is about the
        # LEXER rather than about `len`, and it is not this table's to fix; a case
        # here that spelled the characters as escapes would be reporting a
        # lexer's bug as a `len` divergence on every row. The UTF-8 bytes are
        # what both engines see either way, so writing them out measures the
        # codepoint fold and leaves the escape where it is filed.
        ("of_an_ascii_literal", ["printf(\"L%lld\\n\", len(\"hello\"))"]),
        ("of_an_empty_literal", ["printf(\"L%lld\\n\", len(\"\"))"]),
        ("of_a_two_byte_character",
         ["printf(\"L%lld\\n\", len(\"h\u00e9llo\"))"]),
        ("of_two_cjk_characters", ["printf(\"L%lld\\n\", len(\"\u65e5\u672c\"))"]),
        ("of_an_astral_character",
         ["printf(\"L%lld\\n\", len(\"a\U0001F600b\"))"]),
        # `len` of a range, INLINE and through a NAME. The second is the shape
        # `kind_of`'s missing row refused: a name bound to a `range(...)` came
        # back an integer, and `len` blamed the integer.
        ("of_a_range_written_inline", ["printf(\"L%lld\\n\", len(range(7)))"]),
        ("of_a_range_through_a_name",
         ["var r = range(3, 8, 2)", "printf(\"L%lld\\n\", len(r))"]),
        ("of_a_negative_step_range_through_a_name",
         ["var r = range(8, 0, -2)", "printf(\"L%lld\\n\", len(r))"]),
        # `len` of a SLICE is a new blob, so it is the third lowering again with
        # a container as the operand.
        ("of_a_slice_of_a_list",
         ["var xs = [1, 2, 3, 4]", "printf(\"L%lld\\n\", len(xs[1:3]))"]),
        ("of_an_open_ended_slice",
         ["var xs = [1, 2, 3, 4]", "printf(\"L%lld\\n\", len(xs[2:]))"]),
    ],
)

# ── min / max ───────────────────────────────────────────────────────────────
#
# `max`/`min` are the ONE builtin family this backend lowers selectively, so they
# are the family where a refusal is a decision rather than a limit: two or more
# POSITIONAL arguments and no keyword are a compare and a select, rewritten by
# `formal/build.py::_lower_builtin_extremum` to the `TernaryExpr` both emitters
# already have. The other three shapes refuse, and `model.extremum_call_is_a_`
# `select` is the ONE place that says which is which.
#
# CPython's fold keeps the FIRST of a tie and replaces it only on a strict `>`,
# so `max(a, b)` is `b > a ? b : a` and not `a < b ? b : a`. The two agree on
# every total order over integers and only a NaN can tell them apart, so the tie
# row is here because "returns the first on a tie" is a real property of the
# answer rather than because it is a discriminating test.
group(
    "minmax",
    "`max`/`min` are the one family this backend lowers SELECTIVELY, so this is "
    "the group where a refusal is a decision: two or more positional arguments "
    "and no keyword are a compare and a select "
    "(`formal/build.py::_lower_builtin_extremum`, rewriting to the `TernaryExpr` "
    "both emitters have), and the other three shapes refuse. "
    "`model.extremum_call_is_a_select` is the one place that says which is "
    "which, and both halves of it are here.",
    [
        ("two_positional_arguments",
         ["var a = 3", "printf(\"L%lld %lld\\n\", min(a, 9), min(9, a))"]),
        ("three_positional_arguments",
         ["var a = 3", "var b = 9",
          "printf(\"L%lld %lld\\n\", max(a, b, 5), min(4, b, a))"]),
        ("of_arithmetic_over_names",
         ["var a = 3", "var b = 9", "printf(\"L%lld\\n\", max(a - 1, b + 1, 0))"]),
        ("over_negatives", ["printf(\"L%lld %lld %lld\\n\", max(0 - 9, 3), "
                            "min(0 - 9, 3), min(3, 0 - 9))"]),
        ("a_tie_returns_the_first",
         ["printf(\"L%lld %lld\\n\", max(5, 5), min(2, 2))"]),
        ("a_four_argument_fold",
         ["printf(\"L%lld %lld\\n\", max(1, 9, 3, 7), min(8, 2, 6, 4))"]),
        # The three shapes the rewrite DECLINES. Each refusal needle is the
        # model's own row, so a refusal that starts naming a different construct
        # fails here rather than passing as a limit.
        ("one_argument_folds_a_sequence",
         ["var xs = [1, 5, 2]", "printf(\"L%lld\\n\", max(xs))"],
         "refuse:`max(...)` is not lowered on this path"),
        ("one_argument_min_folds_a_sequence",
         ["var xs = [4, 2]", "printf(\"L%lld\\n\", min(xs))"],
         "refuse:`min(...)` is not lowered on this path"),
        ("a_key_calls_through_a_value",
         ["var a = 3", "var b = 9",
          "printf(\"L%lld\\n\", max(a, b, key=lambda v: 0 - v))"],
         "refuse:`max(...)` is not lowered on this path"),
        ("a_default_is_a_value_the_empty_sequence_takes",
         ["var xs = []", "printf(\"L%lld\\n\", max(xs, default=0))"],
         "refuse:`max(...)` is not lowered on this path"),
        # The rewrite's own GUARD, which is a decision rather than an accident:
        # an integer literal has to be a BARE one. `a - 1` and `b + 1` say
        # nothing about either operand holding a number, so the rewrite declines
        # — and the run case beside it is the same program with a literal added,
        # which is the whole of the difference between the two answers.
        ("two_arithmetic_expressions_with_no_literal",
         ["var a = 3", "var b = 9", "printf(\"L%lld\\n\", max(a - 1, b + 1))"],
         "refuse:`max(...)` is not lowered on this path"),
        ("the_same_program_with_a_literal_lowers",
         ["var a = 3", "var b = 9", "printf(\"L%lld\\n\", max(a - 1, b + 1, 0))"]),
        # Two names and no literal anywhere: the blob table declines rather than
        # comparing two ADDRESSES, which would answer a different number on each
        # architecture.
        ("two_names_with_no_literal",
         ["var a = 3", "var b = 9", "printf(\"L%lld\\n\", max(a, b))"],
         "refuse:`max(...)` is not lowered on this path"),
        ("a_container_and_a_literal",
         ["var a = [1, 2]", "printf(\"L%lld\\n\", len(max(a, 0)))"],
         "refuse:is refused when the right operand is a list"),
    ],
)

# ── sum / any / all ─────────────────────────────────────────────────────────
#
# Three folds over a sequence with the same shape, and the shape is the reason
# all three refuse: a run-time sequence this one-word value model cannot carry.
# They are in the table because "this is a limit and here it is stated" is worth
# more than silence, and because a fold is the FIRST thing worth lowering if the
# sequence ever becomes a value (the answer is one word, unlike `enumerate`'s).
group(
    "folds",
    "`sum`, `any` and `all` are three folds over a sequence with one shape, and "
    "the shape is why all three refuse: a run-time sequence this one-word value "
    "model cannot carry. They are here because a stated limit is worth more than "
    "a silent one — and because a fold is the FIRST of the three worth lowering, "
    "since its answer is one word where `enumerate`'s is a pair.",
    [
        ("sum_of_a_list", ["var xs = [1, 2, 3]", "printf(\"L%lld\\n\", sum(xs))"],
         "refuse:`sum(...)` is not lowered on this path"),
        ("sum_with_a_start", ["var xs = [1, 2]", "printf(\"L%lld\\n\", sum(xs, 10))"],
         "refuse:`sum(...)` is not lowered on this path"),
        ("sum_of_an_empty_list", ["var xs = []", "printf(\"L%lld\\n\", sum(xs))"],
         "refuse:`sum(...)` is not lowered on this path"),
        ("any_over_a_list_with_a_true_element",
         ["var xs = [0, 0, 1]", "printf(\"L%lld\\n\", any(xs))"],
         "refuse:`any(...)` is not lowered on this path"),
        ("any_over_a_list_of_zeros",
         ["var xs = [0, 0]", "printf(\"L%lld\\n\", any(xs))"],
         "refuse:`any(...)` is not lowered on this path"),
        ("all_over_a_list_with_a_false_element",
         ["var xs = [1, 1, 0]", "printf(\"L%lld\\n\", all(xs))"],
         "refuse:`all(...)` is not lowered on this path"),
        ("all_over_a_list_of_ones",
         ["var xs = [1, 1]", "printf(\"L%lld\\n\", all(xs))"],
         "refuse:`all(...)` is not lowered on this path"),
        ("all_of_an_empty_list_is_true",
         ["var xs = []", "printf(\"L%lld\\n\", all(xs))"],
         "refuse:`all(...)` is not lowered on this path"),
    ],
)

# ── sorted ──────────────────────────────────────────────────────────────────
#
# The one builtin whose refusal reason is about CALLING rather than about a
# container: a sort needs a comparison call per element, and calling through a
# value is not a thing this path can express. `sorted` also has three keyword
# shapes of its own (`key=`, `reverse=`, and the stability property), and all
# four refuse — so the table states the whole surface rather than the one shape
# that happens to be most common.
group(
    "sorted",
    "`sorted` refuses for a reason no other builtin in this table shares: not a "
    "container and not a word count but a CALL PER ELEMENT. A sort compares two "
    "elements, so it needs to call through a value, and a value here is one "
    "64-bit word with no code address in it — the same wall as `map` and "
    "`filter`. Its three keyword shapes are in the table for the same reason the "
    "plain one is: a stated limit is worth more than a silent one, and `reverse=` "
    "is the one that would have been cheapest.",
    [
        ("of_a_list", ["var xs = [3, 1, 2]", "printf(\"L%lld\\n\", len(sorted(xs)))"],
         "refuse:`sorted(...)` is not lowered on this path"),
        ("with_a_key", ["printf(\"L%lld\\n\", sorted([1, 2], key=lambda v: 0 - v)[0])"],
         "refuse:`sorted(...)` is not lowered on this path"),
        ("reversed", ["var xs = [1, 2, 3]",
                      "printf(\"L%lld\\n\", sorted(xs, reverse=True)[0])"],
         "refuse:`sorted(...)` is not lowered on this path"),
        ("of_an_empty_list", ["var xs = []", "printf(\"L%lld\\n\", len(sorted(xs)))"],
         "refuse:`sorted(...)` is not lowered on this path"),
        ("of_strings", ["printf(\"L%lld\\n\", sorted([\"b\", \"a\"])[0])"],
         "refuse:`sorted(...)` is not lowered on this path"),
    ],
)

# ── map / filter ────────────────────────────────────────────────────────────
#
# Both need a call through a value per element, which is the same wall as
# `sorted`'s comparison call, and both are here for the same reason: the refusal
# names the wall rather than the symbol.
group(
    "mapfilter",
    "`map` and `filter` need a call THROUGH A VALUE per element, which is the "
    "same wall as `sorted`'s comparison call and the reason all three refuse. "
    "A `lambda` is the shape that makes it obvious and a bare `len` is the shape "
    "that would not: both are here because the wall is the CALLEE being a value, "
    "not the callee being a function literal.",
    [
        # **NONE OF THESE OBSERVES THE REFUSED VALUE**, and that is what makes
        # them testable: `len(map(len, [1, 2]))` is a `TypeError` in CPython
        # ("object of type 'map' has no len()"), so a case that measured the
        # length would be a case whose ORACLE raises rather than one whose
        # subject refuses — two different things wearing the same row. Binding
        # the result and printing a constant says what the case is about: the
        # CALL is refused, at build time, before its value could exist.
        ("map_over_len", ["var v = map(len, [1, 2])", "printf(\"L%lld\\n\", 1)"],
         "refuse:`map(...)` is not lowered on this path"),
        ("map_over_a_lambda", ["var v = map(lambda v: v + 1, [1, 2])",
                               "printf(\"L%lld\\n\", 1)"],
         "refuse:`map(...)` is not lowered on this path"),
        ("filter_over_none", ["var v = filter(None, [1, 0])",
                              "printf(\"L%lld\\n\", 1)"],
         "refuse:`filter(...)` is not lowered on this path"),
        ("filter_over_a_predicate",
         ["var v = filter(lambda v: v > 1, [1, 2, 3])",
          "printf(\"L%lld\\n\", 1)"],
         "refuse:`filter(...)` is not lowered on this path"),
    ],
)

# ── zip / enumerate / reversed ──────────────────────────────────────────────
#
# Three shapes with two different walls between them, which is why they are one
# group and not three. `zip` and `enumerate` build a container whose SIZE is not
# known until the inputs are read — `zip`'s is the SHORTEST input's length —
# and this path reserves a blob before any code runs. `reversed` copies, which is
# the same run-time-sized-copy gap as `list`. `enumerate` also has a `start=`
# that a two-element blob could carry and `zip` a `strict=` that would need a
# third word for the flag; both are in the table so the whole surface is stated.
group(
    "zipenumerate",
    "`zip`, `enumerate` and `reversed` are three shapes with TWO walls between "
    "them, which is why they are one group. `zip` and `enumerate` build a "
    "container whose element count is not known until the inputs are read — "
    "`zip`'s is the SHORTEST input's length — and a blob is reserved before any "
    "code runs. `reversed` copies, which is the run-time-sized-copy gap `list` "
    "is refused for.",
    [
        ("zip_of_two_lists",
         ["var v = zip([1, 2], [3, 4])", "printf(\"L%lld\\n\", 1)"],
         "refuse:`zip(...)` is not lowered on this path"),
        ("zip_of_uneven_inputs",
         ["var v = zip([1, 2, 3], [4])", "printf(\"L%lld\\n\", 1)"],
         "refuse:`zip(...)` is not lowered on this path"),
        ("zip_strict",
         ["var v = zip([1, 2], [3], strict=True)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`zip(...)` is not lowered on this path"),
        ("zip_longest",
         ["var v = zip([1], [2, 3], fillvalue=0)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`zip(...)` is not lowered on this path"),
        ("enumerate_of_a_list",
         ["var v = enumerate([7, 8])", "printf(\"L%lld\\n\", 1)"],
         "refuse:`enumerate(...)` is not lowered on this path"),
        ("enumerate_with_a_start",
         ["var v = enumerate([7, 8], 3)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`enumerate(...)` is not lowered on this path"),
        ("enumerate_reversed",
         ["var v = enumerate([7, 8], 0, -1)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`enumerate(...)` is not lowered on this path"),
        ("reversed_of_a_list", ["var v = reversed([1, 2, 3])",
                                "printf(\"L%lld\\n\", 1)"],
         "refuse:`reversed(...)` is not lowered on this path"),
        ("reversed_of_a_string", ["var v = reversed(\"abc\")",
                                  "printf(\"L%lld\\n\", 1)"],
         "refuse:`reversed(...)` is not lowered on this path"),
        ("reversed_of_a_range",
         ["var v = reversed(range(4))", "printf(\"L%lld\\n\", 1)"],
         "refuse:`reversed(...)` is not lowered on this path"),
    ],
)

# ── abs / divmod / round / pow ──────────────────────────────────────────────
#
# The four whose absence was SILENT, and they are the only four in this table
# that are a SAFETY property rather than a census: the C library DEFINES all
# four, so the bind audit's provider check (it asked `dlsym`) found a provider,
# the image linked, and what it bound was a different function —
# `int abs(int)` sees the low half of a 64-bit word, and `double pow(double,
# double)`/`double round(double)` are read through an INTEGER return register.
# Measured, both architectures, before they were refused by name:
# `pow(10, 2)` answered 0, `round(7)` answered 7 on arm64 and 0 on x86-64, and
# `abs(2**40+5)` answered 5 on both. They are in
# `model.FOREIGN_ABI_BUILTINS` for that reason and the needle here is the
# sentence that names the C function, so a refusal that stops naming it fails.
group(
    "foreignabi",
    "These four are the only entries in this table that are a SAFETY property "
    "rather than a census. The C library DEFINES `abs`, `pow` and `round`, so "
    "the bind audit's provider check found a provider and the image linked — to "
    "`int abs(int)`, which sees the low half of a 64-bit word, and to `double "
    "pow(double, double)`/`double round(double)`, read through an INTEGER return "
    "register. Measured before they were refused by name: `pow(10, 2)` answered "
    "0, `round(7)` answered 7 on arm64 and 0 on x86-64, `abs(2**40+5)` answered "
    "5 on both. The needle here is the sentence that NAMES the C function, so a "
    "refusal that stops naming it fails.",
    [
        ("abs_of_a_literal", ["printf(\"L%lld\\n\", abs(0 - 5))"],
         "refuse:int abs(int)"),
        ("abs_above_2_31",
         ["printf(\"L%lld\\n\", abs(0 - 1099511627781))"],
         "refuse:int abs(int)"),
        ("abs_of_a_name", ["var a = 0 - 9", "printf(\"L%lld\\n\", abs(a))"],
         "refuse:int abs(int)"),
        ("pow_of_two_literals", ["printf(\"L%lld\\n\", pow(2, 10))"],
         "refuse:double pow(double, double)"),
        ("pow_to_the_zero", ["printf(\"L%lld\\n\", pow(7, 0))"],
         "refuse:double pow(double, double)"),
        ("pow_with_a_negative_exponent",
         ["printf(\"L%lld\\n\", pow(2, 0 - 2))"],
         "refuse:double pow(double, double)"),
        ("round_of_an_integer", ["printf(\"L%lld\\n\", round(7))"],
         "refuse:double round(double)"),
        ("round_to_even_would_be_the_banker_rule",
         ["printf(\"L%lld\\n\", round(5))"],
         "refuse:double round(double)"),
        # `divmod` is in this group because it is refused for a different reason
        # than the other three — a PAIR is two words — and it is here so the
        # "what lowering this would take" answers in one place are all four.
        ("divmod_of_two_positives",
         ["var a, b = divmod(7, 2)", "printf(\"L%lld %lld\\n\", a, b)"],
         "refuse:`divmod(...)` is not lowered on this path"),
        ("divmod_of_a_negative_dividend",
         ["var a, b = divmod(0 - 7, 2)", "printf(\"L%lld %lld\\n\", a, b)"],
         "refuse:`divmod(...)` is not lowered on this path"),
    ],
)

# ── iter / next / slice ─────────────────────────────────────────────────────
#
# Three names about a CURSOR, and the reason all three refuse is the same fact
# stated three ways: an iterator is a sequence AND a position, and a value here
# is one 64-bit word. `for x in xs` is the lowering a cursor exists for — its
# induction variable IS the position — which is why the walk cases in the `range`
# and `container` groups are `run` cases and these are `refuse` ones.
group(
    "cursors",
    "`iter`, `next` and `slice` are three names about a value that needs TWO "
    "words, and that is the whole of why they refuse: an iterator is a sequence "
    "AND a position, and a slice object is three fields. `for x in xs` is the "
    "lowering a cursor exists for — the loop's induction variable IS the "
    "position — so the walks in the other groups are `run` cases and these are "
    "`refuse` ones.",
    [
        ("iter_then_next", ["var it = iter([1, 2, 3])", "printf(\"L%lld\\n\", next(it))"],
         "refuse:`iter(...)` is not lowered on this path"),
        ("next_with_a_default",
         ["var it = iter([1])", "next(it)",
          "printf(\"L%lld\\n\", next(it, 99))"],
         "refuse:`iter(...)` is not lowered on this path"),
        # The needle names `next` and not `iter`, and that is the ORDER the
        # pre-pass walks in: `not_lowered_builtin_refusal` returns on the first
        # name it meets in the function's own node order, and in `next(iter(…))`
        # the outer call comes first. A needle that named `iter` would be
        # asserting an implementation detail of the walk — and would go red if
        # the walk were reordered, with the refusal still naming a builtin.
        ("next_of_an_iterator_expression",
         ["var v = next(iter([1, 2]))", "printf(\"L%lld\\n\", 1)"],
         "refuse:`next(...)` is not lowered on this path"),
        ("a_slice_object", ["var s = slice(1, 3)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`slice(...)` is not lowered on this path"),
        ("a_slice_object_with_a_step",
         ["var s = slice(0, 9, 2)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`slice(...)` is not lowered on this path"),
        # The RUN row that says the refusal is about the OBJECT and not about
        # slicing: `xs[1:3]` lowers and answers CPython's length, and it is in
        # the `len` group too. It is here because the contrast is the point.
        ("slicing_a_list_is_not_the_slice_object",
         ["var xs = [1, 2, 3, 4]", "printf(\"L%lld\\n\", len(xs[0:4:2]))"]),
    ],
)

# ── isinstance / issubclass / type / callable ───────────────────────────────
#
# The runtime-type family. This build DOES classify values — `ValueKinds` reads
# annotations, literals and constructions — but at BUILD time, from the source,
# which is a different question from the one these four ask. That is the whole
# reason each refuses, and it is worth stating in the refusal rather than
# leaving a reader to think the model has no idea what a value is.
group(
    "runtimetype",
    "These four ask a question about a value's type AT RUN TIME. This build "
    "does classify values — `ValueKinds` reads annotations, literals and "
    "constructions — but it does it at BUILD time from the source, which is a "
    "different question. So each refusal says that, rather than leaving a reader "
    "to conclude the model has no idea what a value holds.",
    [
        ("isinstance_of_an_int_literal",
         ["printf(\"L%lld\\n\", 1 if isinstance(3, int) else 0)"],
         "refuse:`isinstance(...)` is not lowered on this path"),
        ("isinstance_of_a_name",
         ["var v = 3", "printf(\"L%lld\\n\", 1 if isinstance(v, int) else 0)"],
         "refuse:`isinstance(...)` is not lowered on this path"),
        ("isinstance_of_a_string_literal",
         ["printf(\"L%lld\\n\", 1 if isinstance(\"s\", str) else 0)"],
         "refuse:`isinstance(...)` is not lowered on this path"),
        ("issubclass_of_two_types",
         ["printf(\"L%lld\\n\", 1 if issubclass(int, int) else 0)"],
         "refuse:`issubclass(...)` is not lowered on this path"),
        ("type_of_an_int_literal", ["printf(\"L%lld\\n\", 1 if type(3) else 0)"],
         "refuse:`type(...)` is not lowered on this path"),
        ("callable_of_a_builtin",
         ["printf(\"L%lld\\n\", 1 if callable(len) else 0)"],
         "refuse:`callable(...)` is not lowered on this path"),
    ],
)

# ── the rest of the namespace ───────────────────────────────────────────────
#
# Everything in CPython's `builtins` this backend neither lowers nor refuses by
# name, grouped by the wall each one is behind. Before 2026-10-05 these reached
# the LINK AUDIT with a message about SYMBOLS, or — worse — reached a refusal
# about something else entirely: `var v = globals(); len(v)` was refused with
# "len() of a value classified as 'int', and an integer has no length", because
# `kind_of` answers INT_KIND for a call it does not recognise, so the build
# blamed `len` for a name it never lowered. Both are failures, and both are what
# the `refuse:` needles below are here to catch.
group(
    "namespace",
    "The rest of CPython's `builtins`: every name this backend neither lowers "
    "nor refuses, now refused BY NAME with what lowering it would take. Before "
    "2026-10-05 these reached the LINK AUDIT — \"the image would bind 1 "
    "symbol(s) that nothing provides: isinstance … bind the name from a library "
    "that provides it\", whose advice is about the link line when no library "
    "provides a Python builtin's semantics — and seven of them were worse than "
    "that, being refused for a construct that was not the problem at all. Each "
    "group below is one wall.",
    [
        # Reflection: a name looked up on a frame whose slots its DECLARATION
        # fixed before any code ran.
        ("getattr", ["var v = getattr(3, \"real\")", "printf(\"L%lld\\n\", 1)"],
         "refuse:`getattr(...)` is not lowered on this path"),
        ("setattr", ["var v = setattr(3, \"x\", 1)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`setattr(...)` is not lowered on this path"),
        ("delattr", ["var v = delattr(3, \"x\")", "printf(\"L%lld\\n\", 1)"],
         "refuse:`delattr(...)` is not lowered on this path"),
        ("hasattr", ["var v = hasattr(3, \"real\")", "printf(\"L%lld\\n\", 1)"],
         "refuse:`hasattr(...)` is not lowered on this path"),
        ("dir", ["var v = dir(3)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`dir(...)` is not lowered on this path"),
        ("vars", ["var v = vars()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`vars(...)` is not lowered on this path"),
        ("super", ["var v = super()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`super(...)` is not lowered on this path"),
        # The interpreter's own tables, as run-time-sized dicts.
        ("globals", ["var v = globals()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`globals(...)` is not lowered on this path"),
        ("locals", ["var v = locals()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`locals(...)` is not lowered on this path"),
        # A second compiler inside an image that is already its output.
        ("compile", ["var v = compile(\"1\", \"s\", \"eval\")", "printf(\"L%lld\\n\", 1)"],
         "refuse:`compile(...)` is not lowered on this path"),
        ("eval", ["var v = eval(\"1 + 1\")", "printf(\"L%lld\\n\", v)"],
         "refuse:`eval(...)` is not lowered on this path"),
        ("exec", ["var v = 0", "exec(\"v = 7\")", "printf(\"L%lld\\n\", v)"],
         "refuse:`exec(...)` is not lowered on this path"),
        # The REPL and the pager.
        ("breakpoint", ["var v = breakpoint()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`breakpoint(...)` is not lowered on this path"),
        ("help", ["var v = help()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`help(...)` is not lowered on this path"),
        # Process state, which is not a fact about the program.
        ("id", ["var v = id(3)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`id(...)` is not lowered on this path"),
        ("input", ["var v = input()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`input(...)` is not lowered on this path"),
        ("quit", ["var v = 0", "quit(0)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`quit(...)` is not lowered on this path"),
        # Strings baked into CPython's own binary, which this build has not got.
        ("copyright", ["var v = copyright()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`copyright(...)` is not lowered on this path"),
        ("credits", ["var v = credits()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`credits(...)` is not lowered on this path"),
        ("license", ["var v = license()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`license(...)` is not lowered on this path"),
        # A rendering whose spelling depends on the value's type.
        ("ascii", ["var v = ascii(3)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`ascii(...)` is not lowered on this path"),
        ("format", ["var v = format(3, \"d\")", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`format(...)` is not lowered on this path"),
        # A fresh object, or a run-time-sized one.
        ("object", ["var v = object()", "printf(\"L%lld\\n\", 1)"],
         "refuse:`object(...)` is not lowered on this path"),
        ("memoryview", ["var v = memoryview(b\"ab\")", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`memoryview(...)` is not lowered on this path"),
        ("frozenset", ["var v = frozenset([1, 2])", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`frozenset(...)` is not lowered on this path"),
        ("complex", ["var v = complex(1)", "printf(\"L%lld\\n\", 1)"],
         "refuse:`complex(...)` is not lowered on this path"),
        # The async cursor: the same two words as `iter`, plus an edge.
        ("aiter", ["var v = aiter([1])", "printf(\"L%lld\\n\", 1)"],
         "refuse:`aiter(...)` is not lowered on this path"),
        ("anext", ["var v = anext(iter([1]))", "printf(\"L%lld\\n\", v)"],
         "refuse:`anext(...)` is not lowered on this path"),
    ],
)

# ── container constructors and text builtins ────────────────────────────────
#
# The last of the namespace, and the group where the ANSWER is a run-time string
# rather than a container: `bin`/`hex`/`oct`/`chr` render into a buffer whose
# size is not known until the value is converted, and a string on this path is
# an interned NUL-terminated literal with nowhere to put a rendered one. The
# `run` rows beside them are the direction that matters — `ord` of a LITERAL
# folds, and `exit` lowers — so the group says which half of each pair is
# answerable instead of only what is not.
group(
    "textbuiltins",
    "The text builtins, where the answer is a RUN-TIME STRING and a string on "
    "this path is an interned NUL-terminated literal with nowhere to put a "
    "rendered one. The `run` rows beside them are the half that matters: `ord` "
    "of a LITERAL folds (`model`'s codepoint fold) and `exit` lowers to a "
    "`SystemExit` status, so this group says which half of each pair is "
    "answerable rather than only what is not.",
    [
        ("bin", ["var v = bin(10)", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`bin(...)` is not lowered on this path"),
        ("hex", ["var v = hex(255)", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`hex(...)` is not lowered on this path"),
        ("oct", ["var v = oct(8)", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`oct(...)` is not lowered on this path"),
        # `chr` and `ord`-of-a-NAME are refused at the EMITTER by
        # `model.text_builtin_refusal`, not at the pre-pass, and their sentences
        # are the better ones — `chr`'s says where the answer would have to live
        # ("a NEW one-character `String`, and a string on this path is a bare
        # `char *`") and `ord`'s says what is missing ("cannot see what character
        # s holds"). So the needles are those sentences' own words rather than
        # the pre-pass's marker, which is the same discipline
        # `model.not_lowered_builtin_refusal`'s docstring applies to
        # `FOREIGN_ABI_BUILTINS`: a pre-pass claiming a name the emitter owns
        # would refuse a program the backend can answer.
        ("chr", ["var v = chr(65)", "printf(\"L%lld\\n\", 1)"],
         "refuse:is a NEW one-character `String`"),
        ("ord_of_a_name", ["var s = \"A\"", "printf(\"L%lld\\n\", 1 if ord(s) else 0)"],
         "refuse:cannot see what character"),
        ("repr", ["var v = repr(12)", "printf(\"L%lld\\n\", len(v))"],
         "refuse:`repr(...)` is not lowered on this path"),
        ("hash_of_an_int", ["printf(\"L%lld\\n\", hash(3))"],
         "refuse:hash(3) is refused"),
        ("hash_of_a_negative_int", ["printf(\"L%lld\\n\", hash(0 - 1))"],
         "refuse:hash(0 - 1) is refused"),
        # The two `run` rows, and both are here because a group of refusals
        # reads as "none of this works" when half of it does.
        ("ord_of_a_literal_folds", ["printf(\"L%lld\\n\", ord(\"A\"))"]),
        ("exit_lowers_to_a_system_exit_status",
         ["printf(\"L%lld\\n\", 1)", "exit(3)"]),
        ("int_of_a_decimal_string", ["printf(\"L%lld\\n\", int(\"42\"))"]),
        ("a_sliced_list_is_a_blob",
         ["var xs = [1, 2, 3]", "printf(\"L%lld\\n\", len(xs[0:2]))"]),
    ],
)

# ── hash, stated rather than skipped ────────────────────────────────────────
#
# Its own group because the reason is a property of the ORACLE and not of this
# backend, which is the one refusal here that is not `NOT_LOWERED_BUILTINS` at
# all: CPython randomises `hash` of a `str` per process unless `PYTHONHASHSEED`
# is fixed, so two runs of one program disagree BY DESIGN and there is nothing
# to compare against. `model.text_builtin_refusal` says so by name. The needle
# quotes its own sentence so the refusal cannot rot into a link-audit message.
group(
    "hashoracle",
    "One group, one case, and the reason it is here rather than skipped is that "
    "the obstacle is a property of the ORACLE: CPython randomises `hash` of a "
    "`str` per process unless `PYTHONHASHSEED` is fixed, so two runs of one "
    "program disagree BY DESIGN and there is nothing stable to compare against. "
    "`model.text_builtin_refusal` already refuses it by name and says so, and "
    "the needle quotes that sentence.",
    [
        ("hash_of_a_string_literal",
         ["printf(\"L%lld\\n\", hash(\"abc\"))"],
         "refuse:CPython RANDOMISES the hash of a `str` per process"),
    ],
)


# ── the harvested half ──────────────────────────────────────────────────────
#
# CPython's own cases, and what the harvest actually yields is the measurement
# `--list` prints. The reason the yield is 189 and not thousands is in this
# file's header: CPython builds its builtin vectors in loops and through
# `self.assertEqual` over computed expectations, so a straight-line constant
# propagator finds a few dozen calls and most of them are `pow`/`round`/`ord`/
# `chr`.
#
# The harvester is `test_formal_hostmods_conformance.py`'s, subclassed only to
# seed every wanted name as already in scope — the language's own namespace is
# the module here, where that file's is an `import`.

_HARVEST_WANTED = (
    "abs", "all", "any", "bin", "bool", "chr", "divmod", "enumerate", "filter",
    "float", "hex", "int", "len", "list", "map", "max", "min", "oct", "ord",
    "pow", "repr", "reversed", "round", "sorted", "sum", "tuple",
)

# CPython's file, found through `import test` so the cases and the oracle come
# from the SAME interpreter. `test_builtin` is a file rather than a package.
_CPY_TEST_DIR = None


def cpython_test_dir():
    global _CPY_TEST_DIR
    if _CPY_TEST_DIR is None:
        try:
            import test as _test
        except ImportError as exc:                     # pragma: no cover
            raise Failure(f"this interpreter has no `test` package ({exc}); the "
                          f"harvested half of this table is generated from "
                          f"CPython's own regression suite and there is nothing "
                          f"to generate it from")
        _CPY_TEST_DIR = os.path.dirname(os.path.abspath(_test.__file__))
    return _CPY_TEST_DIR


def harvested_cases():
    """CPython's own builtin calls, with this process's own answers.

    The harvester is imported, not copied, and the only thing subclassed is the
    BINDING: every wanted name is already in scope here, because for builtins
    the module IS the language's own namespace rather than an `import` of one.

    A harvested case is a `refuse` case, and that is a decision rather than a
    limitation of the harvest: it is a CALL of a builtin this backend does not
    lower, so there is no image to compare against CPython for. The harvest's
    value is therefore COVERAGE OF THE REFUSAL SURFACE — it is how the table
    knows that a name refuses for the model's own stated reason rather than
    through a chokepoint that has never heard of it — and it is reported as such
    by `--list`, which prints the count per builtin.
    """
    from test_formal_hostmods_conformance import _Harvester

    class _BuiltinHarvester(_Harvester):
        def __init__(self, cases, stats):
            super().__init__("builtins", set(_HARVEST_WANTED), cases, stats)
            self.direct = {n: n for n in _HARVEST_WANTED}

    path = os.path.join(cpython_test_dir(), "test_builtin.py")
    check(os.path.isfile(path),
          f"this interpreter's regression suite has no test_builtin.py at "
          f"{path}, so the harvested half of this table is empty and an empty "
          f"table is not a pass")
    stats = {"no argument": 0, "argument not a constant": 0,
             "bytes argument has no representation": 0}
    raw = []
    tree = ast_parse(open(path, encoding="utf-8").read(), path)
    harvester = _BuiltinHarvester(raw, stats)
    harvester.path = "test_builtin.py"
    harvester.body(tree.body, {})

    import builtins as _builtins

    out = []
    seen = set()
    for case in raw:
        name = case["fn"]
        key = (name, repr(case["args"]), repr(sorted(case["keywords"].items())))
        if key in seen:
            continue
        seen.add(key)
        real = getattr(_builtins, name, None)
        if real is None:
            continue
        # CPython's own answer, computed HERE and now: there is no table of
        # expected values in this file, for the reason its header gives. The
        # VALUE and not its `repr` — a caller that compares a case's answer
        # against an image needs the number, and `repr` is a printing concern
        # that would make every harvested answer a string.
        try:
            answer = ("value", real(*case["args"], **case["keywords"]))
        except Exception as exc:                        # noqa: BLE001 — the point
            answer = ("raises", type(exc).__name__)
        out.append({
            "fn": name, "args": case["args"], "keywords": case["keywords"],
            "file": case["file"], "line": case["line"], "answer": answer,
        })
    return out, stats


# ── building and running one case ───────────────────────────────────────────

def mojo_source(lines):
    """The case's own lines, inside `main`.

    Indented by two, which is what this backend's sources use throughout the
    formal corpus. A blank line is dropped, because `test_formal_hostmods_
    conformance.py` measured that a `var` in one body of hundreds of cases is a
    frame-budget refusal and a blank line contributes nothing to that budget.
    """
    body = "\n".join("  " + line if line.strip() else ""
                     for line in lines).rstrip() + "\n"
    return "def main() -> int:\n" + body + "  return 0\n"


def build(src, name, backend, tmpdir):
    path = os.path.join(tmpdir, f"{name}.mojo")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src)
    out = os.path.join(tmpdir, f"{name}.{backend}")
    result = run_fire(["build", "--formal", "--no-prove",
                       f"--backend={backend}", "-o", out, path])
    text = (result.stderr or result.stdout or "").strip()
    return (None, text) if result.returncode else (out, "")


def run_image(image, backend):
    """`(exit status, stdout)` as BYTES.

    Bytes and not text, because "the same bytes" is the claim and decoding is a
    lossy step applied to one side only: a case whose answer is not valid UTF-8
    would decode to a replacement character on one engine and raise on the other,
    and the comparison would then be about the decoder.
    """
    argv = [image] if backend == "arm64" else ["arch", "-x86_64", image]
    result = subprocess.run(argv, capture_output=True, timeout=RUN_TIMEOUT)
    return result.returncode, result.stdout


def cpython_answer(lines, tmpdir, tag):
    path = os.path.join(tmpdir, f"{tag}.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(cpython_source(mojo_source(lines)))
    result = subprocess.run([sys.executable, path], capture_output=True,
                            timeout=RUN_TIMEOUT)
    return result.returncode, result.stdout, result.stderr.decode(
        "utf-8", "replace")


def _case_spec(entry):
    """`(name, lines, kind, needle)` for one declared case.

    A case is `(name, lines)`, `(name, lines, "refuse:needle")` or
    `(name, lines, "refuse:name")`. The two-argument form is a `run` case, and
    the three-argument form's third element is what the refusal must contain —
    which is how a refusal that arrives at the wrong chokepoint fails.
    """
    name, lines = entry[0], entry[1]
    if len(entry) == 2:
        return name, lines, "run", None
    want = entry[2]
    check(want.startswith("refuse:"),
          f"case {name!r}: the third element is {want!r}; it is either absent "
          f"(a run case) or 'refuse:<text the message must contain>'")
    return name, lines, "refuse", want[len("refuse:"):]


def run_group(entry, backends, tmpdir, verbose):
    """One group: every declared case, plus the harvested half."""
    failures = []
    refused = []
    agreed = 0
    cpython_raises = 0
    for case in entry["cases"]:
        name, lines, kind, needle = _case_spec(case)
        want_exit, want_out, err = cpython_answer(lines, tmpdir, name)
        if err.strip() and want_exit != 0:
            # CPython RAISES on this case: `range(0, 5, 0)` is a `ValueError`
            # and `max([1, 2], 0)` is a `TypeError`.
            #
            # For a `refuse` case that is the AGREEMENT, not a problem — both
            # engines decline the program, and the fact that CPython declines it
            # with an EXCEPTION and this path with a build-time sentence is the
            # difference between the two value models, stated rather than hidden.
            # It is counted, because a table of refusals that never said how many
            # of them CPython also refuses would be reporting a smaller number
            # than it measured.
            #
            # **AND THE CASE IS STILL BUILT.** Skipping it would leave a hole the
            # exact size of every case whose CPython side objects, which is the
            # shape of the failure this whole file was written to avoid: a
            # coverage table that quietly stops covering. Only a `run` case gives
            # up here, because a run case is one CPython answers and one it
            # raises on has no oracle to compare against.
            if kind != "refuse":
                failures.append(f"{name}: CPython itself raises "
                                f"({err.strip().splitlines()[-1][:120]}), so "
                                f"there is no oracle for this case; a `run` case "
                                f"is one CPython answers")
                continue
            cpython_raises += 1
        built = {}
        for backend in backends:
            image, text = build(mojo_source(lines), name, backend, tmpdir)
            built[backend] = (image, text)
        if kind == "run":
            if any(image is None for image, _ in built.values()):
                first = next(t for t in built.values() if t[0] is None)[1]
                failures.append(f"{name}: refused to build "
                                f"({_chokepoint(first)}): {first[:160]}")
                continue
            answers = {}
            for backend, (image, _) in built.items():
                answers[backend] = run_image(image, backend)
            arm = answers.get("arm64")
            other = answers.get("x86_64")
            if arm and other and arm != other:
                # Two architectures of ONE language implementation may not
                # disagree, and no oracle can see that class of bug: both would
                # have to be wrong the same way for CPython's answer to match.
                failures.append(f"{name}: the two backends disagree with EACH "
                                f"OTHER — arm64 {arm[1]!r} exit={arm[0]} vs "
                                f"x86-64 {other[1]!r} exit={other[0]}, which no "
                                f"oracle comparison can see")
                continue
            if arm != (want_exit, want_out):
                failures.append(f"{name}: answered {arm[1]!r} exit={arm[0]} "
                                f"where CPython answers {want_out!r} "
                                f"exit={want_exit}")
                continue
            agreed += 1
            if verbose:
                print(f"      {name}: {arm[1]!r}")
            continue
        # A `refuse` case.
        images = [image for image, _ in built.values() if image is not None]
        if images:
            failures.append(f"{name}: BUILT AND RAN where this table requires a "
                            f"refusal naming {needle!r} — a builtin this path "
                            f"does not lower must not answer")
            continue
        messages = {backend: text for backend, (_, text) in built.items()}
        if len(set(messages.values())) > 1:
            failures.append(f"{name}: the two backends refuse DIFFERENTLY, and "
                            f"one message per architecture is the same rule as "
                            f"one answer: {messages}")
            continue
        message = next(iter(messages.values()))
        if needle not in message:
            failures.append(f"{name}: refused at the WRONG chokepoint — the "
                            f"message does not contain {needle!r}, and says "
                            f"instead: {_chokepoint(message)}: {message[:200]}")
            continue
        refused.append((name, needle))
    return agreed, refused, failures, cpython_raises


_LINK_MARK = "would bind"


def _chokepoint(message):
    """Which stage refused, in the vocabulary the corpus uses.

    The link audit's own marker, because a refusal that arrives THERE rather than
    at the model's pre-pass is the failure this table's `refuse:` needles were
    written to catch: it is a fact about SYMBOLS whose advice is about the link
    line, when the truth is that no library on any line provides a Python
    builtin's semantics.
    """
    return "the LINK AUDIT" if _LINK_MARK in message else "a named refusal"


# ── the harvested half, run as its own group ────────────────────────────────

def _names_builtin(message, name):
    """Whether a refusal NAMES `name`, at any of the three chokepoints.

    Three, because this backend has three places that can decline a call and only
    the third is a bug:

      * the pre-pass (`model.not_lowered_builtin_refusal`) — `` `name(...)` is not
        lowered on this path ``;
      * the emitter (`model.builtin_binding_refusal` for `abs`/`pow`/`round`,
        `model.text_builtin_refusal` for `chr`/`hash`) — a sentence carrying the
        name in backticks;
      * the LINK AUDIT, which does NOT name it: that is the failure this whole
        half of the table exists to catch, so a refusal that reaches it is not a
        refusal this predicate accepts.

    A name in the message is checked against the NAME and not against the whole
    row's sentence, because the row's sentence is prose about what lowering
    would take and a future rewording of it must not turn 150 passing cases red.
    """
    if _LINK_MARK in message:
        return False
    return f"`{name}" in message or f"`{name}`" in message


def run_harvested(backends, tmpdir, verbose):
    """CPython's own calls, each held to what THE MODEL says about its name.

    The expectation is read from `formal/model.py` rather than from a list kept
    here, and that is the whole reason this half is a measurement: a hand list
    would be a second answer to "does this path lower `ord`", and it would go
    quiet in the direction that reads well — a case that started answering would
    keep being counted as a refusal, and a case that stopped would keep being
    counted as an answer.

    FOUR verdicts, and the third is the one this table was extended to measure:

      `compared`   the name is LOWERED, the image built, and it printed what
                   CPython prints for the same text. `ord('d')` → 100 is one, and
                   `max(1, 2, 3)` → 3 is another.
      `refused`    the build declined, and the refusal NAMES the builtin. That is
                   the correct answer for most of CPython's builtin namespace on
                   a one-word value model, and it is a refusal that says why.
      `declined`   the model's COARSE rule says the name is lowered and the build's
                   FINER guard declined anyway. Not a failure, and not a pass
                   either: `extremum_call_is_a_select` is arity-only by design
                   (its own docstring says the operand half of the rewrite's
                   guard is deliberately not re-implemented anywhere else), so
                   `max(1, 2.0, 3)` is "lowered" to the census and refused by the
                   build because a `Double` is not a value on this path. Each one
                   is counted with the reason it declined, because a reader asking
                   "does this path lower `max`?" needs to see the three shapes
                   that lower and the ones that do not, not one number.
      `linkaudit`  the build declined at the LINK AUDIT, which does not name the
                   builtin. A FAILURE, and it is what 26 names did before
                   `NOT_LOWERED_BUILTINS` grew on 2026-10-05: refused, and
                   refused TRUE, and its advice about the link line when no
                   library on any line provides a Python builtin's semantics.

    A fifth bucket is SKIPPED, with a counted reason: a case whose CPython answer
    is not one integer cannot be compared, because a case prints one number and
    there is nothing on this path to print a list with.
    """
    import formal.model as M

    cases, stats = harvested_cases()
    check(cases, f"CPython's own test_builtin.py yielded no call this table can "
                 f"use, and an empty table is not a pass — {stats}")
    foreign = M.FOREIGN_ABI_BUILTINS
    lifted = (set(M.EMITTER_BUILTINS) | set(M.LOWERED_CALL_SHAPED_BUILTINS)
              | set(M.INT_TYPE_CTORS) | set(M.IDENTITY_TYPE_CTORS)
              | set(M.BYTE_BLOB_TYPE_CTORS) | {"print", "range", "debug_assert"})
    failures = []
    skipped = {}
    declined = {}
    compared = refused = 0
    for index, case in enumerate(cases):
        name = case["fn"]
        where = f"{case['file']}:{case['line']}"
        # A keyword-only call has no positional text, so the two halves are
        # joined by a comma only when there IS a first half — `pow(, base=2,
        # exp=4)` is a spelling error rather than a case, and it would be refused
        # by the PARSER, which is a fourth chokepoint and the least informative.
        parts = [repr(a) for a in case["args"]]
        parts += [f"{k}={v!r}" for k, v in case["keywords"].items()]
        call = f"{name}({', '.join(parts)})"
        answer = case["answer"]
        # The model's OWN answer to "is this call shape lowered", asked rather
        # than re-derived: `extremum_call_is_a_select` for the two extremums (it
        # is what `formal_proof_breadth.py::_unlowered_builtins_in` asks, and a
        # second arity rule here would be a second thing to go quiet).
        coarse_lowered = (M.extremum_call_is_a_select(
            name, len(case["args"]), len(case["keywords"]))
            or name in lifted)
        comparable = (answer[0] == "value" and isinstance(answer[1], int)
                      and not isinstance(answer[1], bool))
        if coarse_lowered and not comparable:
            skipped["the model says lowered and CPython's answer is not one "
                    "integer, which a one-number case cannot print"] = \
                skipped.get("the model says lowered and CPython's answer is not "
                            "one integer, which a one-number case cannot print",
                            0) + 1
            continue
        if coarse_lowered:
            lines = [f'printf("L%lld\\n", {call})']
        else:
            lines = [f'var v = {call}', 'printf("L%lld\\n", 1)']
        image, message = build(mojo_source(lines), f"h{index}", "arm64", tmpdir)
        if image is not None:
            if not coarse_lowered:
                failures.append(
                    f"CPython's own `{call}` ({where}) BUILT AND RAN, where "
                    f"`model.NOT_LOWERED_BUILTINS` says `{name}` is not lowered")
                continue
            status, out = run_image(image, "arm64")
            want = f"L{answer[1]}\n".encode()
            if out != want or status != 0:
                failures.append(f"CPython's own `{call}` ({where}) answered "
                                f"{out!r} exit={status} where CPython answers "
                                f"{want!r}")
                continue
            compared += 1
            if verbose:
                print(f"      CPython's {call} -> {answer[1]}")
            continue
        # It refused. Three questions, in this order.
        if _LINK_MARK in message:
            failures.append(
                f"CPython's own `{call}` ({where}) was refused at the LINK "
                f"AUDIT, which does not name the builtin: {message[:200]}")
            continue
        if name in foreign:
            needle = M.builtin_binding_refusal(name)
            if needle not in message:
                failures.append(
                    f"CPython's own `{call}` ({where}) is one of "
                    f"`model.FOREIGN_ABI_BUILTINS`, whose refusal must carry the "
                    f"model's own sentence naming the C function, and it does "
                    f"not: {message[:200]}")
                continue
        elif not _names_builtin(message, name):
            failures.append(
                f"CPython's own `{call}` ({where}) was refused without naming "
                f"`{name}`: {message[:200]}")
            continue
        if coarse_lowered:
            key = f"`{name}` — {message[:90]}"
            declined[key] = declined.get(key, 0) + 1
        else:
            refused += 1
    return {"total": len(cases), "compared": compared, "refused": refused,
            "declined": declined, "skipped": skipped, "failures": failures,
            "stats": {k: v for k, v in stats.items() if v}}


def _harvest_report(report):
    """The harvested half's four verdicts, each with its count and its reason.

    Printed rather than summarised in a tally because the interesting number is
    the one a reader has to look up: `declined` says the model calls a shape
    lowered and the build's finer guard says otherwise, and the REASON it gives
    is what lowering that shape would take.
    """
    out = [f"\nharvested from CPython's own test_builtin.py: "
           f"{report['total']} calls — {report['compared']} compared against "
           f"CPython, {report['refused']} refused by name, "
           f"{sum(report['declined'].values())} declined by the build's finer "
           f"guard, {len(report['failures'])} failed"]
    if report["declined"]:
        out.append("  declined, with the reason:")
        for key, count in sorted(report["declined"].items()):
            out.append(f"    {count:3d}  {key}")
    if report["skipped"]:
        out.append("  skipped:")
        for reason, count in sorted(report["skipped"].items()):
            out.append(f"    {count:3d}  {reason}")
    if report["stats"]:
        out.append(f"  not expressible as a literal call: {report['stats']}")
    for line in report["failures"][:20]:
        out.append(f"  FAIL  {line}")
    if len(report["failures"]) > 20:
        out.append(f"  ... and {len(report['failures']) - 20} more")
    return "\n".join(out)


# ── the registry, printed ───────────────────────────────────────────────────

def print_registry():
    """The groups, their sizes, and the census this file is worth."""
    print(f"CPython {sys.version.split()[0]}  "
          f"backends: {', '.join(BACKENDS)}")
    total = 0
    for entry in GROUPS:
        runs = sum(1 for c in entry["cases"] if len(c) == 2)
        refuses = len(entry["cases"]) - runs
        total += len(entry["cases"])
        print(f"\n{entry['name']:14s} {len(entry['cases']):3d} cases "
              f"({runs} answered, {refuses} refused)")
        for line in _wrap(entry["note"]):
            print(f"    {line}")
    print(f"\n{'TOTAL':14s} {total:3d} declared cases over {len(GROUPS)} groups")
    cases, stats = harvested_cases()
    by_fn = {}
    for case in cases:
        by_fn[case["fn"]] = by_fn.get(case["fn"], 0) + 1
    print(f"\nHARVESTED from {os.path.basename(cpython_test_dir())}"
          f"/test_builtin.py: {len(cases)} calls of CPython's own, "
          f"{len(by_fn)} builtins")
    for name, count in sorted(by_fn.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {name:12s} {count}")
    print(f"  not expressible as a literal call: {stats}")


def _wrap(text, width=76):
    words = text.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            yield line
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        yield line


# ── the driver ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("groups", nargs="*", help="group names; default is all")
    parser.add_argument("--only", action="append",
                        help="restrict to these groups (repeatable)")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--list", action="store_true",
                        help="print the registry and the census, build nothing")
    parser.add_argument("--harvested", action="store_true",
                        help="run only the harvested half")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return 0

    names = args.only or args.groups
    entries = [e for e in GROUPS
               if not names or e["name"] in names]
    if names:
        unknown = sorted(set(names) - {e["name"] for e in GROUPS})
        check(not unknown, f"no such group: {', '.join(unknown)}; the groups "
                          f"are {', '.join(e['name'] for e in GROUPS)}")

    backends = list(BACKENDS)
    ok, why = rosetta()
    if not ok:
        print(f"SKIP x86-64: {why} — a machine with no x86-64 support has not "
              f"found a model bug, and a red that says \"Rosetta is missing\" is "
              f"a red nobody acts on")
        backends = ["arm64"]

    tmpdir = tempfile.mkdtemp(prefix="formal_builtins_")
    failed = []
    try:
        if args.harvested:
            report = run_harvested(backends, tmpdir, args.verbose)
            print(_harvest_report(report))
            return 1 if report["failures"] else 0

        total_agreed = total_refused = 0
        for entry in entries:
            agreed, refused, failures, raised = run_group(entry, backends,
                                                          tmpdir, args.verbose)
            total_agreed += agreed
            total_refused += len(refused)
            status = "ok  " if not failures else "FAIL"
            note = (f", of which CPython itself refuses {raised}" if raised
                    else "")
            print(f"{status}  {entry['name']:14s} {agreed} answered, "
                  f"{len(refused)} refused{note}, {len(failures)} failed")
            for line in failures[:12]:
                print(f"        FAIL  {line}")
            if len(failures) > 12:
                print(f"        ... and {len(failures) - 12} more")
            if failures:
                failed.append(entry["name"])
        report = run_harvested(backends, tmpdir, args.verbose)
        print(f"{'ok  ' if not report['failures'] else 'FAIL'}  "
              f"{'harvested':14s} {report['compared']} of CPython's own "
              f"{report['total']} calls compared, {report['refused']} refused "
              f"by name, {len(report['declined'])} shapes declined, "
              f"{len(report['failures'])} failed")
        for line in report["failures"][:8]:
            print(f"        FAIL  {line}")
        if report["failures"]:
            failed.append("harvested")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\nbuiltin conformance: {len(entries) - len(failed)} of "
          f"{len(entries)} groups ok; {total_agreed} cases ANSWER what CPython "
          f"answers and {total_refused} are refused by name"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def ast_parse(text, path):
    import ast
    return ast.parse(text, path)


if __name__ == "__main__":
    sys.exit(main())