"""`hashlib` — cryptographic digests, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import hashlib` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` in `formal/imports.py` for
why these did NOT go at the repository root, where the first three of them
captured `import os` in the compiler's own sources.

WHAT IS HERE, AND WHY IT IS THE RIGHT SUBSET
--------------------------------------------
CPython's `hashlib` is a factory: `hashlib.sha256(b"...")` constructs a hash
OBJECT with `.update()`, `.digest()` and `.hexdigest()`. None of that is
expressible here, and the reason is the same one that shapes every other
module in this directory: **a value cannot cross a dylib boundary unless it is
one 64-bit word**, and a hash object is 8 to 64 bytes of state that has to
survive between calls (`bugs/FORMAL_module_state_no_storage.md`). So every
digest here is ONE FUNCTION taking a byte string and a length and returning
its hex digest — the shape `test_formal_hashlib.py` checks against CPython
byte for byte.

That is a real difference from CPython and it is stated at every definition
rather than left to be discovered. A program that needs incremental hashing
concatenates first and hashes once. A program that needs the raw bytes rather
than hex has a `_raw` variant, which writes into a caller-supplied buffer
because a `bytes` object cannot cross the boundary either.

  * SIX DIGESTS COME FROM CommonCrypto, which libSystem provides and the
    image already links: `CC_MD5`, `CC_SHA1`, `CC_SHA224`, `CC_SHA256`,
    `CC_SHA384` and `CC_SHA512`. Each was measured to bind on this target
    (asked of libSystem with `dlsym`) and to produce CPython's own answer
    before it was relied on. That is six of CPython's fourteen guaranteed
    algorithms from one call each, and it is why most of this file is a
    transcription of an API rather than of an algorithm.

  * BLAKE2b IS COMPUTED HERE, because libSystem does not have it. Measured:
    no `blake2*` symbol is in libSystem, and `py314_cache.py` — one of the
    three files this module unblocks — asks for exactly
    `hashlib.blake2b(digest_size=20)`. The implementation is RFC 7693 and is
    checked against CPython over every length from 0 to 300 plus a seeded
    random spread, so the empty message, the single-block boundary at 128 and
    the two-block case are covered rather than assumed.

  * BOTH BACKENDS TODAY, for the reason `formal/hostmods/os/__init__.mojo` gives
    at length: a module dylib that calls into the C library builds and runs
    under `--backend=x86_64` as well, and the claim this replaces was false.
    BLAKE2b itself is pure integer arithmetic and never needed the C library;
    it is in this file because `hashlib` is the name a caller reaches for.

WHAT IS NOT HERE, AND WHY
-------------------------
`blake2s`, `sha3_224`, `sha3_256`, `sha3_384`, `sha3_512`, `shake_128` and
`shake_256` are ABSENT rather than approximated. Each is absent for the same
measured reason — libSystem provides none of them, so each would be a
from-scratch implementation of a specification nobody has checked here — and
SHAKE additionally needs an extendable output, which is a run-time-length
sequence this path cannot build
(`bugs/FORMAL_listdir_no_run_time_sequence.md`). They are named in
`bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md` with the measurements and the
next step, and `test_formal_hashlib.py`'s `absent` group asserts each one is
refused with a message naming itself, so an omission can never be mistaken
for an implementation.

`algorithms_available`, `algorithms_guaranteed` and `new()` are absent for a
different reason: they are containers, or they are the factory that cannot
exist. `md5` and `sha1` ARE here and are usable, which is worth saying plainly
because they are NOT safe for anything security-bearing — CPython's own
documentation says so, and a digest module that made them hard to reach would
be a worse mirror than one that does not.
"""

MASK64 = 0xFFFFFFFFFFFFFFFF
HEX_DIGITS = "0123456789abcdef"


