"""`random.seed`, `random.getrandbits` and `random.randrange` — CPython's
Mersenne Twister, because CPython's IS a Mersenne Twister and both of this
repository's callers compare every answer against CPython's own.

WHY THE EXACT ALGORITHM AND NOT A RANDOMNESS SOURCE
---------------------------------------------------
`formal/hostmods/tempfile.mojo` already calls `arc4random_buf(3)`, so entropy
is the one thing here that is certainly available — and it is the one thing
that cannot answer. The two files that import `random` are differential tests
that print a seeded spread and compare the numbers with what CPython's own
`random` produces for the same seed:

  * `test_formal_time.py:345` — `random.seed(17)` then 120 values from
    `random.randrange(1, 4_000_000_000 * 10**9)`;
  * `test_formal_hashlib.py:233` — `random.seed(23)` then 40 lengths from
    `random.randrange(140, 5000)`.

So a "good enough" generator is a WRONG ANSWER in both: the whole value of
those two rows is that the sequence is the one CPython produces, bit for bit,
and that is MT19937 seeded exactly the way CPython seeds it. `libSystem` has
no MT and neither has libm; the algorithm is 40 lines of integer arithmetic
and it is transcribed here.

THE STATE, AND WHY IT IS A MODULE-LEVEL LIST
--------------------------------------------
CPython's generator is an OBJECT — `random.Random` is 624 words plus an index
behind a pointer — and an object is more than one 64-bit word, which is
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` and the
reason `test_gimple.py`'s `rng = random.Random(20260930)` and
`tools/formal_fuzz.py`'s are NOT in reach. **The module-level spellings are,
and the reason is a measurement rather than an argument:** the 624 words live
in a module-level list, read and written by three functions of the module that
declares it, and that crosses the dylib boundary and comes back correct on
both architectures (a three-slot scratch module built through
`fire.py build --formal` answered 36/39/12 where CPython's own arithmetic says
36/39/12, on arm64 and on x86-64). `bugs/FORMAL_module_state_no_storage.md`
says the same thing about a module global: one writer, in the module that
declares it, is storage that exists.

**A `Random` INSTANCE stays refused after this file**, which is the honest
number and not a disappointment: 2 of the 4 files in the row move, and the two
that spell `random.Random(n)` stop on the instance rather than on the import.

THE SEED, AND WHY IT IS THE INTEGER CASE ONLY
---------------------------------------------
CPython's `Random.seed` folds its argument into a key of up to thirty-two
32-bit words and hands it to `init_by_array`:

  * an INT (or a float, or anything else) — the value's ABSOLUTE value as
    little-endian bytes, so `seed(23)` is the one-word key `[23]` and
    `seed(1 << 32)` is the two-word key `[0, 1]`;
  * a str / bytes / bytearray — `int.from_bytes(a + sha512(a).digest())`,
    which is a 512-BIT key. That is the same shape as the integer case and one
    word too wide: assembling it means a hash of a string
    (`formal/hostmods/hashlib.mojo` has `sha512`) followed by sixteen 32-bit
    words built by hand. It is a real extension rather than a transcription,
    and nothing in this repository asks for it, so it is absent rather than
    approximated;
  * `None`, or no argument at all — the OS. Absent for the same reason the
    two above are, and it is the one case where an absent name costs nothing:
    a program that wants entropy wants `arc4random_buf`, which is in
    `tempfile.mojo`.

The absolute value is not decoration: `seed(-1)` and `seed(1)` are the SAME
CPython sequence, and a transcription that took the value as written would give
a different answer for each and still look right.

`getrandbits(k)` is here because `randrange` is defined in terms of it in
CPython (`_randbelow_with_getrandbits`) and because the two callers' ranges
need it: `test_formal_time.py`'s `randrange(1, 4e18)` asks for 62 bits, which
is two 32-bit draws, and a module that stopped at 32 would answer a number in
the wrong range.

WHAT IS HERE, AND WHAT IS NOT
-----------------------------
    seed(a)         the integer case above
    getrandbits(k)  1..64 bits, CPython's own word split
    randrange(a, b) the two-argument form, CPython's fast path

  * `random()` — `genrand_res53`, a `double` in [0, 1). Absent because a
    `double` is not what a formal value is (`formal/hostmods/math.mojo`'s own
    docstring says it: a `double` does not travel in an integer register on
    either ABI), and `getrandbits` answers the same need in the domain this
    path has.
  * `Random` — the class, above.
  * `randint`, `randrange` with a `step`, `choice`, `shuffle`, `sample`,
    `uniform`, `gauss` — every one of them either takes a SEQUENCE or answers
    one, which lives in the caller's frame and cannot cross a dylib boundary
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`), or keeps a second piece
    of state (`gauss_next`, which CPython's own `seed` clears). `gauss` is the
    one that would otherwise look cheapest and is the clearest no: its state is
    a `float` held between calls.
  * `randbytes`, `getstate`, `setstate` — a byte string and a 625-word tuple.

THE TWO MASKS THAT ARE NOT INTERCHANGEABLE
------------------------------------------
`init_genrand` and `init_by_array` are two different recurrences and a
transcription that merges them produces a generator that is plausible, is
uniform, and disagrees with CPython from its first draw. The 1566083941 below
is the SECOND one and the 1664525 above it is the first; they differ because
one adds the loop counter and the other subtracts it, and both are spelled out
rather than folded into a helper, because a helper would have to be told which
of the two it was and that is the bug.

Every 32-bit value is masked with `0xFFFFFFFF` on the way out of each step,
because `Int` here is a signed 64-bit word (`doc/ABI.md`) and the recurrence
is defined on UNSIGNED 32-bit arithmetic: without the mask a value above 2^31
survives as itself and the next multiply compounds the difference. `test_
formal_random.py` compares every answer with CPython's, so a missing mask is
caught on the first draw rather than on the thousandth.
"""


