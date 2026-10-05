"""`random.seed` and `random.randrange`, for this path: a Mersenne Twister.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright over the host-module list, so this file is
what `import random` binds to. `random` leaves `HOST_MODELLED` when it lands, by
the rule that set is documented with: a name LEAVES by being WRITTEN, and an
entry left behind would refuse a file after the module that answers it is
sitting in the tree.

WHY THIS ONE, AND WHAT THE ROW IS ACTUALLY WORTH
------------------------------------------------
`tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-12.txt` puts
`random` at **8 files, 7 of them naming something it declares**:
`Random` x5, `randrange` x2, `seed` x2. Eight files is the fourth-largest host
import row in the census and the largest one that was both unclaimed and
reachable, which is why this module exists.

**It is 2 of the 8 files, and that is the honest number.** The five `Random`
callers (`test_gimple.py`, `tools/formal_fuzz.py`, `tools/formal_proof_fuzz.py`,
`tools/formal_model_fuzz.py`, `formal/x86_64_model_fuzz.py`) spell
`random.Random(<a str or an int>)`, and a `Random` is an OBJECT whose whole
state is 624 words — behind a pointer, on the wrong side of a dylib boundary, in
the place `bugs/FORMAL_module_state_no_storage.md` is about. **The capability
that would serve them is not this module; it is that one**, and it is not
reachable by writing a `.mojo` file. The two callers that are served
(`test_formal_hashlib.py:233` and `test_formal_time.py:345`) spell the module
functions: `random.seed(23)` then forty or a hundred and twenty
`random.randrange(a, b)` calls, and both already compare every answer against
CPython's own on the host side, so the differential oracle this module needs is
the one its callers wrote.

THE PREMISE, MEASURED, AND IT IS NOT THE OBVIOUS ONE
---------------------------------------------------
This module keeps 624 words of state in two module-level names and reads and
writes them from several functions, so it rests on a claim that
`bugs/FORMAL_module_state_no_storage.md` appears to deny: **a module's OWN
globals have storage, and it persists across calls inside one process.**
Measured on both architectures before this module was written, from a program
whose module-level `var` is written through `global` by one function and read by
another:

    var _c: Int = 0
    def bump() -> Int:  global _c;  _c = _c + 1;  return _c
    def peek() -> Int:  return _c
    def main() -> Int32: ... a = bump(); b = bump(); c = peek() ...
        -> arm64 exit 186, x86-64 exit 186, CPython 186

and the same for a module-level `List[Int]` written through its subscript: two
functions, four words, `arm64 exit 211 = x86-64 exit 211 = CPython 211`. So the
state lives in the defining library's own `__DATA` and a dylib keeps it for the
life of the process, which is all a Mersenne Twister needs. **`len()` on a
module-level list is refused** (the operand's kind does not cross a function
boundary), so `N` is the algorithm's own constant and not `len(_mt)`; that is
also the better transcription, since 624 is a property of MT19937 and not of
this module's spelling of it.

WHAT A 624-WORD LITERAL IS, AND WHY IT IS NOT `[0] * 624`
------------------------------------------------------
The state is a fixed-size LITERAL, and that is measured on both architectures
where a list grown in a loop is not: `[0] * 624` at module level builds and then
**prints nothing at all** (measured, both architectures, exit 0), while the
624-word literal reads back correctly at every size tried (4, 65, 66, 128, 624).
`bugs/FORMAL_x86_64_a_list_grown_in_a_loop_answers_nothing_past_65_elements.md`
records the same wall from the other side. A literal is also what makes the
state CONSTANT, which is what `_twist` mutating in place needs to be the only
writer.

THE FOUR THINGS A TRANSCRIPTION GETS WRONG
------------------------------------------
Every one of these was measured against CPython's own `random` while writing
this file, and each of them changes every answer rather than one of them.

1. **`init_genrand` LEAVES `index = N`, and `init_by_array` DOES NOT RESET IT.**
   So the FIRST draw after `seed` TWISTS FIRST, and the first output is
   `temper(twist(state)[0])` — not `temper(state[0])`. The usual
   `mt19937ar.c` reading (`mti = N` in `init_genrand`, and the reference test
   vectors agree) is right about the twist and wrong about the index if you
   take `init_by_array` from a different transcription of the same family: this
   module follows CPython's `Modules/_randommodule.c`, where the mix loop below
   ends without touching `index`. Getting this wrong produces a stream that is
   *plausible* — right magnitudes, wrong values.
2. **THE SEED MIX IS TWO LOOPS, AND THE SECOND ONE SUBTRACTS.** The first
   passes `+ init_key[j] + j` with multiplier `1664525`; the second passes
   `- i` with multiplier `1566083941` and runs `N-1` times. Then
   `mt[0] = 0x80000000`, which the C does as an assignment and not as a mix, so
   it is the one word of the state that is not a function of the seed.
3. **THE KEY IS THE SEED'S ABSOLUTE VALUE, SPLIT 32 BITS AT A TIME FROM THE
   RIGHT**, and a zero seed is ONE key word, not zero of them: `keyused = 1`
   when the seed is 0. `seed(0)` and an unseeded generator are different states
   in CPython, and `seed(0)` must reproduce the first.
4. **FOR `getrandbits(k)` WITH 33 ≤ k ≤ 64 THE FIRST WORD DRAWN IS THE LOW
   WORD.** The value is `(w0 | (w1 << 32)) >> (64 - k)` with `w0` drawn first,
   and the top word is shifted RIGHT by `64 - k` before it is placed, which is
   the same thing. `randrange(1, 4_000_000_000 * 10**9)` in
   `test_formal_time.py` is `k = 62`, so that call site is in the half of this
   function where the word order decides the answer.

32-BIT ARITHMETIC IS SPELLED OUT, AND WHY
----------------------------------------
CPython's state is `uint32_t`. This path's word is a signed 64-bit one, so every
operation that C performs in `uint32_t` is masked to 32 bits here — after each
multiply and each left shift, because those are the two that leave the range.
Every value is therefore in `0 .. 2^32-1` and non-negative, which is what makes
`>>` the shift this function needs: **`>>` is an ARITHMETIC shift on this path**
(`formal/hostmods/hashlib.mojo` says so where it needs the mask), so a negative
operand would fill the top bits with ones. Nothing here is ever negative.

EVERY PRODUCT FITS IN 64 BITS, WHICH IS WHY THERE IS NO 128-BIT PATH
-------------------------------------------------------------------
`1812433253 * 2^32` is `7.8 * 10^18` and `1566083941 * 2^32` is `6.7 * 10^18`,
both under `2^63`, so the widest product in the whole module — the mix multiply
on a full-range state word — is representable and one mask makes it the `uint32`
C would have produced. `>>` is never applied to a product. That is checked
rather than assumed: a value above `2^63` here would not wrap quietly, it would
be a wrong answer.

WHAT IS NOT HERE, AND WHY — each one measured, none of them approximated
----------------------------------------------------------------------
  * **`random.Random(seed)`** — 5 of the 8 files, and the object half:
    `bugs/FORMAL_module_state_no_storage.md`. A `Random` is 624 words behind a
    pointer and cannot cross a dylib boundary. What is written here is the
    module-level `seed` the two reachable callers spell, and nothing pretends
    to be the other half.
  * **`seed` of a `str`, `bytes`, `float` or `None`** — CPython's version-2
    string seed is `int.from_bytes(a + sha512(a))`, a big-integer construction
    this path has no way to spell, and `None` seeds from `urandom`. A float or
    a string argument is refused by the declared parameter type rather than
    answered by the integer path, which is the failure a caller can see.
  * **`getrandbits` as a module-level name** — it is here as the private
    `_getrandbits`, because it is a step of `randrange` and not of a call site.
    A name with no caller in the tree is not a capability, it is a comment
    (`formal/imports.py`'s `HOST_MODELLED` rule, and `shlex.mojo`'s `_split`
    for the case where shipping one is a trap).
  * **`random()`, `randint`, `uniform`, `shuffle`, `sample`, `choice`, and the
    gaussian cache** — no caller in this repository spells any of them, so they
    are absent rather than approximated. `random()` in particular would be
    `genrand_res53`, which is a `double` and a `float` is not a value on this
    path (`formal/hostmods/math.mojo`'s rule for every float in CPython's
    `math`).
* **A range whose width does not fit a signed 64-bit word**, which is `-1`
    rather than a wrapped number, for the reason stated at `randrange`: the
    answer is a 64-bit UNSIGNED value and can land above `2**63`, which is not a
    value this path has. `math.mojo` states the same rule for a factorial above
    64 bits.
  * **A range CPython rejects**, `randrange(a, b)` with `b <= a`, is `-1` too
    and for the same reason (there are no exceptions here, FORMAL.md phase 7):
    CPython raises `ValueError`, and the alternative was a hang, because
    `_randbelow(0)` asks for zero bits and every draw is `>= 0`.
"""
var _mt: List[Int] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
]


