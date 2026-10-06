"""struct — binary pack/unpack for the formal backends.

CPython's `struct` is "pure computation over representable values" (see
`formal/imports.py`'s HOST_MODELLED comment, which names `struct` among the
reachable-in-principle modules): packing a `<I` is shifts and masks, and
nothing here needs an object a freestanding image that links libSystem and
nothing else does not have. That is what makes this file possible, and it is
why `struct` in HOST_MODELLED was a lie and no longer is.

It lives in `formal/hostmods/` beside this backend's `os` and `sys`, which
`formal/imports.py` adds to every file's search roots as its last entry. It
did NOT live at the repository root, where it was first written: the root is a
search root for four independent resolvers, so a Mojo `struct` there captured
`import struct` in the compiler's own sources. See `_HOSTMODS_ROOT`.

THE FORMAT SUBSET, MEASURED
---------------------------
Every format-shaped string literal in every `formal/*.py` and
`test_x86_64_decode.py` — the seven files the sweep reported plus
`formal/build.py` and `formal/arm64_proof_gen.py`, which import `struct`
too and were not in that list because they are not themselves blocked on it:

    <I   x104  uint32     <QQ         x7   two uint64
    <i   x10   int32      <QQq        x1   uint64, uint64, int64
    <Q   x7    uint64     <HHIQQQI / <HHHHHH / <IIQQQQQQ / <IBBHQQ / <III
    <q   x1    int64      <4sBBBBBBB5x      (elf.py's e_ident: the only `s`)
    <II  x3    two uint32 (formal/build.py:  a Mach-O load command's pair)
    <8I  x1    eight uint32 (formal/build.py: a dylib's 32-byte header)

So: a `<` byte-order prefix (little-endian, standard sizes, no alignment), the
integer codes `b B h H i I l L q Q`, the pad code `x`, and `s`, each with an
optional leading repeat count (`4s`, `8I`, `5x` all occur). Every format in
the corpus is `<`-prefixed, so `>`, `=`, `!` and native `@` are NOT
implemented: a byte order this file gets wrong is a silently wrong Mach-O
header, which is the worst outcome available. `struct.Struct` is not provided
either — it would be a module-level name, and those are refused
(`model.module_global_refusal`).

Note that `pack` and `unpack_from` want DIFFERENT formats, and the table
serves both: the packing formats come from the instruction encoders and the
ELF writer, and the two `build.py` formats are read-only
(`struct.unpack_from("<8I", data, 0)` is a 32-byte dylib header). An earlier
version of this file had every format `elf.py` uses and neither `build.py`
one, because the sweep's seven-file list was read as the whole set of
callers; it was not, and the test now walks the tree rather than a list.

THE VALUE MODEL: A BYTE STRING IS A LIST OF INTS
------------------------------------------------
A formal value is ONE 64-bit word and a container is a frame-allocated blob of
8-byte slots, so a `bytes` object has no representation on this path at all
(`bytes([1,2,3])` lowers to a call to a symbol nothing defines). A byte string
here is a **list of ints, one per byte** — the same shape
`formal/arm64.py`'s `Assembler.sections["text"]` already is, and `buf[i] = v`
is how a byte is written. This is the same substitution the backend already
makes for `str` (a bare `char *`).

FOUR LIMITS THIS FILE IS WRITTEN AROUND — all measured
------------------------------------------------------
1. **A subscript on a `String`-annotated PARAMETER is a silent wrong answer.**
   `fmt[1]` reads the list blob's count field instead of a byte, because
   `_is_string_subscript` consults only the flow-sensitive `_string_vars` and
   not the whole-function `ValueKinds` that already answers `str` for it.
   Measured: `f(s: String): return s[0]` returns a text-section address where
   65 is correct. Filed as
   `bugs/CODEGEN_string_parameter_subscript_reads_count_field.md`.
   Consequence here: the format is recognised by `==` against literals, never
   by indexing it.

2. **No variadic ABI, and the two backends pass DIFFERENT numbers of
   arguments.** `_refuse_variadic_reads` refuses a body that reads `*args`,
   and a call to a callee with DEFAULTS leaves unsupplied parameters as
   whatever was in the argument registers — measured, `two(1, 2)` into an
   eight-parameter callee returned 677441874805190 where 12000000 is correct.
   So `pack` and `pack_into` take FIXED signatures and read only as many
   values as the format names. The unread parameters being garbage is not
   observable: measured across the boundary, `pick2(7, 9)` returns 709 and
   `pick5(1,2,3,4,5)` returns 123405, both correct.

   The ceiling is the SMALLER of the two ABIs, which is six: arm64's AAPCS
   passes integer arguments in X0-X7 (eight), while x86-64's SysV passes them
   in RDI/RSI/RDX/RCX/R8/R9 (six, `formal/x86_64.py`'s `ARG_REGS`). Sized to
   arm64 alone, this module built on arm64 and was REFUSED on x86-64 —
   `pack_into: 8 parameters exceeds the 6 the formal x86-64 ABI passes in
   registers` — which is the whole reason the signatures below are six
   arguments wide and not eight. A cross-backend module has to be written to
   the intersection, and that is not discoverable from either backend alone.

3. **`len()` of a list a CALLEE returned is refused** — the callee's declared
   return type carries no list-ness, so `len(w)` after `w = f()` is refused
   while `w[0]` and `w == []` both work. Consequence here: this file never
   takes a container's length. `_nvalues` and `_width_at` answer one WORD
   each, which is why they are two functions rather than one list being
   summed.

4. **A list built inside a function lives in THAT function's frame.** A
   returned list is therefore a read of a frame the caller does not own.
   Measured: a 4-element list returned by one function and read after a
   second function allocated its own list came back with the second
   function's data. Consequence here: `pack_into` — the form the twelve
   `pack_into` call sites use — writes through the CALLER's list and so is
   sound, and it is the form the tests below pin hardest. `pack` returns a
   list built in its own frame; the corpus consumes a `pack` result
   immediately (`.extend` into the buffer that is about to be returned), so
   it is correct in that shape, and `bugs/FORMAL_known_limits.md` is where a
   reader should look for the general case.

ERRORS
------
CPython raises `struct.error` for a format it cannot compile. Raising is not
available here (a `raise ValueError(...)` lowers to a call to a symbol nothing
defines), so the honest degradation is a RETURN VALUE: `calcsize` returns 0,
`pack` and `unpack_from` return an empty list, for a format this file does
not implement. Every call site in the corpus consumes a `pack` result by
extending a buffer, where an empty list appends nothing and the defect
surfaces downstream as a short buffer rather than as a plausible wrong
number. A real difference from CPython, recorded here rather than hidden.
"""