# ── MT19937's own constants ───────────────────────────────────────────────
#
# `N` is the state size and `M` the recurrence's offset; the rest are the
# masks and multipliers the reference implementation names. They are
# `comptime`-shaped module constants rather than literals at each use because
# the twist indexes `mt[kk + M]` and `mt[kk - (N - M)]` off the same pair, and
# a transcription that hard-codes 397 in one place and 227 in the other is a
# transcription that can be half right.
N = 624
M = 397
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7FFFFFFF
MASK32 = 0xFFFFFFFF
# The twist's multiplier, applied only when the pair's low bit is set (which is
# what `-(y & 1) & MATRIX_A` spells, and spelling it that way rather than with a
# branch is what keeps `_twist` free of a conditional the reference does not
# have).
MATRIX_A = 0x9908B0DF
INIT_MT = 1812433253
INIT_BY_ARRAY_MUL = 1664525
INIT_BY_ARRAY_MUL2 = 1566083941
# `init_by_array`'s key is at most 32 words wide (`uint32_t key[32]` in
# CPython's `_randommodule.c`), and a wider seed is truncated to that.
MAX_KEY_WORDS = 32

# The 624 words, as a module-level LIST rather than 624 `comptime` bindings:
# this is state that three functions write, so it has to be a container with an
# address, and a list is the one container this path can both subscript-assign
# through and keep. The value is irrelevant — `seed` overwrites all 624 before
# any draw — but the BINDING is what gives the state its storage, and `_MTI`
# beside it is the index those 624 words are handed out by.
_MTI = N

_MT = [
    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0,    0, 0, 0, 0, 0, 0, 0, 0
]


def init_genrand(s) -> int:
    """The `init_genrand` recurrence: `mt[0] = s`, then a multiply-add-xorshift
    chain over the whole state.

    CPython calls this from `init_by_array` and nothing else seeds a
    generator through it, so it is private here for the reason `_is_safe` is
    private in `shlex.mojo`: a private name is not exported, and a name with
    no caller in the tree is a comment rather than a capability.
    """
    _MT[0] = s & MASK32
    var mti = 1
    while mti < N:
        var prev = _MT[mti - 1]
        _MT[mti] = (INIT_MT * ((prev ^ (prev >> 30)) & MASK32) + mti) & MASK32
        mti = mti + 1
    return 0