# ── a byte-addressed word buffer ────────────────────────────────────────────
#
# EVERYTHING below is built on these four, and the reason is a measured limit
# rather than a style choice: this path has no container a function can index.
#
#  * `p[i]` on a `Pointer[Int]` or `Pointer[UInt8]` is NOT an element read. It
#    takes the blob path, reads a COUNT from offset 0 and bounds-checks the
#    index against it — so on a `malloc`'d buffer, whose first word `malloc`
#    zeroed, `p[0]` is a silent `exit(1)` with no message, and on a string
#    literal it is a plausible wrong number assembled from adjacent
#    characters. `bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md`
#    has the disassembly.
#  * `q.value()` on a pointer with a DECLARED pointee IS a correct one-byte
#    load, which is what `byte_at` below uses. The declaration has to belong
#    to a single binding: `(b + i).value()` is refused, because the
#    expression declares no type and the load's width comes from the pointee.
#  * There is no assignment through `.value()` at all — the target must be a
#    plain name — so a write is a `memcpy` from a one-byte scratch buffer.
#  * A struct cannot be RETURNED from a function that received it as a
#    parameter: the frame belongs to the caller and the analysis refuses the
#    return rather than hand back a dead address. That rules out the obvious
#    "state is a struct, `G` takes it and returns it" spelling, and it is why
#    the state below is a byte buffer addressed by OFFSET.
#
# So: the state is a `malloc`'d buffer, a 64-bit word lives at a byte offset
# that is a multiple of 8, and the mixing function takes offsets. That is
# less direct than an array and it is the only spelling measured to work.

def byte_at(buf: Pointer[UInt8], i: int) -> int:
    """`buf[i]` as the integer 0..255."""
    var q: Pointer[UInt8] = buf + i
    return q.value()


def byte_store(buf: Pointer[UInt8], i: int, b: int) -> int:
    """`buf[i] = b`. Returns 0."""
    var one: Pointer[UInt8] = malloc(1)
    memset(one, b & 255, 1)
    memcpy(buf + i, one, 1)
    return 0


def word_get(buf: Pointer[UInt8], at: int) -> int:
    """The 8 bytes at `at` as a little-endian 64-bit word.

    Assembled a byte at a time because there is no 64-bit load from a byte
    pointer on this path, and a wrong word here is a wrong digest with nothing
    to say so. The shift is by a VARIABLE amount on purpose: the immediate
    form `x << 8*k` is wrong for every amount above 8 on arm64, which is
    `bugs/FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md`.
    """
    var v = 0
    var k = 0
    while k < 8:
        v = v | (byte_at(buf, at + k) << (8 * k))
        k = k + 1
    return v


def word_put(buf: Pointer[UInt8], at: int, x: int) -> int:
    """The 8 bytes of `x`, little-endian, at `at`. Returns 0."""
    var k = 0
    while k < 8:
        byte_store(buf, at + k, (x >> (8 * k)) & 255)
        k = k + 1
    return 0


def to_hex(buf: Pointer[UInt8], at: int, n: int) -> str:
    """`n` bytes at `at` as lowercase hex, in a buffer the caller owns.

    The single place a digest becomes a string, so every function below is one
    `memcpy` from CPython's `.hexdigest()` and there is no second hex encoder
    to disagree with this one.
    """
    var out: Pointer[UInt8] = malloc(2 * n + 1)
    var i = 0
    while i < n:
        var b = byte_at(buf, at + i)
        var hi: Pointer[UInt8] = HEX_DIGITS + (b >> 4)
        var lo: Pointer[UInt8] = HEX_DIGITS + (b & 15)
        memcpy(out + 2 * i, hi, 1)
        memcpy(out + 2 * i + 1, lo, 1)
        i = i + 1
    memcpy(out + 2 * n, "", 1)
    return out


# ── the six CommonCrypto digests ────────────────────────────────────────────
#
# `CC_<name>(data, len, out)` — one call, the digest in a buffer the caller
# owns. `data` is a `char *` and `len` its length, because a formal string is
# a bare NUL-terminated `char *` and a program holding a pointer and a count
# (a file's contents, a substring) should be able to say so. A literal's own
# length is the count to pass, which the tests do.

def md5_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.md5(data).digest()` into `out`; `out` needs 16 bytes. 0."""
    CC_MD5(data, n, out)
    return 0


def sha1_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.sha1(data).digest()` into `out`; 20 bytes. 0."""
    CC_SHA1(data, n, out)
    return 0


def sha224_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.sha224(data).digest()` into `out`; 28 bytes. 0."""
    CC_SHA224(data, n, out)
    return 0


