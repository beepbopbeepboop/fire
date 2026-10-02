"""`math` — the integer-valued functions and the float constants' bit
patterns, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import math` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

WHAT THIS IS: EVERY FUNCTION IN CPython's `math` THAT ANSWERS AN INTEGER
-------------------------------------------------------------------------
CPython's `math` is about seventy names and exactly seven of them — `gcd`,
`lcm`, `isqrt`, `factorial`, `comb`, `perm` and `prod` — can produce an
`int`. Everything else in the module takes a `float` and answers a `float`,
and this path has no float:

  * `formal/arm64_codegen.py`'s `FloatLiteral` arm says it: *"formal is
    int-only; truncate toward zero (matches C cast)"*, and a `Float64` local is
    a 64-bit word like any other. `0.5` in a source file is the integer 0.

  * So `sqrt`, `exp`, `log`, `sin`, `pow`, `fmod`, `hypot`, `dist`, `fsum`,
    `degrees`, `radians`, `atan2` and the rest are not here, and the reason is
    NOT that the C library lacks them: libSystem has every one, and calling it
    would be the obvious implementation. It is that **a double does not travel
    in an integer register on either ABI** — on arm64 a `double` argument
    arrives in `d0` and on SysV x86-64 in `XMM0`, while the only word this path
    can pass is an integer register — so `sqrt(x)` where `x` is this path's
    representation of a double hands the C library a garbage bit pattern and
    gets a plausible wrong answer back. That is the `time.time()` failure shape
    `formal/hostmods/time.mojo` refuses to ship, and it is why
    `time_seconds_bits()` exists there instead of `time_seconds()`.

  * `floor`, `ceil`, `trunc`, `round` and `fabs` are ABSENT for the same
    reason, and their absence is worth stating separately because it looks
    unjust: for an INTEGRAL argument each of them answers the argument. A
    function called `floor` that returns its argument is `copy.copy` — a name
    that promises a transformation and delivers the identity — so these are
    absent rather than approximated. A caller that wants the integer floor of
    an integer has the integer.

WHAT IS HERE, AND WHAT EACH ONE ANSWERS
--------------------------------------
  * `gcd(a, b)` and `gcdn(vals, n)`, `lcm(a, b)` and `lcmn(vals, n)` — CPython
    spells all four `*args`, and a variadic call is a LIST, and a list is a
    frame blob that cannot cross a dylib boundary. So the two-argument form is
    the function and the variadic form is a caller-allocated list plus its
    length, which is the arrangement `formal/hostmods/re.mojo`'s `search(out,
    n, …)` established. `gcdn(vals, 0)` is 0 and `lcmn(vals, 0)` is 1, which
    are CPython's own answers for `math.gcd()` and `math.lcm()`.
  * `isqrt(n)` — exact for every `n` a 64-bit word holds, by Newton's method
    from a bit-length seed, so there is no overflow to guard.
  * `factorial(n)` for `0 <= n <= 20` and **-1 above 20**: `20!` is
    2432902008176640000, which fits, and `21!` needs 66 bits, which is not a
    value on this path. CPython returns an exact arbitrary-precision integer
    and this path cannot, so the answer is a status rather than a wrapped one.
  * `comb(n, k)` and `perm(n, k)` — CPython's answers, including `0` for
    `k > n`, and **-1 for `k < 0`, `n < 0`, and for every `(n, k)` whose
    answer does not fit a 64-bit word**. `math.comb(67, 33)` is 14226520737620288370,
    which is 64 bits; the module detects the overflow as it goes rather than
    wrapping, because a wrapped binomial coefficient is a plausible wrong
    number and the whole of this module's design is to not produce those.
  * `prodn(vals, n, start)` — `math.prod` with the start spelled as a
    parameter, because a default argument is not applied across a dylib
    boundary (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`).
  * `pi_bits()`, `e_bits()`, `tau_bits()`, `inf_bits()`, `nan_bits()` — the
    IEEE-754 BIT PATTERNS of the five constants, which is this path's
    representation of a double and the same one `time.mojo` uses.
    `test_formal_math.py` compares each against `struct.pack('<d', math.pi)`
    — the ORACLE, not a decimal the test wrote.

    **THE WORD IS THE PORTABLE ANSWER; PRINTING IT AS A DOUBLE IS NOT, AND THE
    DIFFERENCE IS AN ABI, NOT A LIMIT OF THIS MODULE.** On arm64 a `double`
    argument and an integer argument both go in the same register number, so
    `printf("%.17g", pi_bits())` prints `3.1415926535897931`. On SysV x86-64
    the double goes in `XMM0` and the integer in `RDI`, and nothing on this
    path moves between them — so the same call prints whatever `XMM0` happened
    to hold, MEASURED as `6.4810864235206578e-314` and `6.4024130938526187e-314`
    on two runs of the same image, i.e. not even the same wrong answer twice.
    Annotating the local `Float64` does not change it (measured: still
    `0.000000`). So: compare the WORDS, and treat the printed form as arm64
    only. The filing is
    `bugs/FORMAL_x86_64_a_float_printf_operand_reads_XMM0.md`, and it is the
    same ABI fact that keeps every float-valued function out of this module —
    `time.mojo`'s `time_seconds_bits()` has the same arm64-only printing
    property and its test has never run on x86-64.

WHAT IS NOT HERE, AND WHY — the absences worth naming
----------------------------------------------------
  * Every float-valued function, for the register reason above. The list is
    long enough that naming it here is the useful form: `acos`, `acosh`,
    `asin`, `asinh`, `atan`, `atan2`, `atanh`, `ceil`, `comb`-adjacent
    `dist`, `copysign`, `cos`, `cosh`, `degrees`, `dist`, `erf`, `erfc`,
    `exp`, `exp2`, `expm1`, `fabs`, `factor`, `floor`, `fmod`, `frexp`,
    `fsum`, `gamma`, `hypot`, `isclose`, `isqrt`'s float neighbours, `ldexp`,
    `lgamma`, `log`, `log10`, `log1p`, `log2`, `modf`, `nextafter`, `perm`'s
    float neighbours, `pow`, `prod`'s float inputs, `radians`, `remainder`,
    `sin`, `sinh`, `sqrt`, `tan`, `tanh`, `trunc`, `ulp`.

  * `nan` is here as `nan_bits()` and NOT as a predicate. There is no
    `isnan` on this path — a caller compares `x == nan_bits()`, which is
    false for a NaN the way it is in CPython, and CPython's own `math.isnan`
    is the honest spelling of that fact. `test_formal_math.py`'s `absent`
    group pins the refusal by name so a future growth of this module is a
    failure and not a surprise.

  * `nextafter`, `frexp`, `ldexp` and `modf` are additionally absent for a
    second reason each: their answer is a TUPLE (`frexp`, `modf`), which is a
    frame blob, and `frexp`'s second component is a mantissa rather than an
    integer.
"""


