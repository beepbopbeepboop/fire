"""operator.mojo — the part of CPython's `operator` a 64-bit word can answer.

`formal/imports.py` resolves an import in four passes and the FIRST is "a Mojo
source `<name>.mojo` in a search root WINS OUTRIGHT, even over the host-module
list". This file is that source for the name `operator`, so `import operator` is
no longer the refusal

    imports 'operator', which is a host module (CPython standard library), which
    has no Mojo source for this backend to compile

It lives in `formal/hostmods/` — the last search root, and the only one no other
resolver in this tree lists. See `_HOSTMODS_ROOT`.

THE DIVIDING LINE, AND IT IS ONE WORD WIDE
-------------------------------------------
CPython's `operator` is 55 names in three groups, and this module is the first
group: the ones that take two WORDS and answer a word. The other two are a
container and a callable, and a formal value is one 64-bit word in a function's
own stack scratch (`formal/model.py`, "What a value is") — so `getitem`,
`countOf` and `indexOf` want a sequence this path cannot name, and
`itemgetter`, `attrgetter`, `methodcaller` and `call` want a first-class callable,
which is REFUSED on this path whatever it is passed to (measured on both shapes,
in `formal/hostmods/contextlib.mojo` and in
`bugs/COMPILE_FAIL_decorator_application_dropped.md`'s neighbourhood). Every one
of those is named under "WHAT IS NOT HERE".

**SO EVERY ANSWER HERE IS WORD ARITHMETIC AND WRAPS.** That is not a shortcut and
it is not an approximation of CPython's arbitrary-precision `int`; it is what the
target computes, and a mirror that answered 0 or refused an overflowing product
would be answering a question about a different machine:

    printf("%lld", 4611686018427387904 * 4)      # 0    (two's complement, 64-bit)
    printf("%lld", 9223372036854775807 + 1)      # -9223372036854775808

**THREE WAYS AN ANSWER CAN FAIL TO BE A WORD, and each is a NUMBER rather than a
wrong answer**, because there are no exceptions on this path (`FORMAL.md`
phase 7). -1 is `formal/hostmods/math.mojo`'s own choice for a factorial or a
binomial coefficient above 64 bits and this module uses it for the same reason — a
status is visible, a plausible wrong answer is not. The three are separate
things and `test_formal_core_hostmods.py`'s `op` group keeps them in separate
tables, because the first version of that group had one table for all of them and
two of its rows were FALSE about CPython:

  1. **CPython raises, and there is nothing to return.** `floordiv(a, 0)` and
     `mod(a, 0)` answer -1 where CPython raises `ZeroDivisionError`;
     `pow_mod(a, b, 0)` answers -1 where CPython raises `ValueError`; and a
     NEGATIVE shift distance answers -1 where CPython raises `ValueError:
     negative shift count`.
  2. **CPython's answer is a FLOAT.** `pow(a, b)` with `b < 0` answers -1, and
     this one is not a refusal at all — CPython answers `0.5` for `pow(2, -1)`
     (measured; the first version of this module's own docstring claimed a
     `ValueError` there and the group caught it). There is no float on this path
     (`formal/hostmods/math.mojo` says why at length — a `double` does not travel
     in an integer register on either ABI), and an integer `pow(a, -1)` would be
     a different function wearing `pow`'s name.
  3. **CPython's answer is WIDER THAN THE WORD.** `lshift` answers -1 for a
     distance past 63 unless the operand is 0 (where `0 << 1000` really is 0 in
     both). The hardware MASKS a shift distance to its low 6 bits, so `1 << 64`
     is `0` here and `2**64` in CPython — measured — and that is a silent wrong
     answer wearing a shift's name, which is why the guard is written out rather
     than left to `<<`. **`rshift` is the asymmetry and it is the interesting one:
     a right shift past the width is a DEFINED answer both sides can give** — 0
     for a non-negative word and -1 for a negative one, because an arithmetic
     shift saturates — so `rshift` computes that and does NOT answer a status
     there. Left to the machine's `>>` it would answer 0 for both (measured:
     `-1 >> 100` is 0 here and -1 in CPython), which is a second silent wrong
     answer the guard prevents.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `truediv` — a `float`. CPython's `7 / 2` is `3.5` and there is no way to say
    that in one word; `floordiv` is the integer answer and is here. Shipping
    `truediv(a, b) = a // b` would be the worst kind of wrong, because
    `truediv(4, 2)` agrees with CPython and `truediv(7, 2)` does not, so the
    error only shows on the cases that matter.
  * `divmod`, `concat` — a PAIR and a sequence. `formal/hostmods/time.mojo` says
    the same about `get_clock_info`, and the reason is the same: a tuple is a
    blob carved out of the frame that built it, and the caller is not that frame.
  * `contains`, `countOf`, `indexOf`, `getitem`, `setitem`, `delitem` — the same
    missing sequence, plus a callable for the three `*item` ones.
  * `itemgetter`, `attrgetter`, `methodcaller`, `call` — a first-class callable
    as a RETURN value, which is refused on this path.
  * `iadd`, `isub`, `imul`, `itruediv`, `ifloordiv`, `imod`, `ipow`, `ilshift`,
    `irshift`, `iand`, `ior`, `ixor` — the in-place family. Each returns
    `a OP b` AND writes it back through a name, and a value here is not a name:
    `operator.iadd(3, 4)` in CPython cannot be spelled without a variable to
    write, and the half that can be spelled would be a function that computes
    the right number and mutates nothing — the `closing` shape
    `formal/hostmods/contextlib.mojo` declines to ship. A program that wrote
    `i = operator.iadd(i, 1)` would run and lose the increment.
  * `length_hint` — `__len__` off a live object.
  * `abs` is spelled `abs` here and computes its own negation rather than calling
    the builtin: a call is extern exactly when the name is not a function of the
    unit being compiled (`formal/hostmods/os/_syscalls.mojo`'s header, point 1),
    so a module that declares `def abs(a)` and called `abs(a)` would emit a call
    to ITSELF. Measured, in `os/_syscalls.mojo`'s `fs_strsignal` and the same
    rule.

THE TWO THINGS THAT ARE NOT QUITE CPYTHON, STATED HERE
------------------------------------------------------
  * The comparisons answer **1** or **0**, where CPython answers `True`/`False`.
    On this path a boolean is a word (`formal/model.py`) and `1`/`0` is that
    word; `test_formal_core_hostmods.py`'s `op` group compares against
    `int(getattr(operator, name)(a, b))`, so the oracle is CPython's own answer
    read through the same conversion and not a constant.
  * `pow_mod` is not CPython's spelling — CPython's is `pow(a, b, modulo)` with
    `modulo` defaulting to `None`, and this path cannot express "absent": a
    default is a word, and the word that would mean "no modulus" collides with a
    real modulus of 0... which is not even a legal modulus. So the two arities
    are two NAMES here, `pow` and `pow_mod`, the way
    `formal/hostmods/sys.mojo` spells `sys.version_info` as three functions
    rather than one tuple. A three-argument `pow` is REFUSED rather than read as
    the two-argument one, so a caller that means a modulus cannot silently get
    the plain power.
"""