var _idx: Int = 624


def _twist():
    """The 624-word state transform: one pass of MT19937's recurrence.

    `_mt[k] = _mt[k + M] ^ (y >> 1) ^ mag01[y & 1]` with `y` the two halves of
    `_mt[k]` and `_mt[k + 1]` spliced, which is why `y & 1` is the bit that
    selects `MATRIX_A`: the low bit of the spliced word is `_mt[k+1]`'s top bit.
    It is IN PLACE and in this order, which is load-bearing — the second half of
    the pass reads `_mt[k - 227]`, which the first half has already rewritten.

    `mag01[0]` is 0 and `mag01[1]` is `MATRIX_A`, so the table is the `if`.
    """
    global _mt
    global _idx
    var k = 0
    var y = 0
    var v = 0
    while k < 227:                      # N - M, with N = 624 and M = 397
        y = (_mt[k] & 2147483648) | (_mt[k + 1] & 2147483647)
        v = _mt[k + 397] ^ (y >> 1)
        if (y & 1) == 1:
            v = v ^ 2567483615          # MATRIX_A = 0x9908b0df
        _mt[k] = v
        k = k + 1
    while k < 623:
        y = (_mt[k] & 2147483648) | (_mt[k + 1] & 2147483647)
        v = _mt[k - 227] ^ (y >> 1)
        if (y & 1) == 1:
            v = v ^ 2567483615
        _mt[k] = v
        k = k + 1
    y = (_mt[623] & 2147483648) | (_mt[0] & 2147483647)
    v = _mt[396] ^ (y >> 1)
    if (y & 1) == 1:
        v = v ^ 2567483615
    _mt[623] = v
    _idx = 0