# ── bit patterns ────────────────────────────────────────────────────────────
#
# A CONSTANT IS A CALL, for the reason `formal/hostmods/os/__init__.mojo` gives
# at length and `formal/hostmods/stat.mojo` repeats: a module-level name is not
# exported as a word across a dylib boundary, so every one of these is a
# zero-argument function.
#
# The values are the IEEE-754 DOUBLE bit patterns, little-endian, and they are
# NOT written here by transcribing `math.pi`'s decimal. They are read off
# CPython with `struct.pack('<d', …)` and `test_formal_math.py` asks CPython
# the same question, so a wrong digit here is a failure with a number in it
# rather than a plausible constant nobody can check. 0x400921FB54442D18 is
# 3.141592653589793, 0x3FFB0A827999ABEA is 2.718281828459045, and 2pi is the
# sum of the two exponents' worth of multiplication nobody on this path can do.

def pi_bits() -> int:
    """`math.pi` as the IEEE-754 bit pattern of a double: 0x400921FB54442D18.

    `printf("%.17g", pi_bits())` prints `3.1415926535897931` on arm64, which is
    CPython's own `repr(math.pi)` with one more digit than a double holds — the
    %.17g is the C library's shortest round-tripping form and CPython's repr is
    the same algorithm, so a program on THIS architecture can show the value by
    asking for it this way rather than needing a float local to hold it. On
    x86-64 the same call prints garbage; the module's docstring has the
    measurement and the reason.
    """
    return 4614256656552045848


