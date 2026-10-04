#!/usr/bin/env python3
r"""Build `formal/hostmods/math.mojo` and RUN it, compared with CPython's `math`.

    python3 test_formal_math.py [-v] [group ...]

Groups: `consts`, `gcd`, `isqrt`, `factorial`, `combperm`, `prod`, `resolve`,
`absent`. With no argument, all.

WHY AN ORACLE AND NOT A TABLE
-----------------------------
Every answer here is a function of its arguments and nothing else, so the
oracle is CPython's `math` **in this process**. Nothing in this file states
what `math.comb(66, 33)` is; it asks. A table would be a second thing to be
wrong, and for this module that is not a hypothetical: `_binom` carries two
separate overflow stories (the multiply-first one that refuses
`comb(2**32, 2)`, which FITS, and the divide-first one that does not), and the
only thing that tells the two apart is a comparison against the real answers.

THE -1 RULE, WHICH IS THE MODULE'S WHOLE DESIGN
----------------------------------------------
CPython's `math` has two ways of declining to answer, and this path has neither
`ValueError` nor an arbitrary-precision integer:

  * a bad argument raises — `math.isqrt(-1)`, `math.comb(5, -1)`,
    `math.factorial(-1)`;
  * a big answer is returned exactly — `math.factorial(21)` needs 66 bits,
    `math.comb(67, 33)` needs 64.

The module answers both with **-1**, and this file's `want()` is where that rule
is written once: a raise becomes -1, and so does an answer outside the signed
64-bit range. That is a real difference from CPython and it is stated in the
module's docstring; what is asserted here is that the module applies the rule to
exactly the pairs CPython applies it to, and that it does not apply it to a
pair whose answer DOES fit — which is the half that is easy to get wrong and
which `_binom`'s divide-first cancellation exists for.

EXHAUSTIVE WHERE EXHAUSTIVE IS AFFORDABLE
------------------------------------------
  * `factorial`: every `n` in -2..90, so the ceiling at 20/21 and everything
    past it are both inside the sweep rather than a corner case.
  * `isqrt`: every `n` in 0..20000, plus for every bit length 1..63 the four
    values that are hardest — `2**b`, `2**b - 1`, `2**b + 1` and `2**b + 2**(b-1)`
    — plus the top of the range. Newton with a bit-length seed is wrong at the
    TOP of the range and nowhere else if it is wrong at all, and 20000 does not
    reach there.
  * `comb`/`perm`: every `(n, k)` with `n` and `k` both in 0..70, which is 5041
    pairs and contains the whole diagonal where the answer stops fitting
    (`comb(66, 33)` fits, `comb(67, 33)` does not, `perm(20, 20)` fits,
    `perm(21, 20)` does not), plus a handful of huge `n` with a small `k`, which
    is the other diagonal and the one that catches a naive overflow check.
  * `gcd`/`lcm`: the full cross product of a corpus of 24 values chosen to
    include both zeros, both signs, consecutive values, a pair of coprimes, a
    pair sharing a large factor, and the top of the range — 576 pairs.
  * `prod`: every list of length 0..4 over a 7-value corpus, which is what makes
    the EMPTY case (`math.prod([])` is 1) and the `start` parameter both
    covered rather than assumed.

BOTH ARCHITECTURES, AND ONE PLACE WHERE THEY CANNOT BE
----------------------------------------------------
The module is pure integer work with no call into the C library at all, so it is
the case where a two-architecture divergence would be a pure lowering bug with
nothing in `math.mojo` to blame. Every group is built and RUN for arm64 and for
x86-64 and both answers are compared with CPython AND with each other.

The `consts` group used to be the one exception, and it was an exception with a
MEASURED reason rather than a skip for convenience: the five float constants are
WORDS on both architectures and are compared on both, and PRINTING a word as a
double was compared on arm64 only, because `printf("%.17g", bits)` printed
`3.1415926535897931` on arm64 and whatever `XMM0` held on x86-64 —
`6.4810864235206578e-314` and `6.4024130938526187e-314` on two runs of the same
image, so not even a stable wrong answer. The whole group is compared on both
now; `model.printf_argument_classes` is what says which operand is a double, and
`encode_movq_xmm_rm64` is what puts it where SysV AMD64 looks for it.
"""
import argparse
import math as CPY
import os
import platform
import struct
import subprocess
import sys
import tempfile

import test_formal_dylib as D        # noqa: E402  (shared two-backend runner)

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300
REC = "@@"

MIN64 = -(2 ** 63)
MAX64 = 2 ** 63 - 1

# The five float constants, as names. Their answers are BIT PATTERNS and the
# oracle for one is `struct.pack('<d', value)` read back as an unsigned 64-bit
# word — which is the interpreter's own conversion, not a decimal this file
# wrote down.
BITS = ["pi", "e", "tau", "inf", "nan"]