from os._syscalls import str_at, str_eq_n


# ── the format, as one word per question ─────────────────────────────────────
# Every helper answers a single scalar, because a scalar is the only thing
# this path can carry across a call boundary without a length (limit 3). The
# chain of `==` is also the only string test that works on a parameter
# (limit 1). Ordered by corpus frequency: `<I` is 104 of 130 sites.

def _nvalues(fmt: String) -> int:
    """How many VALUES a format names. 0 means "not implemented here".

    Distinct from `calcsize` on purpose: a `5x` pad names no value and still
    emits bytes, and a repeat count widens one value rather than adding
    several. A caller that wants the value count (to pick argument slot k) and
    one that wants the byte count (to size a buffer) ask different questions
    and are answered differently.
    """
    if fmt == "<I" or fmt == "<i":
        return 1
    if fmt == "<Q" or fmt == "<q":
        return 1
    if fmt == "<H" or fmt == "<h":
        return 1
    if fmt == "<B" or fmt == "<b":
        return 1
    if fmt == "<L" or fmt == "<l":
        return 1
    if fmt == "<QQ":
        return 2
    if fmt == "<HH":
        return 2
    if fmt == "<II":
        return 2
    if fmt == "<8I":
        return 8
    if fmt == "<QQq":
        return 3
    if fmt == "<III":
        return 3
    if fmt == "<HHHHHH":
        return 6
    if fmt == "<IBBHQQ":
        return 6
    if fmt == "<HHIQQQI":
        return 7
    if fmt == "<IIQQQQQQ":
        return 8
    if fmt == "<4sBBBBBBB5x":
        return 8
    return 0