def e_bits() -> int:
    """`math.e` as a bit pattern: 0x3FFB0A827999ABEA, or 2.718281828459045."""
    return 4613303445314885481


def tau_bits() -> int:
    """`math.tau` as a bit pattern: 0x400921FB54442D18 + 1 in the exponent
    field, i.e. 6.283185307179586.

    Not computed from `pi_bits()` by arithmetic, and that is deliberate: a
    multiplication of two doubles is exactly the thing this path cannot do, so
    writing `2 * pi_bits()` here would be a bit-pattern function pretending to
    be an arithmetic one. The number is the measured one.
    """
    return 4618760256179416344


def inf_bits() -> int:
    """`math.inf` as a bit pattern: 0x7FF0000000000000.

    The signless infinity, which is what `math.inf` is; `-math.inf` is
    `0xFFF0000000000000` and a program can get it by flipping the top bit,
    which is an integer operation this path does have.
    """
    return 9218868437227405312


def nan_bits() -> int:
    """`math.nan` as a bit pattern: 0x7FF8000000000000.

    THE MEASURED ONE, and the word "measured" is doing work: CPython's `nan` is
    a specific quiet NaN with this payload, and the platform's `NAN` macro is
    not guaranteed to be the same word. `test_formal_math.py` asks
    `struct.pack('<d', math.nan)` rather than trusting this comment, which is
    the only reason a difference between the two would be caught.

    There is no `isnan` here; a caller compares against this value, and that
    comparison is FALSE for a NaN exactly as it is in CPython, which is why
    CPython has `isnan` and this module does not need it to answer the same
    question.
    """
    return 9221120237041090560


# ── the integer functions ───────────────────────────────────────────────────
#
# Everything below is exact integer arithmetic in one 64-bit word. There is no
# float anywhere in this half, which is why the half is here at all.

def _gcd2(a, b) -> int:
    """Euclid, on values already made absolute."""
    while b != 0:
        var t = a % b
        a = b
        b = t
    return a


def gcd(a, b) -> int:
    """`math.gcd(a, b)`: the greatest common divisor of two integers.

    CPython's own algorithm is Euclid on absolute values, with the C fast path
    for the two-operand case, and the answer is never negative. `gcd(0, 0)` is
    0 and `gcd(0, n)` is `|n|`, both measured.

    **-1 when either argument is `-2**63`**, whose magnitude is `2**63` and so
    is not a value on this path — so `gcd(-2**63, 6)`, which CPython answers as
    2, has no answer here. That is a limitation of the REPRESENTATION rather
    than of Euclid, and it is stated rather than papered over with a wrap: the
    alternative is a plain negation returning `-2**63` for it, which then reads
    as "smaller than everything" and makes `gcd` silently wrong for a whole
    family of inputs instead of honestly refusing one. See `_mag`.
    """
    if _mag(a) < 0 or _mag(b) < 0:
        return 0 - 1
    return _gcd2(_mag(a), _mag(b))


def gcdn(vals, n) -> int:
    """`math.gcd(*vals)`: the gcd of a list of integers, in list order.

    `n` is the list's length and is a PARAMETER because a list on this path is
    a plain array with no readable count (`formal/hostmods/re.mojo`'s `_fits`
    says why in one sentence, and this is the same arrangement). `gcdn(vals, 0)`
    is 0, which is `math.gcd()`'s own answer for no arguments at all — measured,
    not assumed, because a fold that starts at 1 would give 1 there and a fold
    that starts at 0 is the one CPython actually does.
    """
    if n <= 0:
        return 0
    var g = 0
    var i = 0
    while i < n:
        var v = _mag(vals[i])
        if v < 0:
            return 0 - 1
        g = _gcd2(g, v)
        i = i + 1
    return g