# The corpus every `gcd`/`lcm`/`prod` group draws from: both zeros, both signs,
# consecutive values, a coprime pair, a pair with a large common factor, a power
# of two, and the ends of the range. `math.lcm` answers a Python integer, so a
# pair whose lcm does not fit is a -1 here (see `want`), and that has to be in
# the corpus or the rule is untested.
CORPUS = [MIN64, -MAX64, -(2 ** 62), -(2 ** 31), -7, -6, -5, -4, -3, -2, -1,
          0, 1, 2, 3, 4, 5, 6, 7, 2 ** 15, 2 ** 31, 2 ** 32, 2 ** 32 - 1,
          2 ** 62, MAX64]

# `n` and `k` values for `comb`/`perm`: the whole 0..70 square, plus `n` values
# big enough that `comb(2**32, 2)` is in it — the pair that fits and that a
# multiply-first overflow check refuses.
BIG_N = [2 ** 32, 2 ** 40, 2 ** 62, MAX64]

# `n` and `k` values for the sign and shape group. `k` is a SEPARATE, SHORTER
# list than `n` and the reason is about the ORACLE, not about the module:
# `math.perm(2**63 - 1, 2**32)` is a legal call and CPython starts computing
# it — one bignum multiply per `k`, four billion of them — so a corpus that
# crossed the two long lists made this test run for hours instead of seconds.
# (The first version did exactly that, and it is worth recording that the
# module answers that same pair in five iterations: its overflow check is one
# compare per factor, so -1 arrives long before the arithmetic could.) Every
# pair this group DOES sweep has a negative in it or is small, and those are the
# cases where CPython raises rather than grinds.
NEG_N = [-1, -2, -MAX64, 0, 1, 2, 3, 2 ** 32]
NEG_K = [-1, -2, -3, 0, 1, 2, 3]


def mj(v):
    """A Python integer as a Mojo source literal, for the generators here.

    `-2**63` IS THE ONE THAT NEEDS SPELLING OUT, and it is worth saying why
    because the naive form is not a smaller detail: writing `-9223372036854775808`
    into a generated program produced an image that exited 1 having printed
    NOTHING, which is this path's subscript-out-of-range signature rather than a
    diagnostic. `9223372036854775808` is one past the largest word, so the
    literal does not parse to a value and `0 - it` is a negation of a word that
    does not exist. `formal/hostmods/math.mojo`'s own `_MIN_I64` is written the
    same way — `0 - _MAX_I64() - 1` — and this is the test half of the same
    rule.
    """
    if v == MIN64:
        return "(0 - 9223372036854775807 - 1)"
    return str(v)


def want(fn, *args, **kw):
    """CPython's answer for one call, as the module's answer.

    THREE CASES, and the module has to get all three:

      * a value that fits in a signed 64-bit word is itself;
      * a `ValueError` — a negative argument, `isqrt(-1)` — is `-1`, because
        there are no exceptions on this path (FORMAL.md phase 7) and a status is
        what a failure is everywhere in `formal/hostmods/`;
      * a value OUTSIDE that range is also `-1`, because there is no
        representation for a 66-bit integer here. That is `factorial(21)` and
        `comb(67, 33)` and `perm(21, 20)`, and it is the case that separates an
        honest module from one that wraps.

    `OverflowError` is caught for the same reason `ValueError` is: it is CPython
    declining, and the module's answer for declining is -1 either way.

    THE FOURTH CASE IS THE MODULE'S OWN DOMAIN AND IT IS NOT CPYTHON'S: an
    ARGUMENT of `-2**63`, whose magnitude is `2**63` and so is not a value on
    this path. CPython answers `gcd(-2**63, 6)` as 2 and this module answers -1,
    and the test asserts THAT — see `_mag`'s docstring for why a plain negation
    would instead make `gcd` silently wrong for a whole family of inputs rather
    than honestly refusing one. It is the one place in this file where the
    module is deliberately less capable than CPython, and a corpus value is not
    enough on its own: the case has to be asserted, or a future change to
    `_mag` that wraps instead of refusing would go unnoticed on every pair in
    the corpus that happens not to contain `MIN64`.
    """
    if fn in ("gcd", "lcm", "gcdn", "lcmn", "prod"):
        for a in args:
            if isinstance(a, (list, tuple)):
                if MIN64 in a:
                    return -1
            elif a == MIN64:
                return -1
        for v in kw.values():
            if v == MIN64:
                return -1
    try:
        v = getattr(CPY, fn)(*args, **kw)
    except (ValueError, OverflowError):
        return -1
    if v < MIN64 or v > MAX64:
        return -1
    return v


# ── the generated programs ───────────────────────────────────────────────────