def add(a, b) -> int:
    """`operator.add(a, b)`: `a + b`, wrapping at 64 bits like the machine's."""
    return a + b


def sub(a, b) -> int:
    """`operator.sub(a, b)`: `a - b`, wrapping at 64 bits."""
    return a - b


def mul(a, b) -> int:
    """`operator.mul(a, b)`: `a * b`, wrapping at 64 bits."""
    return a * b


def floordiv(a, b) -> int:
    """`operator.floordiv(a, b)`: `a // b`, or -1 when `b` is 0.

    The -1 is a STATUS, not an answer: CPython raises `ZeroDivisionError` and
    this path has no raise. It is `formal/hostmods/math.mojo`'s choice for a
    factorial above 64 bits, for the same reason and with the same argument —
    a number a caller can test for is honest and a plausible quotient is not.
    """
    if b == 0:
        return 0 - 1
    return a // b


def mod(a, b) -> int:
    """`operator.mod(a, b)`: `a % b`, or -1 when `b` is 0.

    CPython's `%` FLOORS rather than truncating, and so does this: `7 % 3` is 1
    and `(0 - 7) % 2` is 1 on both sides (measured, and it is the row a
    truncating implementation gets wrong).
    """
    if b == 0:
        return 0 - 1
    return a % b


def pow(a, b) -> int:
    """`operator.pow(a, b)`: `a ** b` for `b >= 0`, or -1 for a negative exponent.

    Computed here by repeated squaring rather than by the `**` operator or by
    libSystem's `pow(double, double)`: the operator has its own lowering and the
    C library's takes and answers a `double`, which does not travel in an integer
    register on either ABI (arm64 `d0`, SysV x86-64 `XMM0`) — the argument
    `formal/hostmods/math.mojo` gives for refusing `sqrt`.

    `0 ** 0` is 1, which is CPython's answer and the one this loop reaches
    without a special case: the accumulator starts at 1 and the exponent at 0.

    A NEGATIVE exponent is -1 rather than a reciprocal, because CPython's answer
    is a `float` and there is none here.
    """
    if b < 0:
        return 0 - 1
    result = 1
    base = a
    e = b
    while e > 0:
        if e % 2 == 1:
            result = result * base
        base = base * base
        e = e // 2
    return result