def lcm(a, b) -> int:
    """`math.lcm(a, b)`: the least common multiple of two integers.

    `a / gcd(a, b) * b` and NOT `a * b / gcd(a, b)`, and the order is the whole
    answer: CPython's own source computes it that way, and the reason is
    overflow — with the multiplication first, `lcm(2**62, 2**62 - 1)` needs 124
    bits where the correct answer needs 63, and a two's-complement machine wraps
    to a negative number. `lcm(0, n)` is 0 for every `n`, and `lcm(0, 0)` is 0
    too; the first factor being 0 is what produces both, with no special case.

    **AND -1 WHEN THE ANSWER DOES NOT FIT**, which the ordering above does not
    make unnecessary — it only makes the check cheap. `lcm(2**63 - 1, 2**62)` is
    124 bits, and CPython returns it exactly as a Python integer; the product
    here wraps, and a wrapped lcm is a NEGATIVE number where CPython's is
    positive, which is the loudest possible wrong answer and still a wrong one.
    The check is `|a| / g > max / |b|`, which is exact for the same reason
    `_binom`'s is: `q <= floor(max / b)` implies `q * b <= max`.
    Measured, because the first version of this function had no check and
    `test_formal_math.py`'s corpus pair `(-2**63 + 1, -2**62)` reported
    `-4611686018427387904` against CPython's "does not fit".

    -1 for a `-2**63` argument, for the reason `gcd` above gives.

    **THE ZERO IS CHECKED BEFORE THE DIVISION, AND THAT IS A CRASH IF IT IS
    NOT.** `lcm(x, 0)` is 0 for every `x`, and the natural spelling —
    `_gcd2(x, 0)` is `x`, so `x / gcd` is 1 and `max / 0` is where it dies. A
    divide-by-zero on this path is a `SIGFPE`, and because stdout is
    block-buffered when it is a pipe or a file the process takes the whole
    buffered output with it: a program whose only defect is one `lcm(x, 0)` call
    exits 1 having printed NOTHING, which reads as a compiler crash rather than
    as the arithmetic error it is. Measured: a flat program of sixteen literal
    `gcd`/`lcm` calls over 0..3 exits 0 for all fifteen pairs and exits 1 with no
    output at `lcm(3, 0)`.
    """
    var ua = _mag(a)
    var ub = _mag(b)
    if ua < 0 or ub < 0:
        return 0 - 1
    if ua == 0 or ub == 0:
        return 0
    var g = _gcd2(ua, ub)
    var x = ua / g
    if x > _MAX_I64() / ub:
        return 0 - 1
    return x * ub


def lcmn(vals, n) -> int:
    """`math.lcm(*vals)`: the lcm of a list of integers, in list order.

    `lcmn(vals, 0)` is 1, which is `math.lcm()`'s own answer for no arguments:
    the fold starts at 1 because 1 is the identity of lcm, while the identity
    of gcd is 0. Getting that backwards gives 0 for the empty case, which is a
    plausible wrong answer for exactly one input.

    **-1 as soon as one step would not fit**, for the reason `lcm` above gives,
    and the fold STOPS there rather than continuing with a wrapped value: a
    subsequent gcd of a wrapped intermediate is a gcd of a number that does not
    exist, so continuing would make the -1 depend on the list's order. CPython
    keeps going with bignums, so `lcmn` here answers -1 for a list whose lcm is
    larger than a word and the exact value for one that is not — the same rule
    `factorial` and `_binom` follow.
    """
    var r = 1
    var i = 0
    while i < n:
        var v = _mag(vals[i])
        if v < 0:
            return 0 - 1
        if r == 0 or v == 0:
            r = 0
        else:
            var g = _gcd2(r, v)
            var x = r / g
            if x > _MAX_I64() / v:
                return 0 - 1
            r = x * v
        i = i + 1
    return r


def _bit_length(v) -> int:
    """How many bits `v` needs, for `v >= 1`.

    Counted DOWN from 63, which is a plain 64-iteration loop rather than a
    binary search: this is called once per `isqrt` and the whole of `isqrt` is
    about being right at the top of the range, not about being quick. `v == 0`
    is 0 and a negative `v` is 0 as well, because every caller has already
    rejected one.
    """
    var n = 0
    var i = 63
    while i >= 0:
        if v >= (1 << i):
            n = i + 1
            i = 0 - 1
        i = i - 1
    return n