def _walk(n, src, count, emit, indent="    "):
    """The loop that walks every list of length `n` over `src`, in order.

    The element STRIKES are what this exists for. `7**n` iterations over `n`
    elements means element `k` advances every `7**(n-1-k)` iterations and wraps
    with `% 7`, and getting the stride wrong is silent: the loop still runs
    `7**n` times and prints the right NUMBER of records, so the only symptom is
    that every answer is the answer for `src[0]`. Both the `gcd` and the `prod`
    generator had that bug independently, the `gcd` one because a runtime
    `n` cannot have compile-time strides, which is why this helper emits ONE
    LOOP PER LENGTH and neither generator loops over the length at run time.

    `src` is the NAME of the list in the generated program and `count` is how
    many values it holds — two separate arguments because the first is a string
    whose length is nothing to do with the second, which is the mistake this
    helper's first version made by computing `len(src)`.
    `emit(letters)` receives the loop body with `a`, `b`, `c`, `d` already bound
    for however many letters `n` needs.
    """
    letters = ["a", "b", "c", "d"][:n]
    out = [indent + "var i = 0",
           indent + "while i < %d:" % (count ** n)]
    for k, letter in enumerate(letters):
        stride = count ** (n - 1 - k)
        if stride == 1:
            out.append(indent + "    var %s = %s[i %% %d]"
                       % (letter, src, count))
        else:
            out.append(indent + "    var %s = %s[(i / %d) %% %d]"
                       % (letter, src, stride, count))
    out.extend(emit(letters))
    out.append(indent + "    i = i + 1")
    return out


def consts_source():
    """The five constants, each printed twice: as a word and as a double.

    The second `printf` is the one that says the module is a MIRROR and not a
    table of numbers: `%.17g` on the bit pattern prints CPython's own `repr` of
    the constant, so the value is read back through the C library and compared
    with the interpreter rather than with a decimal written here.
    """
    lines = ["import math", "", "def main() -> int:"]
    for name in BITS:
        lines.append('    printf("%s_bits=%%lld@@", math.%s_bits())'
                     % (name, name))
    for name in BITS:
        lines.append('    printf("%s=%%.17g@@", math.%s_bits())'
                     % (name, name))
    return "\n".join(lines) + "\n"


def gcd_source():
    """`gcd`/`lcm` over the corpus cross product, and `gcdn`/`lcmn` over lists.

    The list forms take a list LITERAL plus its length, which is the arrangement
    `formal/hostmods/re.mojo`'s `search(out, n, …)` established and the reason
    is in `math.mojo`'s own docstring: a variadic call is a list, and a list
    cannot cross a dylib boundary. Every LENGTH is swept, which is where the
    EMPTY case is — and the empty cases are the two answers most likely to be
    wrong, because they are different identities in the same shape of call:
    `math.gcd()` is 0 and `math.lcm()` is 1.

    ONE LOOP PER LENGTH over a SHORT corpus (the first eight values), and the
    long values appear in the pair cross product instead: a four-deep walk over
    25 values is 390,625 lists and this group is already 625 pairs. See
    `_walk` for why the loops are per length rather than one loop with a
    runtime length.
    """
    lines = [
        "import math",
        "from math import gcd, lcm, gcdn, lcmn",
        "",
        "def pairs() -> int:",
        "    var vs = [%s]" % ", ".join(mj(v) for v in CORPUS),
        "    var i = 0",
        "    while i < %d:" % len(CORPUS),
        "        var j = 0",
        "        while j < %d:" % len(CORPUS),
        '            printf("%d,%d:", i, j)',
        '            printf("%lld:%lld@@", gcd(vs[i], vs[j]), '
        'lcm(vs[i], vs[j]))',
        "            j = j + 1",
        "        i = i + 1",
        "    return 0",
        "",
        "def lists() -> int:",
        "    var v4 = [%s]" % ", ".join(mj(v) for v in CORPUS[:8]),
    ]
    for n in range(0, 5):
        lines.extend(_walk(n, "v4", 8, lambda letters, n=n: [
            ("        var o = [%s]" % ", ".join(letters)) if letters
            else "        var o = [0]",
            '        printf("%d:")' % n,
            '        printf("%%lld:%%lld@@", gcdn(o, %d), lcmn(o, %d))'
            % (n, n),
        ]))
    lines.append("    return 0")
    lines.append("")
    lines.append("def main() -> int:")
    lines.append("    pairs()")
    lines.append("    lists()")
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