def _width_at(fmt: String, k: Int) -> int:
    """Byte width of the k-th value. 0 past the end, and 0 for no format.

    The per-format table, read by index rather than returned as a list
    because `len()` of a returned list is refused (limit 3). In
    `<4sBBBBBBB5x` the `4s` is 4 bytes and each of the seven `B`s is 1; the
    trailing `5x` names no value, so it is `calcsize`'s business and not this
    function's.
    """
    if fmt == "<I" or fmt == "<i" or fmt == "<L" or fmt == "<l":
        return 4
    if fmt == "<Q" or fmt == "<q":
        return 8
    if fmt == "<H" or fmt == "<h":
        return 2
    if fmt == "<B" or fmt == "<b":
        return 1
    if fmt == "<QQ" or fmt == "<QQq":
        return 8
    if fmt == "<II" or fmt == "<III" or fmt == "<8I":
        return 4
    if fmt == "<HH" or fmt == "<HHHHHH":
        return 2
    if fmt == "<HHIQQQI":
        if k == 0:
            return 2
        if k == 1:
            return 2
        if k == 2:
            return 4
        if k == 6:
            return 4
        return 8
    if fmt == "<IBBHQQ":
        if k == 0:
            return 4
        if k == 1:
            return 1
        if k == 2:
            return 1
        if k == 3:
            return 2
        return 8
    if fmt == "<IIQQQQQQ":
        if k == 0:
            return 4
        if k == 1:
            return 4
        return 8
    if fmt == "<4sBBBBBBB5x":
        if k == 0:
            return 4
        return 1
    return 0


def calcsize(fmt: String) -> int:
    """Bytes `pack(fmt, ...)` produces. 0 for a format this file will not size.

    CPython raises `struct.error`; see the docstring's ERRORS.

    **THIS IS A PARSER AND NOT THE TABLE, and that changed because CPython's own
    `test_struct.py` has `calcsize('iii')`, `calcsize('b')`, `calcsize('l')`,
    `calcsize('n')` and `calcsize('P')` and every one of them used to answer 0.**
    A size question with an answer, refused, because `_nvalues` below is a table
    of the seventeen exact format strings this repository's own callers use and
    nothing else. That table is the right shape for `pack` and `unpack_from`,
    which need a BYTE ORDER this file deliberately does not implement; it is
    the wrong shape for a size, which is a property of the grammar rather than
    of the corpus. The cases came from generating `test_struct.py` rather than
    reading it — see `test_formal_hostmods_conformance.py`.

    THE GRAMMAR, IN FULL, because a size is not a byte order:

        [<order>] then items, where an item is [<count>] <code>
        <order>   `<` `>` `=` `!`  standard sizes, no alignment
                  `@` or ABSENT   native sizes, native alignment

    and the codes are `x c b B h H i I l L q Q n N P s p ?`. The three places
    the byte order changes the SIZE and not the meaning:

      * `l` and `L` are 4 bytes standard and 8 native. Every other integer code
        is the same width either way on this target, which is why CPython's
        `calcsize('l')` is 8 and `calcsize('<l')` is 4.
      * `n`, `N` and `P` are NATIVE ONLY: CPython raises `struct.error` for
        `'<P'` and for `'<2n'`, so the parser answers 0 there rather than a
        size, and 0 is this module's status for a format it will not answer.
      * `@` PADS. `calcsize('@xq')` is 16, not 9: the `x` takes byte 0 and the
        `q` is aligned up to byte 8. Alignment is to the item's own size and is
        1 for `x`, `s`, `p`, `c` and `?`, which is why `calcsize('@hx')` is 3.

    `s` and `p` are `count` bytes both here and in CPython 3.14 — measured, not
    quoted, and it is the kind of thing worth measuring because the documented
    reading of `p` is "length count-1" and this build answers `count`.
    """
    n = strlen(fmt)
    i = 0
    # NO PREFIX IS `@`. That is the one default in this function which is not
    # obvious, and CPython's own suite pins it twice over: `calcsize('l')` is 8
    # and `calcsize('<l')` is 4, and `calcsize('si')` is 8 against
    # `calcsize('si')` with a `<` prefix at 5 — the second one because native
    # mode PADS, so a format with no prefix is not only native-sized but
    # native-ALIGNED.
    native = 1
    align = 1
    # `<>!=@`, and the `=` is in the set for the reason the whole set exists:
    # it was written `<>@!` without it, so `calcsize('=i')` was 0 where CPython
    # says 4 — a standard-size format silently refused because the prefix that
    # MEANS "use standard sizes" was the one prefix the test did not ask about.
    # The grammar walk in `test_struct_formal.py` is what found it, by walking
    # the cross product rather than a list of formats somebody remembered.
    if n > 0 and str_at(fmt, 0, "<>!=@") == 1:
        if str_at(fmt, 0, "@") == 0:
            native = 0
            align = 0
        i = 1
    total = 0
    while i < n:
        # The item is [<count>] <code>, and this loop is both halves: a value
        # is ONE WORD on this path, so a helper that answered both "how many
        # bytes" and "how many characters of `fmt` did you read" would have to
        # pack two answers into one word. It is written out here instead, which
        # is the same reason `normpath` is not a table of sub-functions.
        count = 0
        seen = 0
        while i < n:
            d = _fmt_digit(fmt, i)
            if d < 0:
                break
            count = count * 10 + d
            seen = seen + 1
            i = i + 1
        if seen == 0:
            count = 1
        if i >= n:
            return 0                     # digits with no code after them
        code = _fmt_code_size(fmt, i, native)
        if code < 0:
            return 0                     # a format this file will not size
        a = 1
        if align == 1:
            a = _fmt_code_align(fmt, i)
        if a > 1:
            pad = a - (total % a)
            if pad == a:
                pad = 0
            total = total + pad
        total = total + count * code
        i = i + 1
    return total