def isqrt(n) -> int:
    """`math.isqrt(n)`: the exact integer square root, `floor(sqrt(n))`.

    NEWTON, seeded from the BIT LENGTH rather than from `n` itself, and the
    seed is the part that matters: seeding from `n` overflows at the top of the
    range, because the first iterate is `(n + n/n) / 2 = n + 1` and `n + 1` is
    not a word when `n` is `2**63 - 1`. The seed `2**ceil(bits/2)` is at most
    `2**32` for any `n` this path holds and is at most twice `sqrt(n)`, so every
    subsequent `(x + n/x) / 2` is a sum of two words each below `2**33` and the
    arithmetic cannot overflow. Newton from above converges monotonically to
    `floor(sqrt(n))` under integer division, and the loop stops on the first
    iterate that does not decrease — `isqrt(0)` is 0 and `isqrt(1)` is 1
    because the seed is already the answer.

    **-1 for `n < 0`**, where CPython raises `ValueError`. There are no
    exceptions on this path (FORMAL.md phase 7), so a status is the answer,
    and -1 is not a square root of anything.

    Exact for every `n` in 0..2**63-1; `test_formal_math.py` compares every
    one of them against `math.isqrt` — the full range, because this is the one
    function in the module where a seed that is off by one gives a plausible
    wrong answer for most inputs and a wrong one for none, and only the top of
    the range is where it shows.
    """
    if n < 0:
        return 0 - 1
    if n < 2:
        return n
    var x = 1 << ((_bit_length(n) + 1) / 2)
    while True:
        var y = (x + n / x) / 2
        if y >= x:
            return x
        x = y


def factorial(n) -> int:
    """`math.factorial(n)`, for `0 <= n <= 20`. **-1 outside that.**

    `0!` and `1!` are 1, and the loop is written to produce both without a
    special case: it starts at 2 and the answer starts at 1.

    The ceiling is 20 and it is not a choice: `20!` is 2432902008176640000,
    which fits a 64-bit word, and `21!` needs 66 bits. CPython returns an exact
    arbitrary-precision integer there and this path has no representation for
    it, so `factorial(21)` is -1 rather than a wrapped number. `20!` is the
    largest and `math.factorial(21).bit_length() == 66` is the measurement the
    ceiling is read off.
    """
    if n < 0:
        return 0 - 1
    if n > 20:
        return 0 - 1
    var r = 1
    var i = 2
    while i <= n:
        r = r * i
        i = i + 1
    return r


def _binom(n, k) -> int:
    """The exact `C(n, k)` as a 64-bit word, or -1 when it does not fit.

    THE MULTIPLICATIVE FORM, `C(n, i) = C(n, i-1) * (n - i + 1) / i`, and it is
    that form rather than a factorial ratio for two reasons: it never needs a
    factorial — so `comb(67, 33)` is not blocked by `factorial`'s ceiling of 20
    — and every partial result is an integer, so there is no rounding to go
    wrong at any step.

    **THE DIVISION IS DONE FIRST, AND THAT IS THE WHOLE OF THE OVERFLOW
    STORY.** The obvious loop checks `r > max / (n - i + 1)` before multiplying,
    and it is wrong in a way that shows up on a real case: `math.comb(2**32, 2)`
    is 9223372032559808512, which FITS, and the naive check refuses it at
    `i == 2` because `r * (n - i + 1)` is `2**64` even though `r * (n - i +
    1) / i` is not. So each step cancels first — `g = gcd(n - i + 1, i)`, and
    the step becomes `(r / i') * (n - i + 1)'` with the two factors coprime. And
    once they are coprime the division is EXACT before it happens, because
    `r * a / b` is an integer and `gcd(a, b) == 1` forces `b` to divide `r` —
    which is not a hope, it is what coprimality means, so `(r / b) * a` loses
    nothing. The check is then on `q > max / a` with `q = r / b` already
    divided, and no product in this function can overflow at all.

    That check is also EXACT and not conservative: `q > floor(max / a)` is
    `q * a > max`, because `q <= floor(max / a)` implies
    `q * a <= floor(max / a) * a <= max`. So a pair whose answer fits is never
    refused, which is the property the naive check does not have.

    The loop is bounded in practice even for enormous `k`, and does not need a
    `k` cutoff to be safe: `C(n, i)` grows, so the check fires within about 34
    steps for any pair whose answer does not fit. The cutoff is worth knowing
    rather than relying on: `k > 33` cannot fit at all, because
    `C(2k, k) > 2**63 - 1` from `k == 34` on (`C(66, 33)` is 7219428434016265740
    and fits; `C(68, 34)` is 28453041475240576740 and does not) and
    `C(n, k) >= C(2k, k)` for every `n >= 2k`.
    """
    if n < 0 or k < 0:
        return 0 - 1
    if k > n:
        return 0
    if k > n - k:
        k = n - k
    if k == 0:
        return 1
    var max = _MAX_I64()
    var r = 1
    var i = 1
    while i <= k:
        var a = n - i + 1
        var b = i
        var g = _gcd2(a, b)
        a = a / g
        b = b / g
        var q = r / b
        if q > max / a:
            return 0 - 1
        r = q * a
        i = i + 1
    return r