def isqrt_source():
    """Every `n` in 0..20000, then the hardest value at every bit length.

    `2**b`, `2**b - 1`, `2**b + 1` and `2**b + 2**(b-1)` for `b` in 1..63, plus
    the very top of the range and the out-of-range values `want()` answers -1
    for. The four-per-bit-length is the part that matters: a Newton
    implementation seeded from `n` instead of from the bit length overflows only
    at the top of the range, and a sweep that stopped at 20000 would call it
    correct.
    """
    hard = []
    for b in range(1, 64):
        for v in (2 ** b - 1, 2 ** b, 2 ** b + 1, 2 ** b + 2 ** (b - 1)):
            if 0 <= v <= MAX64 and v > 20000:
                hard.append(v)
    # `%.17g` of a double is unique and `mj` is about the integer range; both
    # spellings live in this file because both are ways a generated program can
    # be wrong before it runs a single comparison.
    out = [0 - 1, 0 - 70000, MIN64, 0, 1, 2, 3, MAX64, MAX64 - 1] + hard
    lines = [
        "import math",
        "from math import isqrt",
        "",
        "def low() -> int:",
        "    var n = 0",
        "    while n < 20001:",
        '        printf("L%d=%lld@@", n, isqrt(n))',
        "        n = n + 1",
        "    return 0",
        "",
        "def high() -> int:",
        "    var vs = [%s]" % ", ".join(mj(v) for v in out),
        "    var i = 0",
        "    while i < %d:" % len(out),
        '        printf("H%d=%lld@@", i, isqrt(vs[i]))',
        "        i = i + 1",
        "    return 0",
        "",
        "def main() -> int:",
        "    low()",
        "    high()",
        "    return 0",
    ]
    return "\n".join(lines) + "\n", out


def factorial_source():
    """Every `n` in -2..90, so the ceiling at 20/21 is inside the sweep."""
    lines = [
        "import math",
        "from math import factorial",
        "",
        "def main() -> int:",
        "    var n = 0 - 2",
        "    while n < 91:",
        '        printf("%d=%lld@@", n, factorial(n))',
        "        n = n + 1",
        "    return 0",
    ]
    return "\n".join(lines) + "\n"


def combperm_source():
    """`comb` and `perm` over the whole 0..70 square, plus a huge `n`.

    71 x 71 is 5041 pairs and it is the same square for both functions, so the
    program walks `(n, k)` once and prints both answers: the two functions share
    their arguments, their sign rules and their ceiling, and printing them in one
    record makes a difference between them visible as a difference rather than
    as two separate misses.

    The four `BIG_N` values with `k` in 0..5 are the other diagonal. That is
    where `comb(2**32, 2) = 9223372032559808512` lives — an answer that FITS
    and that a multiply-first overflow check refuses, which is the specific
    defect this module's divide-first cancellation exists to prevent.
    """
    ks = list(range(0, 71))
    lines = [
        "import math",
        "from math import comb, perm",
        "",
        "def square() -> int:",
        "    var n = 0",
        "    while n < 71:",
        "        var k = 0",
        "        while k < 71:",
        '            printf("%d,%d:", n, k)',
        '            printf("%lld:%lld@@", comb(n, k), perm(n, k))',
        "            k = k + 1",
        "        n = n + 1",
        "    return 0",
        "",
        "def huge() -> int:",
        "    var ns = [%s]" % ", ".join(mj(v) for v in BIG_N),
        "    var i = 0",
        "    while i < %d:" % len(BIG_N),
        "        var k = 0",
        "        while k < 6:",
        '            printf("H%d,%d:", i, k)',
        '            printf("%lld:%lld@@", comb(ns[i], k), perm(ns[i], k))',
        "            k = k + 1",
        "        i = i + 1",
        "    return 0",
        "",
        "def negative() -> int:",
        '    var neg = [%s]' % ", ".join(mj(v) for v in NEG_N),
        '    var ks = [%s]' % ", ".join(mj(v) for v in NEG_K),
        "    var i = 0",
        "    while i < %d:" % len(NEG_N),
        "        var j = 0",
        "        while j < %d:" % len(NEG_K),
        '            printf("N%d,%d:", i, j)',
        '            printf("%lld:%lld@@", comb(neg[i], ks[j]), '
        'perm(neg[i], ks[j]))',
        "            j = j + 1",
        "        i = i + 1",
        "    return 0",
        "",
        "def main() -> int:",
        "    square()",
        "    huge()",
        "    negative()",
        "    return 0",
    ]
    return "\n".join(lines) + "\n"


def prod_source():
    """`prodn` over every list of length 0..4, for two starts.

    Seven values rather than the 25 the `gcd` group uses, because this is a
    triple nest: 7^4 is 2401 records, and every LENGTH is swept which is where
    the two identities live — `math.prod([])` is 1 (the start), while
    `math.gcd()` is 0 and `math.lcm()` is 1, so the empty product and the empty
    gcd are different answers in the same shape of call.

    ONE LOOP PER LENGTH, for the reason `_walk` gives: a runtime length cannot
    have compile-time strides, and with the strides all 1 every answer came
    back as the answer for `vals[0]` while the record COUNT stayed exactly
    right — which is the shape of a generator bug that looks like a module bug.

    THE START IS A PARAMETER and this group sweeps two of them, 1 and -3,
    because a default argument is not applied across a dylib boundary
    (`FORMAL_default_argument_not_applied_across_a_dylib`) and a caller
    who forgets it gets whatever was in the register.
    """
    vals = [0, 1, 2, 3, 5, -4, 7]
    starts = [1, -3]
    lines = ["import math",
             "from math import prodn",
             "",
             "def main() -> int:",
             "    var vs = [%s]" % ", ".join(mj(v) for v in vals)]
    for st in starts:
        lines.append("    var st = %d" % st)
        for n in range(0, 5):
            lines.extend(_walk(n, "vs", len(vals),
                              lambda letters, n=n, st=st: [
                "        var o = [%s]" % ", ".join(letters) if letters
                else "        var o = [0]",
                '        printf("%%d,%%d:", st, %d)' % n,
                '        printf("%%lld@@", prodn(o, %d, st))' % n,
            ]))
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