# ── the format, parsed ───────────────────────────────────────────────────────
#
# The three helpers below answer ONE scalar each, which is this file's standing
# convention (the header's "one word per question") and is why the item loop
# above is written out rather than factored into a function.
#
# No SUBSCRIPT on `fmt` anywhere: `fmt: String` is annotated and a subscript on
# such a parameter reads the blob's count word rather than a byte (the file
# docstring's limit 1). Every byte test below is a `str_at` membership or a
# `memcmp` at a POINTER, which is the spelling that works.


def _fmt_digit(s: String, i: Int) -> int:
    """The value of the digit at `i`, or -1."""
    if str_eq_n(s + i, "0", 1) == 1:
        return 0
    if str_eq_n(s + i, "1", 1) == 1:
        return 1
    if str_eq_n(s + i, "2", 1) == 1:
        return 2
    if str_eq_n(s + i, "3", 1) == 1:
        return 3
    if str_eq_n(s + i, "4", 1) == 1:
        return 4
    if str_eq_n(s + i, "5", 1) == 1:
        return 5
    if str_eq_n(s + i, "6", 1) == 1:
        return 6
    if str_eq_n(s + i, "7", 1) == 1:
        return 7
    if str_eq_n(s + i, "8", 1) == 1:
        return 8
    if str_eq_n(s + i, "9", 1) == 1:
        return 9
    return 0 - 1


def _fmt_code_size(fmt: String, i: Int, native: Int) -> int:
    """Bytes ONE OCCURRENCE of the code at `i` takes, or -1. See `calcsize`."""
    if str_at(fmt, i, "xcsbp?") == 1:
        if str_at(fmt, i, "sp") == 1:
            return 1                 # `s`/`p` are `count` bytes, padding 1
        return 1
    if str_at(fmt, i, "bBhH") == 1:
        if str_at(fmt, i, "hH") == 1:
            return 2
        return 1
    if str_at(fmt, i, "iIlL") == 1:
        if str_at(fmt, i, "lL") == 1:
            if native == 1:
                return 8
            return 4
        return 4
    if str_at(fmt, i, "qQnNP") == 1:
        if str_at(fmt, i, "nNP") == 1:
            if native == 0:
                return 0 - 1         # CPython raises `struct.error` here
            return 8
        return 8
    return 0 - 1


def _fmt_code_align(fmt: String, i: Int) -> int:
    """The alignment `@` gives the code at `i`, which is its size or 1.

    Separate from `_fmt_code_size` because the answer depends on the BYTE ORDER
    (`l` is 4 wide standard and 8 native) and the caller has already decided
    that; passing it in again would be a second answer to one question.
    """
    if str_at(fmt, i, "xcsbp?") == 1:
        return 1
    return _fmt_code_size(fmt, i, 1)