def _next32() -> int:
    """One tempered 32-bit word, advancing the state.

    The tempering is the four shifts, and each of the two left shifts is masked
    where C's `uint32_t` truncates for it. `_next32` twists first when `_idx`
    has reached 624, which is also what makes the FIRST call after `seed` a
    twisted one (see the module docstring's first wrong transcription).
    """
    global _mt
    global _idx
    if _idx >= 624:
        _twist()
    var y = _mt[_idx]
    _idx = _idx + 1
    y = y ^ (y >> 11)
    y = y ^ ((y << 7) & 2636928640)     # 0x9d2c5680
    y = y & 4294967295
    y = y ^ ((y << 15) & 4022730752)    # 0xefc60000
    y = y & 4294967295
    y = y ^ (y >> 18)
    return y & 4294967295


def _bit_length(n: int) -> int:
    """`n.bit_length()` for `n >= 0`: the position of its top set bit plus one.

    The loop rather than a logarithm because there is no logarithm on this path
    and because the count has to be exact: it is the WIDTH `randrange` draws,
    and one bit too many changes every answer in the rejection loop.
    """
    var b = 0
    var v = n
    while v > 0:
        v = v >> 1
        b = b + 1
    return b


def _getrandbits(k: int) -> int:
    """CPython's `getrandbits(k)` for `k <= 63`, which is all `randrange` asks.

    `k <= 32` is the fast path: one tempered word, shifted down so the answer
    has exactly `k` bits. `33 <= k <= 63` is the two-word case, and TWO things
    about it are the answer rather than the spelling: the word drawn FIRST is the
    LOW word, and **the low word is NOT shifted at all** — CPython shifts the
    TOP word down before placing it, so the value is `w0 | ((w1 >> (64 - k))
    << 32)` and there is no final shift of the whole thing.

    That is worth stating because the obvious "simplification" of it,
    `((w0 | (w1 << 32)) >> (64 - k))`, is a DIFFERENT function: it drops the top
    `64 - k` bits of the low word as well, so for `k = 33` it answers 2 bits
    where CPython answers 33. It was written here, it was caught by
    `test_formal_random.py`'s corpus against CPython on the first run, and the
    shape that is here is the one that composes the two words the way the C does.

    `(w1 >> s) << 32` with `s = 64 - k >= 1` is below `2^k`, so the answer fits a
    signed 64-bit word; that is also why `k = 64` is not served here — see
    `randrange`.
    """
    if k == 0:
        return 0
    if k <= 32:
        return _next32() >> (32 - k)
    var lo = _next32()
    var hi = _next32()
    return lo | ((hi >> (64 - k)) << 32)