def pow_mod(a, b, m) -> int:
    """`pow(a, b, m)` — CPython spells this `operator.pow` with three arguments.

    The modulus is applied at every step rather than to a finished power, so the
    intermediate products never leave the word: for any `m` the word holds, the
    answer is inside `[0, m)` and therefore representable, which is why this
    function needs no range status where the plain `pow` has none either.

    `m == 0` is -1: CPython raises `ValueError: pow() 3rd argument cannot be 0`.
    """
    if m == 0:
        return 0 - 1
    if b < 0:
        # CPython requires the modulus with a negative exponent to be 1 or -1,
        # and both of those answer 1. Anything else is `ValueError` there, so the
        # honest thing here is the same -1 every other refusal in this module is.
        if m == 1 or m == 0 - 1:
            return 1
        return 0 - 1
    result = 1
    base = a % m
    e = b
    while e > 0:
        if e % 2 == 1:
            result = (result * base) % m
        base = (base * base) % m
        e = e // 2
    return result % m


def lshift(a, n) -> int:
    """`operator.lshift(a, n)`: `a << n`, or -1 where the result cannot be a word.

    `n < 0` is CPython's `ValueError: negative shift count`. `n > 63` is not a
    refusal so much as an arithmetic fact: for any non-zero `a` the answer's
    magnitude is at least `2**n`, which is past 2**63, so there is no signed
    64-bit word that holds it and -1 is the only answer that is not a lie.
    `a == 0` is the exception and is a real answer rather than a status: CPython's
    `0 << 1000` is `0`, and so is the word's.

    The guard is HERE rather than left to the `<<` operator because the hardware
    MASKS a shift distance to its low 6 bits (arm64 `LSL`'s register form, SysV
    x86-64's `SHL` with a `CL` mask). Measured: `1 << 64` is `0` on this target
    and `2**64` in CPython, and `0 - 1 >> 100` is `0` here and `-1` in CPython —
    two silent wrong answers wearing the name of a shift, which is the shape of
    bug `FORMAL_known_limits.md` exists to keep out. The `n <= 63` answers are
    NOT guesses: every one of them was compared with CPython and agrees
    (`test_formal_core_hostmods.py`'s `op` group, including `-1 << 63`).
    """
    if n < 0:
        return 0 - 1
    if n > 63:
        if a == 0:
            return 0
        return 0 - 1
    return a << n