def sha256_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.sha256(data).digest()` into `out`; 32 bytes. 0."""
    CC_SHA256(data, n, out)
    return 0


def sha384_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.sha384(data).digest()` into `out`; 48 bytes. 0."""
    CC_SHA384(data, n, out)
    return 0


def sha512_raw(data, n, out: Pointer[UInt8]) -> int:
    """`hashlib.sha512(data).digest()` into `out`; 64 bytes. 0."""
    CC_SHA512(data, n, out)
    return 0


def md5(data, n) -> str:
    """`hashlib.md5(data).hexdigest()`. NOT SAFE FOR SECURITY.

    Present because it is a real digest and CPython has it, not because it
    should be used for anything an adversary can affect; CPython's own
    documentation says the same. `n` is the byte count.
    """
    var out: Pointer[UInt8] = malloc(16)
    CC_MD5(data, n, out)
    return to_hex(out, 0, 16)


def sha1(data, n) -> str:
    """`hashlib.sha1(data).hexdigest()`. NOT SAFE FOR SECURITY — see `md5`."""
    var out: Pointer[UInt8] = malloc(20)
    CC_SHA1(data, n, out)
    return to_hex(out, 0, 20)


def sha224(data, n) -> str:
    """`hashlib.sha224(data).hexdigest()`."""
    var out: Pointer[UInt8] = malloc(28)
    CC_SHA224(data, n, out)
    return to_hex(out, 0, 28)


def sha256(data, n) -> str:
    """`hashlib.sha256(data).hexdigest()`."""
    var out: Pointer[UInt8] = malloc(32)
    CC_SHA256(data, n, out)
    return to_hex(out, 0, 32)


def sha384(data, n) -> str:
    """`hashlib.sha384(data).hexdigest()`."""
    var out: Pointer[UInt8] = malloc(48)
    CC_SHA384(data, n, out)
    return to_hex(out, 0, 48)


def sha512(data, n) -> str:
    """`hashlib.sha512(data).hexdigest()`."""
    var out: Pointer[UInt8] = malloc(64)
    CC_SHA512(data, n, out)
    return to_hex(out, 0, 64)


# ── BLAKE2b, RFC 7693 ───────────────────────────────────────────────────────
#
# The state is 8 words, the working vector is 16, and both live in one byte
# buffer addressed by offset (see the note at the top of this section for why
# there is no array). Offsets are `8 * word`, so `v[0]` is byte 0 and `v[15]`
# is byte 120.

IV0 = 0x6a09e667f3bcc908
IV1 = 0xbb67ae8584caa73b
IV2 = 0x3c6ef372fe94f82b
IV3 = 0xa54ff53a5f1d36f1
IV4 = 0x510e527fade682d1
IV5 = 0x9b05688c2b3e6c1f
IV6 = 0x1f83d9abfb41bd6b
IV7 = 0x5be0cd19137e2179


def rotr64(x: int, n: int) -> int:
    """`x` rotated right by `n` bits, as a 64-bit word.

    THE VARIABLE SHIFT IS LOAD-BEARING, and this is the most important comment
    in the file. `n` is a parameter, not a literal, so this lowers to `LSRV`
    rather than `LSL #imm` — and the immediate form of `<<` is WRONG for
    every amount above 8 on arm64: `1 << 12` returns `16`. That is a
    one-constant defect in `formal/arm64.py`'s `encode_lsl_xd_xn_imm`, it is
    not this file's to fix, and it is measured against clang's own assembler
    in `bugs/FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md`.

    BLAKE2b needs rotations by 16, 24, 32 and 63, every one of them in the
    broken range, so writing this with the immediate form would have produced
    a digest that is wrong and looks fine.

    And `>>` needs a MASK, because on this path it is always an ARITHMETIC
    shift: `(-5) >> 4` fills the top four bits with ones, and a rotation needs
    zeros there. Masking to `n` bits of headroom turns it into the logical
    shift the specification means, using only operations that are correct —
    the inner `1 << (64 - n)` is itself a variable shift, so it is `LSLV`.

    So the cost of correctness here is three extra ALU instructions per
    rotation instead of one bare `LSL #n`, which is the right trade on a
    backend whose job is to be trustworthy rather than fast. When those fixes
    land this should be revisited on purpose and the digest test re-run — not
    changed blind.
    """
    if n == 0:
        return x
    return ((x >> n) & ((1 << (64 - n)) - 1)) | (x << (64 - n))


# THE EIGHT `G` CALL SITES, as the four working-vector words each one mixes,
# packed low-to-high into four NIBBLES of one word. `b2_g` unpacks them.
#
# Byte offset = word index * 8, and there are 16 words, so every index is four
# bits and four of them fit in one word with room to spare. That packing is
# what keeps `b2_g` inside the SIX integer argument registers both backends
# pass: it took `v, a, b, c, d, x, y` — seven, one too many for x86-64 — and
# the module could not be built for x86-64 at all
# (`b2_g: 7 parameters exceeds the 6 the formal x86-64 ABI passes in
# registers`), which is three of the files that import it.
#
# The offsets themselves are NOT derivable from anything smaller, which is why
# they are packed rather than computed: the four COLUMNS are (d, d+4, d+8,
# d+12) but the four DIAGONALS are not an arithmetic progression — {1, 6, 11,
# 12} has steps 5, 5, 1 — so a base and a stride cannot spell them and each is
# written out.
_Q_C0 = 0xC840       # column  0: words 0, 4, 8, 12   (bytes   0,  32,  64,  96)
_Q_C1 = 0xD951       # column  1: words 1, 5, 9, 13   (bytes   8,  40,  72, 104)
_Q_C2 = 0xEA62       # column  2: words 2, 6, 10, 14  (bytes  16,  48,  80, 112)
_Q_C3 = 0xFB73       # column  3: words 3, 7, 11, 15  (bytes  24,  56,  88, 120)
_Q_D0 = 0xFA50       # diagonal 0: words 0, 5, 10, 15 (bytes   0,  40,  80, 120)
_Q_D1 = 0xCB61       # diagonal 1: words 1, 6, 11, 12 (bytes   8,  48,  88,  96)
_Q_D2 = 0xD872       # diagonal 2: words 2, 7, 8, 13  (bytes  16,  56,  64, 104)
_Q_D3 = 0xE943       # diagonal 3: words 3, 4, 9, 14  (bytes  24,  32,  72, 112)


def b2_g(v: Pointer[UInt8], q: int, x: int, y: int) -> int:
    """The BLAKE2b `G` function, on the four slots `q` names, mixing in `x`, `y`.

    `q` is four packed nibbles — see the constants above, which is where the
    offsets are written out and why they cannot be computed. Offsets rather
    than indices because this path has no container a function can index, and
    the mixing function has to name its slots dynamically — the whole point of
    `G` is that the same eight lines run on eight different column/diagonal
    slot sets.
    """
    a = (q & 15) * 8
    b = ((q >> 4) & 15) * 8
    c = ((q >> 8) & 15) * 8
    d = ((q >> 12) & 15) * 8
    word_put(v, a, (word_get(v, a) + word_get(v, b) + x) & MASK64)
    word_put(v, d, rotr64(word_get(v, d) ^ word_get(v, a), 32))
    word_put(v, c, (word_get(v, c) + word_get(v, d)) & MASK64)
    word_put(v, b, rotr64(word_get(v, b) ^ word_get(v, c), 24))
    word_put(v, a, (word_get(v, a) + word_get(v, b) + y) & MASK64)
    word_put(v, d, rotr64(word_get(v, d) ^ word_get(v, a), 16))
    word_put(v, c, (word_get(v, c) + word_get(v, d)) & MASK64)
    word_put(v, b, rotr64(word_get(v, b) ^ word_get(v, c), 63))
    return 0


def b2_round(v: Pointer[UInt8], m: Pointer[UInt8], sg: Pointer[UInt8],
             s: int) -> int:
    """One BLAKE2b round: eight `G` calls, with message word `sg[s+k]` in slot k.

    `m` is a 16-word message block, `sg` is the flattened SIGMA permutation
    (see `sigma_table`) and `s` is a BASE INDEX of 16 into it. The row is not
    a table of its own because a table is a container this path cannot index;
    instead SIGMA's ten rows are written end to end into one 160-byte buffer
    and each round reads sixteen bytes at its base. BLAKE2b runs TWELVE rounds
    over a TEN-row permutation, which is why `b2_compress` ends with base 0
    and base 16 again.
    """
    b2_g(v, _Q_C0, word_get(m, 8 * byte_at(sg, s)),
         word_get(m, 8 * byte_at(sg, s + 1)))
    b2_g(v, _Q_C1, word_get(m, 8 * byte_at(sg, s + 2)),
         word_get(m, 8 * byte_at(sg, s + 3)))
    b2_g(v, _Q_C2, word_get(m, 8 * byte_at(sg, s + 4)),
         word_get(m, 8 * byte_at(sg, s + 5)))
    b2_g(v, _Q_C3, word_get(m, 8 * byte_at(sg, s + 6)),
         word_get(m, 8 * byte_at(sg, s + 7)))
    b2_g(v, _Q_D0, word_get(m, 8 * byte_at(sg, s + 8)),
         word_get(m, 8 * byte_at(sg, s + 9)))
    b2_g(v, _Q_D1, word_get(m, 8 * byte_at(sg, s + 10)),
         word_get(m, 8 * byte_at(sg, s + 11)))
    b2_g(v, _Q_D2, word_get(m, 8 * byte_at(sg, s + 12)),
         word_get(m, 8 * byte_at(sg, s + 13)))
    b2_g(v, _Q_D3, word_get(m, 8 * byte_at(sg, s + 14)),
         word_get(m, 8 * byte_at(sg, s + 15)))
    return 0


def put4(sg: Pointer[UInt8], at: int, a0: int, a1: int, a2: int,
         a3: int) -> int:
    """Write four SIGMA indices at `at`. Returns 0.

    FOUR, and not sixteen, because of the ABI this module has to fit in BOTH
    backends' terms, and SIX is the smaller of the two: arm64 passes eight
    integer argument registers (X0-X7) and x86-64 passes six (RDI/RSI/RDX/RCX/
    R8/R9), so a module both backends compile has to fit six
    (`bugs/FORMAL_arm64_ninth_argument_is_silently_dropped.md` for what the
    seventh and beyond used to do on arm64 — silently dropped and read as
    zero, with no diagnostic at either end, which produced a BLAKE2b digest
    that was plausible and incorrect). A sixteen-way `put16` is the obvious
    spelling of "write one row" and it is wrong twice over: too wide for
    either backend here, and a digest nobody could tell from a right one.

    It was `put6` + `put6` + `put4` per row, which fit arm64's eight and not
    x86-64's six — `put6: 8 parameters exceeds the 6 …`. A row is now four
    `put4`s, and `put6` is gone rather than left beside the thing that
    replaced it.
    """
    byte_store(sg, at, a0)
    byte_store(sg, at + 1, a1)
    byte_store(sg, at + 2, a2)
    byte_store(sg, at + 3, a3)
    return 0


def sigma_table() -> Pointer[UInt8]:
    """RFC 7693's SIGMA, its ten rows written end to end into 160 bytes.

    Built at RUN TIME into a `malloc`'d buffer rather than being a
    module-level list, for the reason at the top of this section: a
    module-level name that is not a literal-only constant has nowhere to live
    (`bugs/FORMAL_module_state_no_storage.md`), and a list is not a
    literal-only constant. Sixteen bytes per row, so row r starts at 16*r and
    a round's base index is a constant at each call site in `b2_compress`.
    """
    var sg: Pointer[UInt8] = malloc(160)
    memset(sg, 0, 160)
    # row 0: 0..15
    var i = 0
    while i < 16:
        byte_store(sg, i, i)
        i = i + 1
    # row 1: 14 10  4  8  9 15 13  6  1 12  0  2 11  7  5  3
    row1(sg, 16)
    # row 2: 11  8 12  0  5  2 15 13 10 14  3  6  7  1  9  4
    row2(sg, 32)
    # row 3:  7  9  3  1 13 12 11 14  2  6  5 10  4  0 15  8
    row3(sg, 48)
    # row 4:  9  0  5  7  2  4 10 15 14  1 11 12  6  8  3 13
    row4(sg, 64)
    # row 5:  2 12  6 10  0 11  8  3  4 13  7  5 15 14  1  9
    row5(sg, 80)
    # row 6: 12  5  1 15 14 13  4 10  0  7  6  3  9  2  8 11
    row6(sg, 96)
    # row 7: 13 11  7 14 12  1  3  9  5  0 15  4  8  6  2 10
    row7(sg, 112)
    # row 8:  6 15 14  9 11  3  0  8 12  2 13  7  1  4 10  5
    row8(sg, 128)
    # row 9: 10  2  8  4  7  6  1  5 15 11  9 14  3 12 13  0
    row9(sg, 144)
    return sg


def row1(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 14, 10, 4, 8)
    put4(sg, at + 4, 9, 15, 13, 6)
    put4(sg, at + 8, 1, 12, 0, 2)
    put4(sg, at + 12, 11, 7, 5, 3)
    return 0


def row2(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 11, 8, 12, 0)
    put4(sg, at + 4, 5, 2, 15, 13)
    put4(sg, at + 8, 10, 14, 3, 6)
    put4(sg, at + 12, 7, 1, 9, 4)
    return 0


def row3(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 7, 9, 3, 1)
    put4(sg, at + 4, 13, 12, 11, 14)
    put4(sg, at + 8, 2, 6, 5, 10)
    put4(sg, at + 12, 4, 0, 15, 8)
    return 0


def row4(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 9, 0, 5, 7)
    put4(sg, at + 4, 2, 4, 10, 15)
    put4(sg, at + 8, 14, 1, 11, 12)
    put4(sg, at + 12, 6, 8, 3, 13)
    return 0


def row5(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 2, 12, 6, 10)
    put4(sg, at + 4, 0, 11, 8, 3)
    put4(sg, at + 8, 4, 13, 7, 5)
    put4(sg, at + 12, 15, 14, 1, 9)
    return 0


def row6(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 12, 5, 1, 15)
    put4(sg, at + 4, 14, 13, 4, 10)
    put4(sg, at + 8, 0, 7, 6, 3)
    put4(sg, at + 12, 9, 2, 8, 11)
    return 0


def row7(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 13, 11, 7, 14)
    put4(sg, at + 4, 12, 1, 3, 9)
    put4(sg, at + 8, 5, 0, 15, 4)
    put4(sg, at + 12, 8, 6, 2, 10)
    return 0


def row8(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 6, 15, 14, 9)
    put4(sg, at + 4, 11, 3, 0, 8)
    put4(sg, at + 8, 12, 2, 13, 7)
    put4(sg, at + 12, 1, 4, 10, 5)
    return 0


def row9(sg: Pointer[UInt8], at: int) -> int:
    put4(sg, at + 0, 10, 2, 8, 4)
    put4(sg, at + 4, 7, 6, 1, 5)
    put4(sg, at + 8, 15, 11, 9, 14)
    put4(sg, at + 12, 3, 12, 13, 0)
    return 0


def b2_compress(h: Pointer[UInt8], block: Pointer[UInt8], t: int,
                last: int) -> int:
    """The BLAKE2b compression function: fold one 128-byte block into `h`.

    `h` is 8 words and is updated in place; `block` is the 128-byte block,
    zero-padded by the caller; `t` is the number of message bytes compressed
    so far INCLUDING this block; `last` is 1 for the final block, which is
    what sets `f[14]`.

    The message block is 16 words of EIGHT bytes each. That is worth stating
    because the reference implementation many people transcribe from uses 16
    bytes per word, which is BLAKE2**s**'s block width and is wrong here in a
    way that is invisible for any message of 8 bytes or fewer — the two
    layouts only start to differ past the first word.
    """
    # The working vector: h, then the IV, then the offset words.
    var v: Pointer[UInt8] = malloc(128)
    var i = 0
    while i < 8:
        word_put(v, 8 * i, word_get(h, 8 * i))
        i = i + 1
    word_put(v, 64, IV0)
    word_put(v, 72, IV1)
    word_put(v, 80, IV2)
    word_put(v, 88, IV3)
    word_put(v, 96, IV4)
    word_put(v, 104, IV5)
    word_put(v, 112, IV6)
    word_put(v, 120, IV7)
    # The high half of the 128-bit counter `t` is `t >> 64` in RFC 7693, and
    # this path CANNOT COMPUTE IT: a shift of 64 or more wraps to the amount
    # modulo 64
    # (bugs/FORMAL_shift_by_64_or_more_wraps_instead_of_saturating.md), so
    # `t >> 64` would XOR the WHOLE counter back in and change the digest. It
    # is 0 for every message this target can hash, and that is arithmetic
    # rather than a guess: `t` counts BYTES of one buffer, a 64-bit address
    # space caps a buffer at 2**48 bytes, and 2**48 < 2**64. So the constant
    # below is the correct value over the whole reachable domain.
    word_put(v, 96, word_get(v, 96) ^ t)
    if last == 1:
        word_put(v, 112, word_get(v, 112) ^ MASK64)

    # One SIGMA table for all twelve rounds: building it per round would
    # be twelve identical mallocs, and the table is the same every time.
    var sg: Pointer[UInt8] = sigma_table()

    b2_round(v, block, sg, 0)
    b2_round(v, block, sg, 16)
    b2_round(v, block, sg, 32)
    b2_round(v, block, sg, 48)
    b2_round(v, block, sg, 64)
    b2_round(v, block, sg, 80)
    b2_round(v, block, sg, 96)
    b2_round(v, block, sg, 112)
    b2_round(v, block, sg, 128)
    b2_round(v, block, sg, 144)
    b2_round(v, block, sg, 0)
    b2_round(v, block, sg, 16)

    i = 0
    while i < 8:
        word_put(h, 8 * i,
                 word_get(h, 8 * i) ^ word_get(v, 8 * i) ^ word_get(v, 8 * (i + 8)))
        i = i + 1
    free(v)
    free(sg)
    return 0


def blake2b_hex(data, n: int, digest_size: int) -> str:
    """`hashlib.blake2b(data, digest_size=digest_size).hexdigest()`.

    `digest_size` is CPython's parameter and defaults to 64 there; it is
    REQUIRED here because a default argument does not survive a dylib
    boundary — the caller has no signature to materialize it from, so the
    argument register is whatever the caller last left in it, measured
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). 1 to 64,
    as in CPython.

    The truncated output is CPython's: BLAKE2b's `digest_length` is part of
    the initial state, so `digest_size=20` is a DIFFERENT HASH and not the
    first 20 bytes of the 64-byte one. Both are in the test.
    """
    var h: Pointer[UInt8] = malloc(64)
    word_put(h, 0, IV0)
    word_put(h, 8, IV1)
    word_put(h, 16, IV2)
    word_put(h, 24, IV3)
    word_put(h, 32, IV4)
    word_put(h, 40, IV5)
    word_put(h, 48, IV6)
    word_put(h, 56, IV7)
    # The parameter block: byte 0 digest_length, byte 1 key_length,
    # byte 2 fanout, byte 3 depth. Only word 0 is non-zero, and it is
    # `digest_size | (fanout << 16) | (depth << 24)`. Getting fanout and depth
    # in the right BYTES matters: with depth at byte 2 the digest is wrong for
    # every input, which is how this was found.
    var p0 = digest_size + 65536 + 16777216
    word_put(h, 0, word_get(h, 0) ^ p0)

    # A keyed BLAKE2b would prepend a 128-byte key block here. This module
    # does not support keys: `key=` is not a parameter, so there is no
    # spelling here that silently hashes without one.
    var block: Pointer[UInt8] = malloc(128)
    var consumed = 0
    var t = 0
    # Every block but the last is a full 128 bytes and is NOT final. The loop
    # condition is `> 128` and not `>=`: a message whose length is an exact
    # multiple of 128 has its last full block compressed as the FINAL block,
    # with no empty block after it, which is what RFC 7693 specifies and what
    # CPython does.
    while n - consumed > 128:
        memcpy(block, data + consumed, 128)
        t = t + 128
        b2_compress(h, block, t, 0)
        consumed = consumed + 128
    # The final block: the remaining bytes, zero-padded to 128. A message
    # that is an exact multiple of 128 arrives here with `rest == 0`, and the
    # all-zero block with `t` already at the full length is the right final
    # block in that case.
    var rest = n - consumed
    memset(block, 0, 128)
    if rest > 0:
        memcpy(block, data + consumed, rest)
    t = t + rest
    b2_compress(h, block, t, 1)
    free(block)
    return to_hex(h, 0, digest_size)