# ── build, run, compare ─────────────────────────────────────────────────────

def build(src, name, arch, tmpdir):
    """`fire.py build --formal` of one program on one architecture.

    Only `group_absent` needs this — the other groups go through
    `both_ways`, which is the shared two-architecture runner in
    `test_formal_dylib.py` and which builds AND runs and compares the two
    architectures with each other. Keeping the single-architecture build here as
    well is deliberate: `absent` asserts that a build FAILS, so there is no
    image to run and it is checking a different thing from every other group.
    """
    path = os.path.join(tmpdir, name + ".mojo")
    with open(path, "w") as f:
        f.write(src)
    out = os.path.join(tmpdir, name + "." + arch)
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "--backend=" + arch, "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return r, out


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures this host can run a formal image on.

    `test_formal_dylib.py`'s `rosetta()` is the shared spelling of "and what to
    print if it cannot", and it is shared because three hostmod suites now ask
    the same question and three copies of it would be three places to keep true.
    """
    if not D.host_machine():
        return []
    ok, why = D.rosetta()
    if not ok:
        print(f"note: x86-64 half SKIPPED — {why}")
        return ["arm64"]
    return list(D.BACKENDS)


def both_ways(archs, tmpdir, name, src, fn, verbose, cross=None):
    """Build and run on every architecture in `archs`, and compare them.

    A thin wrapper over `test_formal_dylib.py`'s `build_and_run`, which is where
    that machinery lives for every host module's suite. The wrapper exists for
    two reasons and neither is convenience: the groups here want a NAME and a
    VERBOSE flag rather than a backends tuple, and `consts` needs the `cross`
    filter that `build_and_run` takes. What the wrapper does NOT do is decide
    anything — the cross-architecture comparison, the record split and the "the
    image crashed" report all live in the shared runner, so a second copy of
    them could not drift from the first without being visible.
    """
    if verbose:
        print(f"    building and running on {' and '.join(archs)}")
    try:
        return D.build_and_run(src, name, tmpdir, fn, backends=archs,
                               cross=cross)
    except D.Failure as e:
        raise Failure(str(e)) from None


# ── the groups ──────────────────────────────────────────────────────────────

def group_consts(tmpdir, archs, verbose):
    """The five float constants, as words and as doubles.

    The WORD answers are compared against `struct.pack('<d', v)` read back as an
    unsigned 64-bit integer, and the DOUBLE answers against CPython's own
    `repr` rendered through `%.17g`. Two oracles for one constant, because they
    fail differently: a wrong bit pattern fails the first, and a constant that
    is the right word but the wrong thing printed — a format string off by one
    digit — fails only the second.
    """
    want_bits = {}
    want_dbl = {}
    for name in BITS:
        v = getattr(CPY, name)
        want_bits[name + "_bits"] = str(
            struct.unpack("<Q", struct.pack("<d", v))[0])
        # `%.17g` of a double is unique, so the C library's printf and
        # CPython's `%` formatting produce the same text — see `c_17g`. The
        # oracle is therefore asked, not written down.
        want_dbl[name] = c_17g(v)

    def compare(arch, recs):
        words, doubles = {}, {}
        for rec in recs:
            k, _, v = rec.partition("=")
            (words if k.endswith("_bits") else doubles)[k] = v
        bad = [f"{k}: image {words.get(k)!r}, CPython {v!r}"
               for k, v in want_bits.items() if words.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want_bits)} bit patterns "
                       f"differ from `struct.pack('<d', …)`: " +
                       "; ".join(bad))
        # The PRINTED doubles are compared on BOTH architectures, and they were
        # not for a while: a `double` reaches a SysV variadic callee in XMM0 and
        # an integer in RDI, and nothing on this path moved between them, so
        # `printf("%.17g", bits)` printed whatever XMM0 held — a denormal, and a
        # DIFFERENT one on each run of the same image. The fix is
        # `model.printf_argument_classes` plus one `movq`, and the reason the row
        # lives HERE and not only in a backend's own suite is that this group
        # already asks two oracles of one constant (the word and the rendering)
        # and the rendering half was the half that could not be asked.
        bad = [f"{k}: image {doubles.get(k)!r}, CPython {v!r}"
               for k, v in want_dbl.items() if doubles.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want_dbl)} printed "
                       f"doubles differ from CPython's own value: " +
                       "; ".join(bad))

    both_ways(archs, tmpdir, "math_consts", consts_source(), compare, verbose)
    return True, (f"{len(BITS)} constants agree as bit patterns and as printed "
                  f"doubles on {' and '.join(archs)}")


def c_17g(v):
    """What `printf("%.17g", …)` prints for `v`, as an oracle.

    PYTHON's OWN `%` FORMATTING, not `ctypes` into the C library's `snprintf`,
    and the reason is worth recording because the first version of this helper
    used ctypes and reported five correct answers as wrong: ctypes on arm64
    macOS marshals a double through libffi's variadic path incorrectly for
    `snprintf`, so the C library printed `0` for every one of the five
    constants — a silent wrong answer rather than an error, which is the shape
    that makes a helper dangerous.

    They agree because `%.17g` of a double is UNIQUE: 17 significant digits of
    a correctly-rounded conversion are the same digits whichever correctly-
    rounded implementation produces them, and CPython's `PyOS_double_to_string`
    is correctly rounded. The special values agree too — `%.17g % math.inf` is
    `inf` in both, and `nan` is `nan`.
    """
    return "%.17g" % v


def group_gcd(tmpdir, archs, verbose):
    """`gcd`, `lcm`, `gcdn`, `lcmn` over the corpus cross product and lists."""
    want_pairs = []
    for a in CORPUS:
        for b in CORPUS:
            want_pairs.append(("%d,%d" % (CORPUS.index(a), CORPUS.index(b)),
                               "%d:%d" % (want("gcd", a, b),
                                          want("lcm", a, b))))
    short = CORPUS[:8]
    want_lists = []
    for n in range(0, 5):
        if n == 0:
            # An EMPTY list, and not `[0]`: the program passes length 0, so the
            # list it builds is never read, and the oracle has to be asking
            # about the same thing the call is. `[[0]]` made every empty record
            # report `lcm 0` where the image answered CPython's `lcm()` of 1.
            combos = [[]]
        elif n == 1:
            combos = [[a] for a in short]
        elif n == 2:
            combos = [[a, b] for a in short for b in short]
        elif n == 3:
            combos = [[a, b, c] for a in short for b in short for c in short]
        else:
            combos = [[a, b, c, d] for a in short for b in short
                      for c in short for d in short]
        for lst in combos:
            # The key is `%d` and not `%d:` because the comparison splits each
            # record on its FIRST colon, and the program prints the colon. The
            # first version of this table wrote `"%d:"` and every one of the
            # 4,681 list records reported a key mismatch that looked like a
            # value bug.
            want_lists.append(("%d" % n, "%d:%d" % (
                want("gcd", *lst) if lst else 0,
                want("lcm", *lst) if lst else 1)))

    def compare(arch, recs):
        keys = [r.partition(":")[0] for r in recs]
        vals = [r.partition(":")[2] for r in recs]
        check(len(recs) == len(want_pairs) + len(want_lists),
              f"[{arch}] the image reported {len(recs)} records and the oracle "
              f"expects {len(want_pairs) + len(want_lists)}")
        for i, (key, exp) in enumerate(want_pairs):
            ia, ib = (int(x) for x in key.split(","))
            check(keys[i] == key,
                  f"[{arch}] record {i} is {keys[i]!r}, the corpus order says "
                  f"{key!r} — the program and the oracle are walking "
                  f"different orders, which is a different bug from a wrong "
                  f"answer")
            check(vals[i] == exp,
                  f"[{arch}] gcd/lcm of ({CORPUS[ia]}, {CORPUS[ib]}) is "
                  f"{vals[i]}, CPython says {exp}")
        off = len(want_pairs)
        for i, (key, exp) in enumerate(want_lists):
            check(keys[off + i] == key,
                  f"[{arch}] list record {i} is {keys[off + i]!r}, expected "
                  f"{key!r}")
            check(vals[off + i] == exp,
                  f"[{arch}] gcdn/lcmn over a list of length {key[0]} is "
                  f"{vals[off + i]}, CPython says {exp}")

    both_ways(archs, tmpdir, "math_gcd", gcd_source(), compare, verbose)
    return True, (f"{len(want_pairs)} gcd/lcm pairs and {len(want_lists)} "
                  f"list forms agree with CPython")


def group_isqrt(tmpdir, archs, verbose):
    """`isqrt` over 0..20000 and the hardest value at every bit length."""
    src, out = isqrt_source()

    def compare(arch, recs):
        check(len(recs) == 20001 + len(out),
              f"[{arch}] the image reported {len(recs)} records, expected "
              f"{20001 + len(out)}")
        bad = []
        for i in range(0, 20001):
            rec = recs[i]
            k, _, v = rec.partition("=")
            check(k == "L%d" % i,
                  f"[{arch}] record {i} is {k!r}, expected 'L{i}'")
            exp = str(want("isqrt", i))
            if v != exp:
                bad.append(f"isqrt({i}): image {v}, CPython {exp}")
        for j in range(0, len(out)):
            rec = recs[20001 + j]
            k, _, v = rec.partition("=")
            check(k == "H%d" % j,
                  f"[{arch}] high record {j} is {k!r}, expected 'H{j}'")
            exp = str(want("isqrt", out[j]))
            if v != exp:
                bad.append(f"isqrt({out[j]}): image {v}, CPython {exp}")
        check(not bad, f"[{arch}] {len(bad)} isqrt answers differ from CPython; "
                       f"first three: " + "; ".join(bad[:3]))

    both_ways(archs, tmpdir, "math_isqrt", src, compare, verbose)
    return True, (f"{20001 + len(out)} isqrt answers agree with CPython, "
                  f"including every bit length up to 2**63")


def group_factorial(tmpdir, archs, verbose):
    """`factorial` over every `n` in -2..90, so the ceiling is in the sweep."""

    def compare(arch, recs):
        check(len(recs) == 93,
              f"[{arch}] the image reported {len(recs)} records, expected 93")
        bad = []
        for i, n in enumerate(range(-2, 91)):
            k, _, v = recs[i].partition("=")
            check(k == str(n),
                  f"[{arch}] record {i} is {k!r}, expected {n!r}")
            exp = str(want("factorial", n))
            if v != exp:
                bad.append(f"factorial({n}): image {v}, CPython {exp}")
        check(not bad, f"[{arch}] {len(bad)} factorial answers differ from "
                       f"CPython; first three: " + "; ".join(bad[:3]))

    both_ways(archs, tmpdir, "math_factorial", factorial_source(), compare,
              verbose)
    return True, ("93 factorial answers agree with CPython, including the "
                  "-1 for every n above 20")


def group_combperm(tmpdir, archs, verbose):
    """`comb` and `perm` over the 0..70 square, a huge `n`, and negative pairs."""
    want_sq = []
    for n in range(0, 71):
        for k in range(0, 71):
            want_sq.append(("%d,%d" % (n, k),
                            "%d:%d" % (want("comb", n, k),
                                       want("perm", n, k))))
    want_huge = []
    for i, n in enumerate(BIG_N):
        for k in range(0, 6):
            want_huge.append(("H%d,%d" % (i, k),
                              "%d:%d" % (want("comb", n, k),
                                         want("perm", n, k))))
    want_neg = []
    for i, a in enumerate(NEG_N):
        for j, b in enumerate(NEG_K):
            want_neg.append(("N%d,%d" % (i, j),
                             "%d:%d" % (want("comb", a, b),
                                        want("perm", a, b))))
    allw = want_sq + want_huge + want_neg

    def compare(arch, recs):
        check(len(recs) == len(allw),
              f"[{arch}] the image reported {len(recs)} records, expected "
              f"{len(allw)}")
        bad = []
        for i, (key, exp) in enumerate(allw):
            k, _, v = recs[i].partition(":")
            if k != key or v != exp:
                bad.append(f"{key}: image {k!r}/{v}, CPython {key!r}/{exp}")
        check(not bad, f"[{arch}] {len(bad)} of {len(allw)} comb/perm answers "
                       f"differ from CPython; first three:\n      " +
                       "\n      ".join(bad[:3]))

    both_ways(archs, tmpdir, "math_combperm", combperm_source(), compare,
              verbose)
    return True, (f"{len(allw)} comb/perm pairs agree with CPython, over the "
                  f"whole 0..70 square and a huge n")


def group_prod(tmpdir, archs, verbose):
    """`prodn` over every list of length 0..4, for two starts."""
    vals = [0, 1, 2, 3, 5, -4, 7]
    want_all = []
    for st in (1, -3):
        for n in range(0, 5):
            if n == 0:
                combos = [[]]
            elif n == 1:
                combos = [[a] for a in vals]
            elif n == 2:
                combos = [[a, b] for a in vals for b in vals]
            elif n == 3:
                combos = [[a, b, c] for a in vals for b in vals
                          for c in vals]
            else:
                combos = [[a, b, c, d] for a in vals for b in vals
                          for c in vals for d in vals]
            for lst in combos:
                # `%d,%d` and not `%d,%d:` — see `group_gcd`'s table.
                want_all.append(("%d,%d" % (st, n),
                                 str(want("prod", lst, start=st))))

    def compare(arch, recs):
        check(len(recs) == len(want_all),
              f"[{arch}] the image reported {len(recs)} records, expected "
              f"{len(want_all)}")
        bad = []
        for i, (key, exp) in enumerate(want_all):
            k, _, v = recs[i].partition(":")
            if k != key or v != exp:
                bad.append(f"{key}: image {k!r}/{v}, CPython {key!r}/{exp}")
        check(not bad, f"[{arch}] {len(bad)} of {len(want_all)} prod answers "
                       f"differ from CPython; first three:\n      " +
                       "\n      ".join(bad[:3]))

    both_ways(archs, tmpdir, "math_prod", prod_source(), compare, verbose)
    return True, f"{len(want_all)} prod answers agree with CPython"


def group_resolve(tmpdir, archs, verbose):
    """`math` resolves where `formal/imports.py` says, and left the set."""
    import formal.imports as I
    path = os.path.join(HERE, "formal", "hostmods", "math.mojo")
    check(os.path.isfile(path), "no Mojo source for math")
    got = I.resolve_module_path("math")
    check(got is not None and os.path.samefile(got, path),
          f"import math resolves to {got!r}, not {path!r}")
    check(I.host_module_tier("math") == "",
          "math is still in HOST_MODELLED; its Mojo source exists, so the "
          "entry is now a false statement about the target")
    check(I._is_host_module("math") is False,
          "math is still classified as a host module, which would make "
          "`import math` refuse for a module that now has Mojo source")
    if verbose:
        print("    resolves into formal/hostmods/, out of HOST_MODELLED, out "
              "of the host-module union")
    return True, "math resolves, and left both tiers"


def group_absent(tmpdir, archs, verbose):
    """Every name this module documents as absent, refused BY NAME.

    A CALL, not a bare name: a bare `math.sqrt` is a read of a module-level
    name, refused for a different and vaguer reason that does not name the name
    being asked for.

    The float half is the interesting one, because these are all IN libSystem
    and their absence is NOT about the C library: a `double` does not travel in
    an integer register on either ABI, so `sqrt(x)` here would hand the C
    library a garbage bit pattern. Pinning the refusal is what stops a later
    reader from "fixing" it by adding the libc call.
    """
    absent = [
        "sqrt", "exp", "log", "log10", "log2", "log1p", "expm1", "exp2",
        "pow", "fabs", "floor", "ceil", "trunc", "fmod", "remainder",
        "copysign", "hypot", "dist", "fsum", "modf", "frexp", "ldexp",
        "ulp", "nextafter", "isclose", "isnan", "sin", "cos", "tan", "asin",
        "acos", "atan", "atan2", "sinh", "cosh", "tanh", "asinh", "acosh",
        "atanh", "degrees", "radians", "erf", "erfc", "gamma", "lgamma",
        "cbrt", "fma", "prod",
    ]
    # `prod` IS absent and is the one entry in that list the module renames
    # rather than declines: CPython's is `prod(iterable, start=1)` and this
    # one's is `prodn(vals, n, start)`, because `math.prod` takes a variadic-
    # shaped iterable that would be a list across a boundary. So the entry above
    # is a real gap with a spelling beside it, and the two entry points a caller
    # has are checked as PRESENT rather than absent — a module that had silently
    # added a second spelling of `prod` would pass this group.
    arch = archs[0]
    for name in absent:
        src = ("import math\n\ndef main() -> int:\n"
               f"  math.{name}(1)\n  return 0\n")
        r, _out = build(src, "math_absent_" + name, arch, tmpdir)
        check(r.returncode != 0,
              f"math.{name} resolved, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"math.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    # The renamed entry points, asserted PRESENT — see the comment above.
    for name, arity in (("gcd", 2), ("lcm", 2), ("comb", 2), ("perm", 2),
                        ("factorial", 1), ("isqrt", 1), ("gcdn", 2),
                        ("lcmn", 2), ("prodn", 3)):
        args = ", ".join(["3"] * arity)
        src = f"import math\n\ndef main() -> int:\n  math.{name}({args})\n" \
              "  return 0\n"
        r, _out = build(src, "math_present_" + name, arch, tmpdir)
        check(r.returncode == 0,
              f"math.{name}/{arity} did not build, but the module exports it: "
              f"{(r.stderr or r.stdout).strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused each naming itself, and "
              f"9 renamed entry points confirmed present")
    return True, (f"{len(absent)} absent names refused, and the 9 integer "
                  f"entry points confirmed present")


GROUPS = {
    "consts": group_consts,
    "gcd": group_gcd,
    "isqrt": group_isqrt,
    "factorial": group_factorial,
    "combperm": group_combperm,
    "prod": group_prod,
    "resolve": group_resolve,
    "absent": group_absent,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for nm in names:
        if nm not in GROUPS:
            print(f"ERROR: unknown group {nm!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    archs = backends()
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for nm in names:
            try:
                ok, detail = GROUPS[nm](tmpdir, archs, args.verbose)
            except Exception as e:
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + nm + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(nm)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed "
          f"({', '.join(archs)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