def rshift(a, n) -> int:
    """`operator.rshift(a, n)`: `a >> n`, or -1 for a negative distance.

    `n > 63` is NOT a status here, and the asymmetry with `lshift` is measured
    rather than chosen. CPython's `int` is arbitrary-precision, so `a >> n` past
    the width is a well-defined answer this target can also produce: `0` for a
    non-negative `a` and `-1` for a negative one, because an arithmetic shift
    saturates there. So the module computes exactly that instead of the `>>`
    operator, whose low-6-bit masking answers `0` for BOTH (measured:
    `-1 >> 100` is `0` on this target and `-1` in CPython). Inside `0..63` the
    machine and CPython agree on every case measured, negative operands
    included.
    """
    if n < 0:
        return 0 - 1
    if n > 63:
        if a < 0:
            return 0 - 1
        return 0
    return a >> n


def and_(a, b) -> int:
    """`operator.and_(a, b)`: `a & b`, bitwise. NOT the boolean `and`."""
    return a & b


def or_(a, b) -> int:
    """`operator.or_(a, b)`: `a | b`, bitwise. NOT the boolean `or`."""
    return a | b


def xor(a, b) -> int:
    """`operator.xor(a, b)`: `a ^ b`, bitwise."""
    return a ^ b


def invert(a) -> int:
    """`operator.invert(a)`: `~a`, bitwise."""
    return ~a


def neg(a) -> int:
    """`operator.neg(a)`: `-a`, wrapping at 64 bits like the machine's."""
    return 0 - a


def pos(a) -> int:
    """`operator.pos(a)`: `+a`, which on this path is the identity.

    Worth having because it is the ONE name in this module that is the identity
    function, and a mirror that answered 0 for it would be a wrong answer about
    a function whose whole contract is "changes nothing".
    """
    return a


def abs(a) -> int:
    """`operator.abs(a)`: `|a|`.

    Its own negation rather than a call to the builtin — see the module
    docstring's last paragraph, which is the name-collision rule this shape is
    the second instance of in this tree (`os/_syscalls.mojo`'s `fs_strsignal` is
    the first).
    """
    if a < 0:
        return 0 - a
    return a


def index(a) -> int:
    """`operator.index(a)`: `a.__index__()`, which for every word here is `a`.

    A CPython `int` IS its own `__index__`, and on this path a value is a word,
    so the whole of what `__index__` means is already the identity. A `bool`
    inherits it, and a `bool` is a word here too.
    """
    return a


def truth(a) -> int:
    """`operator.truth(a)`: `bool(a)`, as 1 or 0.

    CPython's own `truth` returns a real `bool`; see the module docstring's note
    on the comparisons, which is the same conversion.
    """
    if a == 0:
        return 0
    return 1


def lt(a, b) -> int:
    """`operator.lt(a, b)`: `a < b` as 1 or 0."""
    if a < b:
        return 1
    return 0


def le(a, b) -> int:
    """`operator.le(a, b)`: `a <= b` as 1 or 0."""
    if a <= b:
        return 1
    return 0


def eq(a, b) -> int:
    """`operator.eq(a, b)`: `a == b` as 1 or 0."""
    if a == b:
        return 1
    return 0


def ne(a, b) -> int:
    """`operator.ne(a, b)`: `a != b` as 1 or 0."""
    if a != b:
        return 1
    return 0


def gt(a, b) -> int:
    """`operator.gt(a, b)`: `a > b` as 1 or 0."""
    if a > b:
        return 1
    return 0


def ge(a, b) -> int:
    """`operator.ge(a, b)`: `a >= b` as 1 or 0."""
    if a >= b:
        return 1
    return 0


def not_(a) -> int:
    """`operator.not_(a)`: `not a` as 1 or 0.

    CPython's `not` is about TRUTH and not about the bits, so this is 1 for a
    zero word and 0 for every other — which is why it is not `1 - truth(a)`'s
    spelling in the source: `0 - 1` and `0` are the two words here, and a `1 -`
    would read as arithmetic on a boolean that has no arithmetic.
    """
    if a == 0:
        return 1
    return 0