def comb(n, k) -> int:
    """`math.comb(n, k)`: how many ways to choose `k` of `n` WITHOUT ORDER.

    `comb(n, 0)` and `comb(n, n)` are 1, `comb(n, k)` is 0 for `k > n` (there is
    no such thing as choosing five of three — CPython answers 0 rather than
    raising, measured), and everything else is `_binom`'s exact value.

    **-1** for `k < 0`, for `n < 0`, and for every `(n, k)` whose answer needs
    more than 64 bits. CPython raises `ValueError` for the first two and
    returns an exact arbitrary-precision integer for the third; there are no
    exceptions here (FORMAL.md phase 7) and no representation for a 66-bit
    number, so both are a status. `math.comb(67, 33)` is the first pair over
    the line: 14226520737620288370 needs 64 bits and `comb(66, 33)` is
    7219428434016265740, which fits — so the ceiling is a property of the pair
    and not of either argument, which is why the module detects it as it
    multiplies rather than testing `n` against a number.
    """
    return _binom(n, k)


def perm(n, k) -> int:
    """`math.perm(n, k)`: how many ways to take `k` of `n` IN ORDER.

    THE PRODUCT, `perm(n, k) = n * (n-1) * … * (n-k+1)`, rather than
    `comb(n, k) * k!`. The two are equal and the product is the honest spelling
    here: it needs no binomial coefficient and no factorial, so it does not
    inherit either one's ceiling, and the overflow check is one compare per
    factor (`p > max / factor`) with no division to get wrong.

    `perm(n, 0)` is 1 for every `n >= 0` — there is exactly one way to choose
    nothing — and `perm(n, k)` is 0 for `k > n`, because there is no such thing
    as taking five of three. Both are CPython's own answers, measured rather
    than inferred from the formula, and both are the two places where a
    binomial-based spelling would have gone wrong first.

    **-1** for `k < 0`, for `n < 0`, and for every pair whose answer needs more
    than 64 bits — `perm(21, 20)` is 51090942171709440000, which is 66 bits.
    """
    if n < 0 or k < 0:
        return 0 - 1
    if k > n:
        return 0
    var max = _MAX_I64()
    var p = 1
    var i = 0
    while i < k:
        var f = n - i
        if p > max / f:
            return 0 - 1
        p = p * f
        i = i + 1
    return p


def prodn(vals, n, start) -> int:
    """`math.prod(vals, start)`: the product of a list of integers.

    THE START IS A PARAMETER and not a default, for the reason
    `formal/hostmods/time.mojo` states: a call into another image does not
    materialize the callee's defaults, so a default here would read whatever
    the caller last left in the register
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). CPython's
    default is 1, so a caller who wants it passes 1.

    `prodn(vals, 0, s)` is `s`, which is the identity of the product and is
    what CPython gives for an empty iterable.

    **-1 when a step would not fit**, and it stops there: `math.prod` returns an
    exact Python integer for every input and a wrapped product is a number of
    the wrong sign, which for a product is a wrong answer about every factor
    above the one that overflowed.

    THE CHECK IS `_mul_ok` AND NOT `r > max / f`, because a factor may be
    NEGATIVE and `max / (-4)` is a negative number, against which every
    positive running product "overflows". `_mul_ok` handles the four sign cases
    and is documented there.
    """
    var r = start
    var i = 0
    while i < n:
        var f = vals[i]
        if _mul_ok(r, f) == 0:
            return 0 - 1
        r = r * f
        i = i + 1
    return r