def _word_count(n: int) -> int:
    """How many 32-bit words `n`'s little-endian split has; at least one.

    CPython's `keyused = bits == 0 ? 1 : (bits - 1) / 32 + 1`, which is this
    count: a zero seed is ONE key word, and that word is 0. The key is never
    MATERIALISED as a list — `_seed_by_array` reads word `j` out of `n` with a
    shift — because a run-time-length list is not a value this path has
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`) and the words are the same
    two lines either way.
    """
    var w = 1
    var v = n
    while v > 4294967295:
        v = v >> 32
        w = w + 1
    return w


def _init_genrand(s: int):
    """`mt[0] = s`, then `mt[i] = 1812433253 * (mt[i-1] ^ (mt[i-1] >> 30)) + i`.

    The multiplier is Knuth's, and the shift is 30 because `1812433253` has bit
    31 set and the high bits of the seed have to reach the high bits of the
    array. **`_idx` is left at 624**, which is the whole of the difference
    between this and a transcription that starts reading at word 0.
    """
    global _mt
    global _idx
    _mt[0] = s & 4294967295
    var i = 1
    var prev = _mt[0]
    while i < 624:
        prev = ((1812433253 * (prev ^ (prev >> 30))) + i) & 4294967295
        _mt[i] = prev
        i = i + 1
    _idx = 624