def _twist() -> int:
    """One regeneration of all 624 words, in place.

    The reference loop reads `mt[kk]` and `mt[kk + 1]`, writes `mt[kk]`, and
    wraps `kk + 1` to 0 at the end — so the read of `mt[kk + 1]` always sees
    the PREVIOUS iteration's value, which is the whole of why the in-place
    form works at all. `y` is assembled from two halves of two words
    (`UPPER_MASK` on the older, `LOWER_MASK` on the newer) because the shift
    below moves 31 bits across the seam and a plain `mt[kk] ^ mt[kk + 1]`
    would not.
    """
    var kk = 0
    while kk < N - M:
        var y = (_MT[kk] & UPPER_MASK) | (_MT[kk + 1] & LOWER_MASK)
        _MT[kk] = (_MT[kk + M] ^ (y >> 1) ^ (-(y & 1) & MATRIX_A)) & MASK32
        kk = kk + 1
    while kk < N - 1:
        var y = (_MT[kk] & UPPER_MASK) | (_MT[kk + 1] & LOWER_MASK)
        _MT[kk] = (_MT[kk - (N - M)] ^ (y >> 1) ^ (-(y & 1) & MATRIX_A)) & MASK32
        kk = kk + 1
    # The seam: the newest word paired with the just-regenerated `mt[0]`.
    var y = (_MT[N - 1] & UPPER_MASK) | (_MT[0] & LOWER_MASK)
    _MT[N - 1] = (_MT[M - 1] ^ (y >> 1) ^ (-(y & 1) & MATRIX_A)) & MASK32
    return 0


def _next_uint32() -> int:
    """One tempered 32-bit draw: twist when the index has wrapped, then temper.

    **The index is the algorithm.** MT19937 regenerates all 624 words every
    624 draws and hands them out one at a time; a transcription that twists on
    every call is a different generator — still uniform, still reproducible
    from the seed, and disagreeing with CPython from its FIRST draw, which is
    the failure mode this module exists to avoid. `_MTI` is the walk, and it is
    module-level for the reason `_MT` is: it has to survive between calls, and
    one writer inside the module that declares it is storage that exists.

    The tempering's three shifts are not commutative with the masks beside
    them, so each line masks where the reference masks, and `y` is masked to
    32 bits at every step because the recurrence is defined on unsigned
    arithmetic while `Int` here is a signed 64-bit word.
    """
    global _MTI
    if _MTI >= N:
        _twist()
        _MTI = 0
    var y = _MT[_MTI]
    _MTI = _MTI + 1
    y = (y ^ (y >> 11)) & MASK32
    y = (y ^ ((y << 7) & 0x9D2C5680)) & MASK32
    y = (y ^ ((y << 15) & 0xEFC60000)) & MASK32
    y = (y ^ (y >> 18)) & MASK32
    return y