def _MIN_I64() -> int:
    """`-2**63`, written as `0 - _MAX_I64() - 1`.

    A FUNCTION for the reason every constant in this file is one, and written
    this way because `2**63` itself is NOT a value on this path: a literal of
    that size is one past the largest word, and a `0 - x` that produces it wraps
    to `-2**63` instead. So the only way to name it is from its neighbour.
    """
    return 0 - _MAX_I64() - 1


def _mag(v) -> int:
    """`|v|`, or **-1 for `-2**63`** — the one word whose magnitude is not a
    value here.

    `0 - (-2**63)` is `2**63`, which does not fit, so this path's negation of
    the most negative word WRAPS and a plain negation would return `-2**63` for
    it — a "magnitude" that is the smallest negative number, which then
    compares as
    less than every positive limit and makes an overflow check silent. So
    `_mag` refuses it with -1, and every caller that gets -1 refuses the
    operation rather than computing with a magnitude that does not exist.

    `gcdn` and `lcmn` pass this through `gcd`/`lcm`, where a `-2**63` operand
    is fine (Euclid works on it, and `gcd(-2**63, 0)` is `2**63` — which is
    also not a value, so those two refuse it too).
    """
    if v == _MIN_I64():
        return 0 - 1
    if v < 0:
        return 0 - v
    return v


def _mul_ok(a, b) -> int:
    """1 when `a * b` is a value on this path, 0 when it would wrap.

    THE FOUR SIGN CASES, and the reason there are four is one number: **the
    largest magnitude a word holds is `2**63`, and `2**63` is not itself a
    value on this path.** So a POSITIVE product may reach `2**63 - 1` and a
    NEGATIVE one may reach `2**63`, and a check written against `2**63 - 1`
    would refuse `(-2**62) * 2`, which is exactly `-2**63` and is representable.

      * both positive — `a > max / b`, the ordinary case;
      * both negative — the product is positive, so `max` again, on the
        magnitudes;
      * opposite signs — the product is negative, so the limit is `2**63`, and
        since that is not a value the comparison is done against `max` and
        corrected: `|a| * b` fits exactly when `|a| <= floor(2**63 / b)`, and
        `floor(2**63 / b)` is `floor(max / b)` plus one exactly when
        `max % b == b - 1`. The correction is a COMPARISON against the limit
        and not the limit itself, because computing `floor(max / b) + 1` when
        `b == 1` is `2**63 - 1 + 1` — which wraps to `-2**63`, a NEGATIVE
        limit, against which every `|a|` "overflows". That is not a corner case:
        `b == 1` is one of the two or three inputs of every one-element list,
        and the version with `limit = q + 1` refused `prod([-4], 1)` and
        `prod([2, -4], 1)`, both of which fit. `b == 1` is therefore answered
        first and directly: multiplying by one cannot overflow;
      * either factor is `-2**63` — refused, because `2**63` is its magnitude
        and `2**63` is not a value (see `_mag`).

    A plain `a > max / b` gets TWO of the four wrong, and both wrongnesses are
    silent: `prodn([2, 3, 5, -4], …)` refuses an answer of -120 that fits, and
    `prodn([-4], …)` accepts one that does not.
    """
    var ua = _mag(a)
    var ub = _mag(b)
    if ua < 0 or ub < 0:
        return 0
    if ua == 0 or ub == 0:
        return 1
    var max = _MAX_I64()
    var same = 0
    if a < 0:
        same = same + 1
    if b < 0:
        same = same + 1
    if same == 1:
        if ub == 1:
            return 1
        var q = max / ub
        if ua > q:
            if max % ub == ub - 1:
                return 1
            return 0
        return 1
    if ua > max / ub:
        return 0
    return 1


def _MAX_I64() -> int:
    """`2**63 - 1`, the largest value a word on this path holds.

    A FUNCTION because a module-level name is not exported as a word across a
    dylib boundary (`bugs/FORMAL_module_state_no_storage.md`), which is the same
    reason `os.sep()` and `stat.S_IRUSR()` are functions. Three callers in this
    file need it and a constant in three places is a number in three places.
    """
    return 9223372036854775807