def _seed_by_array(n: int, keyused: int):
    """CPython's `init_by_array` over the seed's own words.

    The walk is `i` over the array and `j` over the key, both wrapping at 624
    and `keyused`, for `max(624, keyused)` steps; the key word is
    `(n >> (32 * j)) & 0xFFFFFFFF`, which is `init_key[j]` in C without a list.
    The SECOND pass is the one a transcription gets wrong: multiplier
    `1566083941`, and `- i` where the first pass wrote `+ j`.

    `_idx` is not touched, so it stays at the 624 `_init_genrand` left, and the
    first `_next32` after this twists before it reads.
    """
    global _mt
    _init_genrand(19650218)
    var i = 1
    var j = 0
    var k = 624
    if keyused > 624:
        k = keyused
    var prev = 0
    var v = 0
    while k > 0:
        prev = _mt[i - 1]
        v = _mt[i] ^ (((prev ^ (prev >> 30)) * 1664525) & 4294967295)
        v = (v + ((n >> (32 * j)) & 4294967295) + j) & 4294967295
        _mt[i] = v
        i = i + 1
        j = j + 1
        if i >= 624:
            _mt[0] = _mt[623]
            i = 1
        if j >= keyused:
            j = 0
        k = k - 1
    k = 623
    while k > 0:
        prev = _mt[i - 1]
        v = _mt[i] ^ (((prev ^ (prev >> 30)) * 1566083941) & 4294967295)
        v = (v - i) & 4294967295
        _mt[i] = v
        i = i + 1
        if i >= 624:
            _mt[0] = _mt[623]
            i = 1
        k = k - 1
    _mt[0] = 2147483648                  # 0x80000000: the MSB is set on purpose


def seed(n: int):
    """`random.seed(n)` for an integer `n`: the module-level generator's state.

    CPython takes the ABSOLUTE value (`random_seed` says the algorithm relies on
    the number being unsigned), splits it into 32-bit words from the right, and
    calls `init_by_array` with them. So `seed(-17)` and `seed(17)` are the same
    state, and `seed(0)` is one key word of zero rather than no key at all.

    Returns nothing, as CPython's does. There is no way to read the state back
    on this path (`getstate` is a 625-element tuple), so a program that wants a
    reproducible sequence seeds and then draws, which is what both callers do.
    """
    global _mt
    global _idx
    var m = n
    if m < 0:
        m = -m
    _seed_by_array(m, _word_count(m))


def randrange(a: int, b: int) -> int:
    """`random.randrange(a, b)` for `a < b`: a uniform integer in `[a, b)`.

    CPython's shape exactly: `width = b - a`, `k = width.bit_length()`, then
    `getrandbits(k)` until the draw is UNDER `width`, then `a + draw`. The
    rejection loop is not an optimisation to drop — it is what makes the answer
    uniform, and CPython's expected number of iterations for a width just under a
    power of two is close to two.

**TWO STATUSES WHERE CPython RAISES**, both `-1`, both because there are no
    exceptions on this path (FORMAL.md phase 7) and both stated rather than
    papered over:

      * `b <= a`. CPython raises `ValueError: empty range`. The alternative here
        was not a refusal but a HANG: `_bit_length(0)` is 0, `_getrandbits(0)`
        is 0, and `0 >= 0` never ends.
      * a width above `2**63 - 1`, which is CPython's own bound as well —
        `_index` is `PyLong_AsSsize_t`, so `randrange(-(2**63), 2**63 - 1)` is a
        call CPython accepts and answers anywhere in a span of `2**64 - 1`. The
        answer is a 64-bit UNSIGNED value and can land above `2**63`, which is
        not a value a signed 64-bit word holds.

    **THE SECOND STATUS IS CHECKED ON `width < 0`, NOT ON `k >= 64`, and that is
    not a stylistic choice — it is the difference between a status and a HANG.**
    The width is computed in this path's signed word, so a true width of `2**63`
    or more arrives here already NEGATIVE (it is `width - 2**64`). Asking
    `_bit_length` about it first answers 0 — the loop counts `while v > 0`, and a
    negative `v` is not `> 0` — and then `_getrandbits(0)` is 0 and
    `while 0 >= width` with a negative `width` never ends. Measured: the first
    spelling of this module with a `k >= 64` guard hung for the full 300 s the
    test allows instead of answering, and `test_formal_random.py`'s `statuses`
    group is the row that found it. The two tests are the same test, since a
    width is at least `2**63` exactly when its bit length is 64.
    """
    if b <= a:
        return -1
    var width = b - a
    if width < 0:
        return -1
    var k = _bit_length(width)
    var r = _getrandbits(k)
    while r >= width:
        r = _getrandbits(k)
    return a + r