def seed(a) -> int:
    """`random.seed(a)` for an integer `a`: CPython's key derivation, then
    `init_by_array`.

    The key is `abs(a)` as little-endian 32-bit words, capped at 32 of them,
    which is CPython's own rule (`random_seed` in `_randommodule.c` converts
    the absolute value with `PyObject_AsByteArray(..., PY_LITTLE_ENDIAN, 0)`
    into a `uint32_t key[32]`). So `seed(23)` is the one-word key `[23]` and
    the two words come out little-endian, not big.

    `init_by_array` is three passes and each one is load-bearing:

      1. `init_genrand(19650218)` — a FIXED seed, the reference's own choice,
         which is why two different seeds do not produce two related
         sequences;
      2. 624 rounds mixing the key in, wrapping `i` to 1 and `j` to 0, with
         1664525 as the multiplier and `+ j` in the sum;
      3. 623 further rounds with 1566083941 and `- i`.

    The `mt[0] = 0x80000000` at the end is the reference's, and it is what
    makes the FIRST draw independent of the key's low word.
    """
    var v = a
    if v < 0:
        v = 0 - v
    var words = 0
    var t = v
    while t > 0:
        words = words + 1
        t = t >> 32
    if words == 0:
        words = 1
    if words > MAX_KEY_WORDS:
        words = MAX_KEY_WORDS

    init_genrand(19650218)
    var i = 1
    var j = 0
    var k = N
    while k > 0:
        var prev = _MT[i - 1]
        var key_word = (v >> (32 * j)) & MASK32
        _MT[i] = (((_MT[i] ^ ((prev ^ (prev >> 30)) * INIT_BY_ARRAY_MUL))
                   + key_word + j) & MASK32)
        i = i + 1
        j = j + 1
        if i >= N:
            _MT[0] = _MT[N - 1]
            i = 1
        if j >= words:
            j = 0
        k = k - 1
    k = N - 1
    while k > 0:
        var prev = _MT[i - 1]
        _MT[i] = (((_MT[i] ^ ((prev ^ (prev >> 30)) * INIT_BY_ARRAY_MUL2))
                   - i) & MASK32)
        i = i + 1
        if i >= N:
            _MT[0] = _MT[N - 1]
            i = 1
        k = k - 1
    _MT[0] = 0x80000000
    # `init_by_array` leaves the index AT the end, so the first draw twists
    # before it reads. Measured, not assumed: a reference implementation with
    # the index left at 0 agrees with CPython on `getrandbits(32)` for no seed
    # tried, and with it at 624 for every one of 0, 1, 17, 23, 20260930, 2^32
    # and -7.
    global _MTI
    _MTI = N
    return 0


def getrandbits(k) -> int:
    """`random.getrandbits(k)`: the low `k` bits of fresh draws.

    CPython's own split, and the split is the answer rather than an
    implementation detail: `k <= 32` is ONE 32-bit draw shifted down, and
    anything wider is a sequence of 32-bit draws assembled little-endian, with
    the LAST one shifted down by whatever is left over. A transcription that
    drew `k` bits in one step would be right for 32 and wrong for every other
    width, which is exactly the range `test_formal_time.py` asks for.
    """
    if k <= 0:
        return 0
    if k > 64:
        # CPython would keep drawing words; this path cannot hold the answer in
        # one word, and a truncated answer that LOOKS like a random number is
        # the failure mode this module exists to avoid.
        k = 64
    if k <= 32:
        return _next_uint32() >> (32 - k)
    var low = _next_uint32()
    var high = _next_uint32()
    var rest = k - 32
    if rest < 32:
        high = high >> (32 - rest)
    # NOT masked to 32 bits: the two words ARE the answer, and masking here is
    # the bug a first transcription of the reference makes (`(hi << 32) | lo`
    # is already below 2^64). `k == 64` is the one width whose top half this
    # path cannot hold as CPython spells it: an `Int` is a signed 64-bit word
    # (`doc/ABI.md`), so the answers with bit 63 set arrive negative. The bits
    # are the same 64; only the sign differs, and the widest ask in this
    # repository is `randrange(1, 4e18)` at 62 bits.
    return (high << 32) | low


def randrange(a, b) -> int:
    """`random.randrange(a, b)`: an int in `[a, b)`, CPython's fast path.

    CPython's `randrange` with a `step` of 1 is `a + _randbelow(b - a)`, and
    `_randbelow` is REJECTION SAMPLING, not a modulo: `k = n.bit_length()`, draw
    `k` bits, and redraw while the draw is `>= n`. The modulo spelling is the
    one everybody writes and it is wrong — it biases the low end of the range,
    and for `n` a power of two minus one it changes the answer outright, which
    is a corpus case in `test_formal_random.py` for exactly that reason.

    `width <= 0` is CPython's `ValueError: empty range in randrange(a, b)`,
    which has no spelling on this path (there are no exceptions here,
    `FORMAL.md` phase 7) and is a 0 rather than a plausible number.
    """
    var width = b - a
    if width <= 0:
        return 0
    var k = 0
    var t = width
    while t > 0:
        k = k + 1
        t = t >> 1
    var r = getrandbits(k)
    while r >= width:
        r = getrandbits(k)
    return a + r
