#!/usr/bin/env python3
"""Integer semantics on the formal backends, with CPython as the oracle.

CPython's `int` is arbitrary precision. A formal value is ONE 64-bit word
(`doc/ABI.md`, "Scalar types"), so `ADD`/`SUB`/`MUL`/`LSL`/`SDIV` and
`strtoll` answer the result MODULO 2^64 and nothing downstream can tell. Every
divergence that follows from that was measured on this tree, on BOTH
architectures, and each is either refused by the build (with the exact CPython
value) or is a wrong number — this file is the table of which is which, and it
is the reason the refusals in `formal/model.py`'s integer-overflow section say
what they say.

**Why a table and not a pile of cases.** Each row here names an OPERATION and
the input class that separates it from CPython, and the two architectures are
built and RUN for every row, because the defect's worst form is the two of them
disagreeing about the wrong number (`-2**63 // -1` was a wrong number on arm64
and a SIGFPE on x86-64, from one source). A test that compared only the exit
status would call both of those "did not crash" for the second.

**How a row is allowed to pass.** Three answers are correct on this path and a
row must say which it expects, so a refusal cannot pass for a computation and a
computation cannot pass for a refusal:

  * `("value", n)` — the image prints `n` and exits 0. CPython computed it in
    this process, so it is an oracle and not an expectation copied by hand.
  * `("refuse", substring)` — the BUILD refuses, and the message contains
    `substring`. A substring, not the whole text, so a rewording does not break
    every row; but a specific one (`"18446744073709551616"`), so a message that
    stopped carrying the number would.
  * `("trapped", status)` — the image runs and stops with `status`, which is
    `model.INT_OVERFLOW_TRAP_STATUS` / the divide-by-zero status.

**Read integers through `print`, never `printf("%d", …)`.** Measured, both
backends: `printf("%d", 2**62)` prints `0` because libc's `%d` reads a C `int`,
while `%lld` and `print` are right —
`bugs/FORMAL_printf_d_renders_32_bits.md`. Reading a 64-bit answer through
`%d` would have measured that bug instead of the arithmetic, which is why every
`print` below is `print`.

**The `print` spelling.** `print(x)` on this path builds its own format
(`_print_call` chooses `%s` or `%lld` from the operand's kind), so it is the
one output call in this file that is right for every value in every row.

Run:  python3 test_formal_int_semantics.py [-v] [-k SUBSTRING] [--only-row N]
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

#: The status every bounded operation on this path leaves behind. Read out of
#: the model rather than written here, so this file cannot drift from it.
sys.path.insert(0, HERE)
from formal import model as M                                    # noqa: E402

TRAP = M.INT_OVERFLOW_TRAP_STATUS


def prog(body):
    """A whole `main` whose body is `body` (already indented-free lines)."""
    lines = ["def main(n):"] + ["    " + l for l in body.split("\n")] + \
            ["    return 0"]
    return "\n".join(lines) + "\n"


# ── the table ───────────────────────────────────────────────────────────────
#
# (name, body, expectation).  `expectation` is one of the three shapes above.
#
# The expectation's VALUE is computed by this process with Python's own
# operators, so it is the oracle. Where a row cannot be computed by `eval` of a
# literal (a division CPython allows and this target does not, say) the number
# is written out, and the comment says which CPython expression produced it.

ROWS = [
    # ── `+`, `-`, `*`: exact, and the edges ────────────────────────────────
    ("add_small", "print(5 + 7)", ("value", 12)),
    ("add_neg", "print(0 - 7 + 2)", ("value", -5)),
    ("add_edge_max", "print(9223372036854775806 + 1)",
     ("value", 9223372036854775807)),
    ("add_over", "print(9223372036854775807 + 1)",
     ("refuse", "9223372036854775808")),
    ("sub_small", "print(7 - 9)", ("value", -2)),
    ("sub_edge_min", "print(0 - 9223372036854775807 - 1)",
     ("value", -9223372036854775808)),
    ("sub_over", "print(0 - 9223372036854775807 - 2)",
     ("refuse", "-9223372036854775809")),
    ("mul_small", "print(6 * 7)", ("value", 42)),
    ("mul_neg", "print(0 - 4000000000 * 2000000000)",
     ("value", -8000000000000000000)),
    ("mul_edge", "print(3037000499 * 3037000499)",
     ("value", 3037000499 * 3037000499)),
    ("mul_over", "print(4000000000 * 4000000000)",
     ("refuse", "16000000000000000000")),
    # A multiply by 0 and by 1 are the two that must NOT trap at the edge, and
    # they are here because the run-time check that is still missing (see
    # `bugs/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md`) is a
    # high-half compare, and `high == low` is not the test that gets it right.
    ("mul_by_one", "print(9223372036854775807 * 1)",
     ("value", 9223372036854775807)),
    ("mul_by_zero", "print(9223372036854775807 * 0)", ("value", 0)),

    # ── the types that wrap BY DEFINITION, and must keep doing so ──────────
    #
    # A narrow type is a declared bit width and an unsigned 64 is a declared
    # unsigned word; CPython has neither, so there is no source that could be
    # asking for either, and a trap here would be a false refusal. These four
    # rows are the reason `int_overflow_traps` asks about the RESULT type and
    # not about "is this an integer".
    ("int8_wraps", "a: Int8 = 127\nprint(a + 1)", ("value", -128)),
    ("int32_wraps", "a: Int32 = 2147483647\nprint(a + 1)",
     ("value", -2147483648)),
    ("uint64_wraps", "a: UInt64 = 18446744073709551615\nprint(a + 1)",
     ("value", 0)),

    # ── `//` and `%`: Python FLOORS, and one division does not fit ────────
    ("floordiv_pos", "print(7 // 2)", ("value", 3)),
    # The parentheses are load-bearing and the reason is PRECEDENCE, which is
    # not this file's subject but decides what these rows measure: unary minus
    # binds TIGHTER than `//` and `%`, and binary minus binds LOOSER. So
    # `0 - 7 // 2` is `0 - (7 // 2)` = -3 while `(0 - 7) // 2` is -4, and both
    # rows are here because only the parenthesised one is the floor-division
    # case (`model.division_floors`). An unparenthesised row would have passed
    # on a backend that truncated.
    ("floordiv_neg", "print((0 - 7) // 2)", ("value", -4)),
    ("floordiv_negdiv", "print(7 // (0 - 2))", ("value", -4)),
    ("mod_pos", "print(7 % 3)", ("value", 1)),
    ("mod_neg", "print((0 - 7) % 3)", ("value", 2)),
    ("mod_negdiv", "print(7 % (0 - 2))", ("value", -1)),
    # And the unparenthesised spellings, so the precedence itself is pinned:
    # `0 - 7 // 2` is -3 in CPython because `//` binds tighter, and a backend
    # that read it as `(0-7) // 2` would answer -4.
    ("precedence_slash_slash", "print(0 - 7 // 2)", ("value", -3)),
    ("precedence_mod", "print(0 - 7 % 3)", ("value", -1)),
    ("floordiv_zero", "print(7 // 0)", ("trapped", TRAP)),
    ("mod_zero", "print(7 % 0)", ("trapped", TRAP)),
    # `INT64_MIN // -1` is 2**63. arm64 answered the dividend; x86-64's IDIV
    # raised #DE and the image died on SIGFPE. One source, two architectures,
    # one wrong number and one signal.
    ("floordiv_min_by_minus_one",
     "print((0 - 9223372036854775807 - 1) // (0 - 1))",
     ("refuse", "9223372036854775808")),
    # The `%` of the same pair FITS (it is 0), so it must be computed and not
    # refused — the row that keeps the refusal from over-reaching. It is also
    # the one place the two architectures do NOT agree, and the disagreement is
    # the finding rather than a nuisance: x86-64's `IDIV` raises `#DE` on
    # `INT64_MIN % -1` even though the REMAINDER is 0 and fits, so the backend
    # dies on SIGFPE (measured, exit -8) computing a value it could have had.
    # arm64 computes it. The `x86_64` key is that measurement.
    ("mod_min_by_minus_one",
     "print((0 - 9223372036854775807 - 1) % (0 - 1))",
     {"default": ("value", 0), "x86_64": ("trapped", None)}),

    # ── `**` ───────────────────────────────────────────────────────────────
    ("pow_small", "print(3 ** 5)", ("value", 243)),
    ("pow_zero_exp", "print(7 ** 0)", ("value", 1)),
    ("pow_over", "print(2 ** 64)", ("refuse", "18446744073709551616")),
    # 2**63 is the LAST exponent whose answer fits, so it is the row that
    # keeps the refusal from over-reaching by one.
    ("pow_last_fitting", "print(2 ** 62)", ("value", 4611686018427387904)),
    # A negative exponent is a FLOAT in CPython — there is no integer answer to
    # give and this target has no float division, so the `0` this used to
    # materialise was a number the source never wrote.
    ("pow_negative_exp", "print(2 ** (0 - 1))", ("refuse", "NEGATIVE")),
    ("pow_three_arg", "print(pow(2, 10, 1000))", ("refuse", "pow(")),

    # ── `<<` and `>>` ──────────────────────────────────────────────────────
    ("shl_small", "print(1 << 10)", ("value", 1024)),
    ("shl_zero", "print(7 << 0)", ("value", 7)),
    ("shl_edge", "print(1 << 62)", ("value", 4611686018427387904)),
    ("shl_63", "print(1 << 63)", ("refuse", "9223372036854775808")),
    ("shl_64", "print(1 << 64)", ("refuse", "18446744073709551616")),
    ("shl_200", "print(1 << 200)",
     ("refuse", "1606938044258990275541962092341162602522202993782792835301376")),
    ("shl_negative", "print(1 << (0 - 1))", ("refuse", "negative amount")),
    # `>>` SATURATES and 0 IS CPython's answer: `8 >> 64` is 0 and `8 >> 200`
    # is 0. These two rows are the reason the shift refusal is `<<`-only, and
    # they are the rows a "fix" that made the rule uniform would break.
    ("shr_past_width", "print(8 >> 64)", ("value", 0)),
    ("shr_far_past_width", "print(8 >> 200)", ("value", 0)),
    ("shr_negative", "print(0 - 8 >> 2)", ("value", -2)),
    ("shr_negative_far", "print((0 - 8) >> 64)", ("value", -1)),
    ("shr_negative_count", "print(8 >> (0 - 1))",
     ("refuse", "negative amount")),

    # ── the bitwise operators, and unary `-` / `~` ─────────────────────────
    #
    # Every answer here is a function of the same bit positions of in-range
    # operands, so none of them can leave the range and none of them is in
    # `int_overflow_traps`. They are pinned because "the same rule for every
    # operator" is the obvious over-correction, and a trap on `&` would fire on
    # `a & 0xFF` in every program that masks.
    ("bitwise_and", "print(12 & 10)", ("value", 8)),
    ("bitwise_or", "print(12 | 10)", ("value", 14)),
    ("bitwise_xor", "print(12 ^ 10)", ("value", 6)),
    ("bitwise_not", "print(~5)", ("value", -6)),
    ("bitwise_mixed", "print((12 & 10) | (5 ^ 3))", ("value", 14)),
    ("unary_minus", "print(0 - 5)", ("value", -5)),
    # `-2**63` is REPRESENTABLE, so it is computed and not refused — the row
    # that keeps `int_overflow_traps` honest about the boundary itself. (The
    # one operand that does overflow is `-(2**63)`, and a source has to spell it
    # as `0 - 9223372036854775807 - 1 - 9223372036854775807 - 1` to reach it.)
    ("unary_minus_min", "print(0 - 9223372036854775807 - 1)",
     ("value", -9223372036854775808)),

    # ── `int()` conversions ────────────────────────────────────────────────
    ("int_str", 'print(int("123"))', ("value", 123)),
    ("int_str_ws", 'print(int("  41  "))', ("value", 41)),
    ("int_str_base", 'print(int("ff", 16))', ("value", 255)),
    ("int_str_over", 'print(int("9223372036854775808"))',
     ("refuse", "9223372036854775808")),
    ("int_str_neg_over", 'print(int("-9223372036854775809"))',
     ("refuse", "-9223372036854775809")),
    # `strtoll` clamps and sets `errno`, and the endptr is at the end of the
    # string, so BOTH of the parse's own checks pass and the clamp is the
    # answer. That is how `int("9223372036854775808")` printed `-1`.
    ("int_float", "print(int(2.9))", ("value", 2)),
    # `0 - 2.9` is a MIXED expression (an integer literal beside a double) and
    # is refused for that, which is `model.float_binary_refusal`'s question and
    # not this file's. The row is here only to say so: a reader who tried it
    # should find a refusal about MIXING rather than about integer semantics.
    ("int_float_mixed_refused", "print(int(0 - 2.9))",
     ("refuse", "FloatLiteral")),
    # `abs` is refused by NAME (a 32-bit C `int`), not by overflow, and the row
    # pins the refusal rather than the value so a future `abs` cannot be a
    # silent 32-bit truncation.
    ("abs_refused", "print(abs(0 - 5))", ("refuse", "abs(")),

    # ── comparisons, range bounds, len arithmetic ──────────────────────────
    ("cmp_neg_lt", "a = 0 - 3\nif a < 2:\n    print(1)\nelse:\n    print(0)",
     ("value", 1)),
    ("cmp_neg_gt", "a = 0 - 3\nif a > 2:\n    print(1)\nelse:\n    print(0)",
     ("value", 0)),
    ("cmp_neg_neg", "a = 0 - 7\nb = 0 - 9\nif a > b:\n    print(1)\nelse:\n"
     "    print(0)", ("value", 1)),
    ("cmp_uint_signed", "a: UInt32 = 7\nb = 2\nif a > b:\n    print(1)\n"
     "else:\n    print(0)", ("value", 1)),
    ("range_step_sum", "t = 0\nfor i in range(0, 5, 2):\n    t = t + i\n"
     "print(t)", ("value", 6)),
    ("range_negative_step", "t = 0\nfor i in range(5, 0, -2):\n"
     "    t = t + i\nprint(t)", ("value", 9)),
    ("range_len", "print(len(range(0, 10, 3)))", ("value", 4)),
    ("len_plus_one", 'print(len("abc") + 1)', ("value", 4)),
    ("len_negative_index", 'print(len("abcde") - 1)', ("value", 4)),

    # ── `divmod` and `bit_length`: refused by name, and pinned as refusals ──
    # Both are bound to a name before printing: `print` refuses an operand it
    # cannot classify (a `SubscriptExpr`, a `CallExpr`), and that refusal is
    # about PRINT and would otherwise mask the refusal these two rows are
    # measuring.
    ("divmod_refused", "q = divmod(7, 2)[0]\nprint(q)", ("refuse", "divmod")),
    ("bit_length_refused", "b = (5).bit_length()\nprint(b)",
     ("refuse", "bit_length")),

    # ── `/` is the DOCUMENTED int-only truncation, pinned so a "fix" that
    # made it agree with `//` (and disagree with CPython in a new place) fails
    ("slash_truncates", "print((0 - 7) / 2)", ("value", -3)),
]

# ── the rows that PIN the still-wrong answers ───────────────────────────────
#
# Every other row in this file is either right or refused. These are not, and a
# table of integer semantics that quietly omitted them would be a census with
# the failures taken out — which is the thing `CLAUDE.md` calls "a fixed bug
# still listed is indistinguishable from an open one" in its worse form, the
# failure never written down at all.
#
# Each of these asserts the CURRENT answer, with the CPython answer in the
# comment, and each names the bug doc. When the run-time trap lands they become
# `("trapped", TRAP)` and this section is deleted with the doc.
# `INT64_MIN` is 2**63 past the small end, so these are the WRAPPED answers and
# not zeros: an addition of 2**62 + 2**62 is 2**63, which lands on the
# smallest word, and `3000000000 * 3000000000` FITS (9e18 < 9.223e18) so the
# multiply row uses a base just past the boundary.
VARIABLE_ROWS = [
    ("var_add_over", "a = 4611686018427387904\nprint(a + a)",
     ("value", -9223372036854775808), "9223372036854775808"),
    ("var_sub_over", "a = 9223372036854775807\nb = 5\nprint(0 - a - b)",
     ("value", 9223372036854775804), "-9223372036854775809"),
    ("var_mul_over", "a = 4000000001\nprint(a * a)",
     ("value", -2446744065709551615), "16000000008000000001"),
    ("var_mul_fits", "a = 3000000000\nprint(a * a)",
     ("value", 9000000000000000000), "9000000000000000000"),
    ("var_shl_over", "a = 1\nb = 63\nprint(a << b)",
     ("value", -9223372036854775808), "9223372036854775808"),
    # The two architectures do not even fail this one the same way, which is
    # why the expectation is a per-backend dict: arm64's `SDIV` defines the
    # overflowing case as the dividend and answers a number, x86-64's `IDIV`
    # raises `#DE` and the image dies.
    ("var_floordiv_min", "a = 0 - 9223372036854775807 - 1\nb = 0 - 1\n"
     "print(a // b)",
     {"default": ("value", -9223372036854775808),
      "x86_64": ("trapped", None)}, "9223372036854775808"),
    # `strtoll` CLAMPS rather than wrapping: the value that comes back for a
    # string past the top of the range is `LLONG_MAX`, and both of the parse's
    # own checks (no digits consumed / trailing rubbish) pass, so the clamp is
    # the answer. Measured, both backends, exit 0.
    ("var_int_str_over", 's = "9223372036854775808"\nprint(int(s))',
     ("value", 9223372036854775807), "9223372036854775808"),
    ("var_pow_neg", "a = 2\nb = 0 - 1\nprint(a ** b)", ("value", 0), "0.5"),
]

STILL_UNTRAPPED_DOC = (
    "bugs/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md")

# ── the runner ──────────────────────────────────────────────────────────────

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print("FAIL  %s" % what + ((": " + detail) if detail else ""),
              flush=True)
    return bool(ok)


def build_run(tmpdir, name, source, backend):
    """Build `source` for `backend` and RUN the image. Returns (rc, out, err)."""
    src = os.path.join(tmpdir, "%s_%s.py" % (name, backend))
    out = os.path.join(tmpdir, "%s_%s.bin" % (name, backend))
    with open(src, "w") as f:
        f.write(source)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            "--backend=%s" % backend, "-o", out, src]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        return ("BUILD-FAIL", (r.stderr or r.stdout), r.returncode)
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ("RAN", run.stdout.strip(), run.returncode, run.stderr.strip())


def judge(row_name, backend, res, want, want_note=""):
    """One (row, backend) verdict. Returns True when it is what the row wants."""
    kind = res[0]
    tag = "[%s] %s" % (backend, row_name)
    if kind == "BUILD-FAIL":
        text = res[1]
        if want[0] != "refuse":
            return check(False, tag + " builds", text.strip()[-300:])
        return check(want[1] in text, tag + " refuses naming %r" % want[1],
                     text.strip()[-300:])
    _, out, rc, err = res
    if want[0] == "refuse":
        return check(False, tag + " is refused, not answered",
                     "it printed %r and exited %d" % (out, rc))
    if want[0] == "trapped":
        # `None` means "it must NOT exit 0" rather than a named status: the two
        # x86-64 rows above die on SIGFPE, which is a SIGNAL and not the
        # trap status this path uses for everything else, and pinning -8 here
        # would make the row a claim about the signal rather than about the
        # fact that the machine stopped without an answer.
        if want[1] is None:
            return check(rc != 0, tag + " does not exit 0",
                         "exit %d, stdout %r" % (rc, out))
        return check(rc == want[1], tag + " stops with status %d" % want[1],
                     "exit %d, stdout %r" % (rc, out))
    want_s = str(want[1])
    if rc != 0:
        return check(False, tag + " exits 0", "exit %d, stderr %r" % (rc, err))
    got = out.strip()
    return check(got == want_s,
                 tag + " prints %s%s" % (want_s, ("  (CPython: %s)" % want_note)
                                        if want_note else ""),
                 "printed %r" % got)


def _want_for(want, backend):
    """The expectation for one backend, from either a pair or a per-backend map.

    A per-backend map exists for the two rows where the two architectures
    genuinely disagree about a FAILURE rather than about a number — one wraps
    and one raises `#DE` — because "the same expectation on both backends" is
    the property this file exists to keep, and forcing them into one shape
    would hide the two places it does not hold.
    """
    if isinstance(want, dict):
        return want.get(backend, want.get("default"))
    return want


def run_table(tmpdir, rows, only=None, label=""):
    for i, (name, body, want, *rest) in enumerate(rows):
        if only is not None and i != only:
            continue
        note = rest[0] if rest else ""
        source = prog(body)
        for backend in BACKENDS:
            res = build_run(tmpdir, name, source, backend)
            judge(name, backend, res, _want_for(want, backend), note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", dest="substring", default=None)
    ap.add_argument("--only-row", type=int, default=None)
    args = ap.parse_args()

    rows = list(ROWS)
    if not args.substring:
        rows += list(VARIABLE_ROWS)
    elif args.substring in STILL_UNTRAPPED_DOC:
        rows = list(VARIABLE_ROWS)
    else:
        rows = [r for r in rows if args.substring in r[0]]

    with __import__("tempfile").TemporaryDirectory(dir=os.path.join(
            HERE, "build")) as tmpdir:
        run_table(tmpdir, rows, only=args.only_row)

    npass = sum(1 for ok, _ in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print("\n%d/%d checks passed (%d rows x %d backends)"
          % (npass, len(RESULTS), len(rows), len(BACKENDS)))
    if args.verbose:
        for ok, what in RESULTS:
            print("  %s  %s" % ("PASS" if ok else "FAIL", what))
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