# ── bytes ────────────────────────────────────────────────────────────────────

def _byte(v, sh: Int) -> int:
    """Byte `sh // 8` of `v`, little-endian.

    `& 255` rather than a narrow type: there is no narrow type on this path
    and the mask IS the truncation CPython performs. For a negative `v` the
    shift is arithmetic and the mask keeps the low byte, which is the two's
    complement byte CPython packs — measured, the four bytes of `-5` sum to
    1016 both here and under `struct.pack('<i', -5)`.
    """
    return (v >> sh) & 255


def _get(buf, at: Int, width: Int) -> int:
    """The unsigned little-endian integer of `width` bytes at `at`.

    Unsigned because that is what every call site in the corpus wants: each
    reads back a word it packed as `<I`/`<Q` and masks it itself
    (`formal/arm64.py`'s `resolve()` does `insn & 0xff000000`). A signed read
    would need a per-width sign extension that no caller asks for, so it is
    not provided rather than provided and untested.
    """
    v = 0
    k = 0
    sh = 0
    while k < width:
        v = v | (buf[at + k] << sh)
        sh = sh + 8
        k = k + 1
    return v


# ── the public surface ───────────────────────────────────────────────────────

def pack_into(fmt: String, buf, off: Int, v0=0, v1=0, v2=0) -> int:
    """Write `fmt`'s values into `buf` at byte `off`. Returns 0.

    The lifetime-independent form and the one the twelve `pack_into` call
    sites want: each patches a word into a section that already exists, so
    there is nothing to return and nothing that can outlive the call. `buf` is
    the CALLER's list, which is what makes this sound where a list built here
    would not be (limit 4).

    THREE value slots, and that is arithmetic rather than taste: the whole
    signature is six arguments wide (`fmt`, `buf`, `off`, three values)
    because SIX is the smaller of the two ABIs' integer argument registers
    (limit 2) and a module this backend compiles has to fit both. Three is
    not a restriction in practice: every `pack_into` call site in the corpus
    passes at most three values, measured — `formal/macho_linker.py:111` is the
    widest (`<III`), and the `patch(off, fmt, *vals)` sites pass one or two.
    A format needing more is left unwritten rather than written wrong, because
    the extra value would be garbage this function cannot detect.

    THE VALUE SLOTS ARE DEFAULTED, and that is what makes them safe to leave
    off. A slot beyond `_nvalues(fmt)` is never read, so a caller that packs a
    two-value format has nothing to say about `v2` — but across a dylib
    boundary a caller cannot leave a parameter out at all: the callee gives it
    a register home whether or not the caller mentions it, and a register
    nothing wrote is whatever the caller last put there
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`, and the
    arity half of the same change). `pack_into(fmt, buf, 4, a, b)` is the shape
    `test_struct_formal.py`'s offset case and the corpus's `patch` sites use,
    and it is a `TypeError` against three REQUIRED value parameters. Zero is the
    right fill for a slot that is not read, and declaring it is what turns the
    call from an unbindable one into the CPython answer.
    """
    n = _nvalues(fmt)
    if n == 0 or n > 3:
        return 0
    p = off
    k = 0
    while k < n:
        w = _width_at(fmt, k)
        if k == 0:
            v = v0
        elif k == 1:
            v = v1
        else:
            v = v2
        b = 0
        while b < w:
            buf[p] = _byte(v, b * 8)
            p = p + 1
            b = b + 1
        k = k + 1
    return 0


def unpack_from(fmt: String, buf, off: Int):
    """Values of `fmt`, read from `buf` at byte `off`, as a list of ints.

    One element per VALUE (not per byte), so the result's length is
    `_nvalues(fmt)`: `<QQ` gives two numbers, `<I` gives one. The corpus reads
    element 0 and nothing else — `formal/x86_64_decode.py` is
    `struct.unpack_from("<i", code, at)[0]` — but the whole list is built so
    the shape is not a special case for the one caller.

    The result is a literal of the right length chosen by the same ladder
    `pack` uses, for the same two reasons (limit 3's `len()`, and limit 4's
    frame lifetime — a list built here is in this frame, which is correct for
    the corpus's immediate `[0]` and is recorded in the docstring rather than
    papered over).

    `off` is a parameter and a subscript on `buf` is fine: `buf` is a LIST and
    the list path is the correct one for a list. Limits 1-3 are about strings,
    variadics and returned-list lengths, and none of them applies here.
    """
    n = _nvalues(fmt)
    if n == 0:
        return []
    if n == 1:
        out = [0]
    elif n == 2:
        out = [0, 0]
    elif n == 3:
        out = [0, 0, 0]
    elif n == 6:
        out = [0, 0, 0, 0, 0, 0]
    elif n == 7:
        out = [0, 0, 0, 0, 0, 0, 0]
    else:
        out = [0, 0, 0, 0, 0, 0, 0, 0]
    p = off
    k = 0
    while k < n:
        out[k] = _get(buf, p, _width_at(fmt, k))
        p = p + _width_at(fmt, k)
        k = k + 1
    return out


def pack(fmt: String, v0=0, v1=0, v2=0, v3=0, v4=0):
    """Bytes for `fmt` and up to five values, as a list of ints.

    The buffer is a literal of the format's own size, chosen by a ladder of
    `if`s on `calcsize`. That is not decoration: a list literal is the only
    container this path can build, its length is fixed at compile time, and
    `len()` of a returned list is refused (limit 3) — so the size has to be
    spelled as a literal and the right one has to be picked before the fill
    loop runs. The sizes are exactly the ones the corpus need, and every one
    of them is measured to fill correctly.

    FIVE value slots: the signature is six arguments wide because six is the
    smaller of the two ABIs' integer argument registers (limit 2). A format
    naming more than five values cannot be packed here, and the corpus formats
    that do — `<HHHHHH` (6), `<HHIQQQI` (7), `<IIQQQQQQ` (8), `<4sBBBBBBB5x`
    (8) — return an empty list rather than a wrong answer WHEN SUPPLIED FIVE
    VALUES, which is what every call site in the corpus does.

    Two different refusals, and the difference is the interesting part. Handed
    MORE values than the signature has slots — `pack("<IIQQQQQQ", 1, 2, 3, 4,
    5, 6, 7, 8)`, nine arguments to six parameters — the CALL is refused by
    the arity check against this signature, before the body is ever entered:

        call pack(): too many positional arguments (9 for 6 parameter(s);
        the parameters are ['fmt', 'v0', 'v1', 'v2', 'v3', 'v4']

    So the ceiling is enforced twice over and at two different layers: the
    signature stops the call, and the empty list is what this body answers when
    the format asks for more values than the caller supplied. The earlier
    version of this docstring listed `<IIQQQQQQ` among the formats that "return
    an empty list" without saying that supplying all eight of its values never
    reaches this function at all — which is true, and is the reason
    `test_struct_formal.py`'s `test_the_eight_value_pack_is_refused_by_arity`
    exists as its own case with its own expectation.

    `pack_into` has no such limit for the corpus's formats: every `pack_into`
    call site needs at most three values, and it reads its buffer from the
    CALLER's frame, so the limit that bites is the value count and not where
    the bytes come from.
    """
    total = calcsize(fmt)
    if total == 0:
        return []
    if total == 1:
        out = [0]
    elif total == 2:
        out = [0, 0]
    elif total == 3:
        out = [0, 0, 0]
    elif total == 4:
        out = [0, 0, 0, 0]
    elif total == 6:
        out = [0, 0, 0, 0, 0, 0]
    elif total == 8:
        out = [0, 0, 0, 0, 0, 0, 0, 0]
    elif total == 12:
        out = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    elif total == 16:
        out = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    elif total == 24:
        out = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    elif total == 36:
        out = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    else:
        return []
    if _nvalues(fmt) > 5:
        return []
    p = 0
    k = 0
    while k < _nvalues(fmt):
        w = _width_at(fmt, k)
        if k == 0:
            v = v0
        elif k == 1:
            v = v1
        elif k == 2:
            v = v2
        elif k == 3:
            v = v3
        else:
            v = v4
        b = 0
        while b < w:
            out[p] = _byte(v, b * 8)
            p = p + 1
            b = b + 1
        k = k + 1
    return out
