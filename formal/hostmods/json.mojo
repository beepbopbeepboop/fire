"""`json` — RFC 8259 JSON, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import json` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` in `formal/imports.py` for
why these did NOT go at the repository root, where the first three of them
captured `import os` in the compiler's own sources.

WHAT IS HERE, AND WHY IT IS THE RIGHT SUBSET
--------------------------------------------
CPython's `json` is a MARSHALLER: `json.loads(text)` builds a Python object
graph out of the text, and `json.dump(obj, fp)` walks one. Neither direction
is expressible here, and the reason is the one that shapes every module in
this directory: **a value cannot cross a dylib boundary unless it is one
64-bit word** (`bugs/FORMAL_module_state_no_storage.md`), while a dict is a
blob carved out of the frame that built it. So `loads`, `load`, `dump` and
`dumps` of a container are ABSENT rather than approximated — see "WHAT IS NOT
HERE" below, where each is named.

What IS here is the other half of the module, and it is not a consolation
prize: **the scanner**. RFC 8259 is a grammar over fixed characters, and every
question about a JSON document that has a scalar answer is answerable here —
is this text well formed, what kind is the value, what is the integer at the
top level, what is the string under this key, and what is the JSON spelling
of this string. Those are the questions a program that cannot hold the object
graph still has to ask, and they are the questions the tree's own consumers
have: `tools/ab_compare.py` reads a `.meta.json` whose members are integers,
and `checked_run.py`, `py314_cache.py`, `test_memslot.py` and
`test_formal_imports.py` each read one integer or one string out of a
sidecar file.

So the shape is the one `sys` and `os` already use: **a CPython name where
its answer is a scalar, and a name marked at its definition where CPython's
spelling cannot be carried over.** `dumps_str` is `json.dumps` of a `str`.
`loads_int` is `json.loads` of a document that is a number. `member_int` is
`payload["n"]` — the subscript, as a function, because a subscript is a
container read. And `valid`, `top_kind` and `member_kind` are named at their
definitions as names CPython's `json` does not have, for the same reason
`sys.write_stdout` is not one: CPython spells "this text is malformed" by
raising, and this path has no exceptions to raise
(`bugs/FORMAL_no_exceptions.md`), so the question has to become a return
value to be asked at all.

THE PRIMITIVE THIS FILE IS BUILT ON
-----------------------------------
Everything below reduces to three questions about the byte at `text[i]`: is
it equal to a specific byte, is it in a set of bytes, and what is its
numeric value. The first two are `memcmp` and `strspn`. The third is
`byte_at`. It was recorded as UNAVAILABLE on this path by a 2026-09-29 attempt
at this module, whose three implementations of the byte-value read (a linear
scan over the 256 candidates, a bisection over `strspn`, and a table lookup)
all returned plausible integers and all were wrong — the scan measured exactly
64 less than the truth for every input, which reads like a counter losing a
bit and sent that attempt looking for a table bug instead of a spelling.

**It was a spelling, and the spelling is two lines.** The scan took
`memcmp(s + i, TABLE + k, 1)`, which asks the value question and not the
equality one; what does not work here is asking an EXPRESSION for a pointee it
does not declare, so `(s + i).value()` is refused. Assigning first does:

    var q: Pointer[UInt8] = s + i
    return q.value()

which is `formal/hostmods/hashlib.mojo`'s `byte_at`, and it is correct — the
whole of `test_formal_json.py`'s `primitive` group is that assertion, over
every byte value 1..255, in the image and across a dylib boundary, against
CPython's own `ord`. The doc's own step 1 ("settle whether a module-level
constant survives being passed as an argument") was the right question to ask
first and the answer turned out not to be where the value was lost. The
bisection it recommended instead of the loop was not needed either: with the
load fixed there is no loop.

TWO CONSEQUENCES OF THIS PATH THAT THE CODE BELOW IS WRITTEN AROUND
----------------------------------------------------------------
  * **A CHARACTER CLASS IS A COMPARISON AGAINST A NUMBER.** Every
    character-class test below is `b == 34` rather than a `strspn` against a set
    literal, because what a JSON scanner wants is the byte VALUE: the double
    quote is 34, the backslash is 92, and the control bytes are 9, 10, 13 and
    32. Naming the number once is the same idea as the `os` module's
    `str_at(path, j, "/")` with one element in it, and it keeps one spelling per
    byte instead of a set literal beside a numeric test.
    (This file used to give a different and now false reason for the same code
    — "a string escape is NOT interpreted in a literal, so there is NO way to
    write a double quote, a backslash or a control byte into a string
    constant". `9023031b` gave these backends the decoder every engine shares:
    a literal IS decoded, inside a module as well as inside a program, on both
    architectures, measured through a module dylib and pinned by
    `test_formal_sys.py::test_a_literal_inside_a_module_is_decoded_too`.)
  * **THERE ARE NO EXCEPTIONS AND NO MODULE STATE.** Every failure is a
    return value — `-1` for "no such index", `0` for "not valid", and for
    `loads_*` a documented sentinel. A module-level name is a value inlined
    at its use site and crosses no boundary, so this module has nothing to
    remember between calls and nothing to free but what it `malloc`s.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `load`, `loads`, `dump`, `dumps` — the container-valued half. `loads`
    RETURNS an object graph and `dump` TAKES one; both are containers, and a
    container cannot cross a dylib boundary. They are absent, and a call to
    one is refused with the export-map message naming the module and listing
    what it does export, so the omission can never be mistaken for a
    function that answers something plausible.
  * `JSONDecodeError`, `JSONEncoder`, `JSONDecoder`, `detect_encoding` — a
    type, two factories and one spelling rule. A type is not a value
    (`bugs/FORMAL_module_state_no_storage.md`).
  * `NaN`, `Infinity`, `-Infinity` as INPUT — CPython's `json.loads` accepts
    all three, because its default `parse_constant` does, even though RFC
    8259 does not mention them. This module follows CPython rather than the
    RFC, because it is a mirror of CPython's `json` and not of a
    specification: a program written against CPython that reads a file
    containing `NaN` works there and would be refused here, which is a
    divergence nobody would be looking for. They are Floats as values, so
    `loads_int` returns 0 for them and `top_kind` reports 4 — the caller gets
    the KIND, which is the fact it can act on, and no invented number.
  * `json.tool`, `json.decoder`, `json.encoder`, `json.scanner` — CPython's
    submodules, and a submodule is a module, so this would be four more
    dylibs.
  * A `str` CONTAINING A NUL, IN EITHER DIRECTION — a formal string is a
    bare NUL-terminated `char *`, so a NUL ends it. `dumps_str` cannot be
    HANDED one (CPython's `json.dumps("\\x00")` is `"\\u0000"`), and
    `loads_str` cannot RETURN one: `"\\u0000"` decodes to a string whose
    first byte is 0, and every byte after it is past the end of the string.
    Both are stated at the definitions and both are why
    `test_formal_json.py`'s corpora have no NUL in them. That is a property of
    the value model and not something this file can route around.
"""

HEX = "0123456789abcdef"

# `json`'s six two-character escapes, as the byte that follows the backslash.
# Needed as NUMBERS because of the literal rule above: `"\\b"` would put a
# backslash and a `b` in the C string, and the scanner wants byte 98.
ESC_B = 98
ESC_F = 102
ESC_N = 110
ESC_R = 114
ESC_T = 116
ESC_U = 117
ESC_Q = 34
ESC_SLASH = 47
ESC_BSLASH = 92

# The nesting depth `scan_value` accepts, and it is a MEASURED number rather
# than a chosen one.
#
# `scan_value` -> `scan_array` -> `scan_value` is two frames per level, and a
# formal image's stack is the machine stack and the frame the backend reserves,
# neither of which a program can size
# (`bugs/FORMAL_always_returns_recurses_past_the_stack_on_a_large_function.md`).
# Measured on a document of nothing but `[` repeated: with no bound at all, 28
# levels is answered and 29 is SIGSEGV. The bound is set BELOW that ceiling
# rather than at it, because the check runs inside the frame it is testing for
# and the last few frames are exactly the ones that fault — so a bound AT the
# measured ceiling still crashes, which is the failure this exists to prevent.
#
# A document nested deeper than this is reported INVALID, which is the
# difference between a module that says no and one that dies.
# `test_formal_json.py`'s `deep` group pins both halves: 24 is answered, 25 is
# INVALID, and 40 — four times the raw ceiling — is INVALID rather than a
# SIGSEGV, so the day the stack grows this says so instead of quietly costing
# the module a quarter of its grammar.
MAX_DEPTH = 24

# The kind codes, in the order `kind_at` returns them. Named at their use.
K_NULL = 0
K_FALSE = 1
K_TRUE = 2
K_INT = 3
K_FLOAT = 4
K_STRING = 5
K_ARRAY = 6
K_OBJECT = 7


# ── byte-level primitives ───────────────────────────────────────────────────
#
# The three questions, in the order the rest of the file asks them.

def byte_at(s, i) -> int:
    """The byte at `s + i`, as 0..255.

    `var q: Pointer[UInt8] = s + i` and then `q.value()`, NOT `(s + i).value()`:
    the load's width comes from the pointee, and an EXPRESSION declares no
    type, so the one-call spelling is refused. It is not a wrong answer, it is
    a refusal — and it is the whole of what a previous attempt at this module
    measured as a missing primitive. See the module docstring, and
    `test_formal_json.py`'s `primitive` group, which is the assertion that
    settles it over 351 byte values.
    """
    var q: Pointer[UInt8] = s + i
    return q.value()


def byte_or(s, i) -> int:
    """The byte at `s + i`, or 256 if `i` is at or past the terminating NUL.

    Every read of a DOCUMENT goes through here, and the reason is measured
    rather than stylistic. A grammar LOOKS AHEAD: `scan_number` reads one byte
    past the digits it has, `scan_value` reads the byte after a `-` to see
    whether it is `-Infinity`, `unescape` reads six bytes past a `\u` to see
    whether a second escape follows. A formal string is a bare NUL-terminated
    `char *` in a `malloc`'d block, so a read past the NUL reads whatever the
    allocator left there — and at the end of a page that is a SIGSEGV, not a
    wrong answer. Measured: with the unbounded read, a corpus containing a
    document that ends in a number killed the image, and no amount of
    reasoning about which byte would have been there would have found it.

    256 is the sentinel because it is not a byte any of the class tests can
    be: `is_ws`, `is_digit`, `is_hex` and every `== 34` in this file answer 0
    for it, so a lookahead past the end reads as "not a digit", "not a
    member" and "not the end of the document" — which is what a grammar wants
    at the end of its input.
    """
    if i >= strlen(s):
        return 256
    return byte_at(s, i)


def hexdig(b) -> int:
    """The value of the hex digit `b`, or -1 if it is not one."""
    if b >= 48 and b <= 57:
        return b - 48
    if b >= 97 and b <= 102:
        return b - 87
    if b >= 65 and b <= 70:
        return b - 55
    return 0 - 1


def is_ws(b) -> int:
    """1 for the four bytes RFC 8259 calls JSON whitespace."""
    if b == 32:
        return 1
    if b == 9:
        return 1
    if b == 10:
        return 1
    if b == 13:
        return 1
    return 0


def is_digit(b) -> int:
    """1 for 0..9."""
    if b >= 48 and b <= 57:
        return 1
    return 0


def is_hex(b) -> int:
    """1 for a hex digit, either case."""
    if hexdig(b) >= 0:
        return 1
    return 0


def lit_at(s, i, lit) -> int:
    """1 if `s` at `i` begins with the escape-free literal `lit`."""
    if memcmp(s + i, lit, strlen(lit)) == 0:
        return 1
    return 0


# ── writing bytes into a buffer ────────────────────────────────────────────
#
# There is no assignment through `.value()` on this path — the target must be
# a plain name — so every byte is written with a `memcpy` out of a one-byte
# scratch. That is `formal/hostmods/hashlib.mojo`'s `byte_store`, and it is
# why the hex writer below reads as three operations where Python would write
# one.

def put_byte(out, at, b) -> int:
    """`out[at] = b & 255`. Returns `at + 1`."""
    var one: Pointer[UInt8] = malloc(1)
    memset(one, b & 255, 1)
    memcpy(out + at, one, 1)
    return at + 1


def put_str(out, at, s) -> int:
    """Append `s`'s bytes. Returns the index after them."""
    memcpy(out + at, s, strlen(s))
    return at + strlen(s)


def put_hex4(out, at, v) -> int:
    """Append `v` as four lowercase hex digits, zero-padded. `v` is 0..65535.

    Zero-padded through the digit table rather than by a format string,
    because `snprintf("%04x")` is the C library's idea of a width and this
    file is checked against CPython byte for byte, and a width that differs
    is a difference in the answer.
    """
    var u = at
    u = put_byte(out, u, byte_at(HEX, (v >> 12) & 15))
    u = put_byte(out, u, byte_at(HEX, (v >> 8) & 15))
    u = put_byte(out, u, byte_at(HEX, (v >> 4) & 15))
    u = put_byte(out, u, byte_at(HEX, v & 15))
    return u


# ── the scanner ────────────────────────────────────────────────────────────
#
# A recursive-descent pass over RFC 8259's grammar, in the shape the value
# model allows: every function returns an INDEX, never a tuple, so "where did
# this value end" is the return value and "was it well formed" is -1.

def skip_ws(s, i) -> int:
    """The first index at or after `i` that is not JSON whitespace."""
    while is_ws(byte_or(s, i)) == 1:
        i = i + 1
    return i


def scan_hex4(s, i) -> int:
    """`i` is just past a `\\u`; the index after its four hex digits, or -1.

    RFC 8259 requires four and CPython's strict mode requires four, and the
    two agree — `json.loads('"\\\\u00"')` is a `JSONDecodeError` in both.
    """
    var k = 0
    while k < 4:
        if is_hex(byte_or(s, i + k)) == 0:
            return 0 - 1
        k = k + 1
    return i + 4


def scan_escape(s, i) -> int:
    """`i` is just past a backslash. The index after the escape, or -1.

    Every one of RFC 8259's seven, and nothing else: a backslash before any
    other byte is malformed in CPython too, so this refuses rather than
    passing the byte through.
    """
    var b = byte_or(s, i)
    if b == ESC_B or b == ESC_F or b == ESC_N or b == ESC_R or b == ESC_T:
        return i + 1
    if b == ESC_Q or b == ESC_SLASH or b == ESC_BSLASH:
        return i + 1
    if b == ESC_U:
        return scan_hex4(s, i + 1)
    return 0 - 1


def scan_string(s, i) -> int:
    """`i` is at a double quote. The index after the closing quote, or -1.

    Two rules, both from the grammar and both checked by CPython: a raw byte
    below 0x20 is malformed (this is `strict=True`, the default), and a
    `\\u` escape is four hex digits and NOT a surrogate-pair check. CPython
    accepts a lone surrogate — `json.loads('"\\\\ud800"')` is a one-character
    string — so pairing is not validated here either; the PAIRING happens in
    `unescape`, on the way out, not here.
    """
    var p = i + 1
    while p < strlen(s):
        var b = byte_or(s, p)
        if b == ESC_Q:
            return p + 1
        if b < 32:
            return 0 - 1
        if b == ESC_BSLASH:
            p = scan_escape(s, p + 1)
            if p < 0:
                return 0 - 1
        else:
            p = p + 1
    return 0 - 1


def scan_number(s, i) -> int:
    """`i` is at a number. The index after it, or -1.

    The grammar, not `strtod`: an optional `-`, an `int` part that is a single
    `0` or a non-zero digit run, then an OPTIONAL fraction and an OPTIONAL
    exponent, each of which requires its digits. CPython's scanner is the same
    shape, so `01`, `1.`, `.5`, `+1` and `1e` are all malformed here exactly
    as they are there.
    """
    var p = i
    if byte_or(s, p) == 45:
        p = p + 1
    if is_digit(byte_or(s, p)) == 0:
        return 0 - 1
    if byte_or(s, p) == 48:
        p = p + 1
    else:
        while is_digit(byte_or(s, p)) == 1:
            p = p + 1
    return scan_number_tail(s, p)


def scan_number_tail(s, p) -> int:
    """The optional fraction and exponent, from `p`. The end index, or -1."""
    var q = p
    if byte_or(s, q) == 46:
        q = q + 1
        if is_digit(byte_or(s, q)) == 0:
            return 0 - 1
        while is_digit(byte_or(s, q)) == 1:
            q = q + 1
    if byte_or(s, q) == 101 or byte_or(s, q) == 69:
        q = q + 1
        if byte_or(s, q) == 43 or byte_or(s, q) == 45:
            q = q + 1
        if is_digit(byte_or(s, q)) == 0:
            return 0 - 1
        while is_digit(byte_or(s, q)) == 1:
            q = q + 1
    return q


def is_number_start(b) -> int:
    """1 for a byte that can begin a number, 0 otherwise.

    Two bytes, not one: `-` is a number's own first byte and is not a value
    on its own, and the `0..9` range is the other.
    """
    if b == 45:
        return 1
    if is_digit(b) == 1:
        return 1
    return 0


def scan_value(s, i, depth) -> int:
    """`i` is at a value. The index after it, or -1.

    The one recursive function in the file, and `depth` is in the signature
    rather than counted locally because a formal value is one word: a depth
    counter a function increments for itself IS one word too, but a bound this
    deep is easier to test from outside than to reason about from inside.
    See `MAX_DEPTH`.
    """
    if depth > MAX_DEPTH:
        # The bound is `MAX_DEPTH` and the reason is at its definition: 29
        # levels of `[` is a SIGSEGV on this target with no bound at all, so
        # the check has to be here rather than discovered by a caller.
        return 0 - 1
    var p = skip_ws(s, i)
    var b = byte_or(s, p)
    if b == 123:
        return scan_object(s, p, depth)
    if b == 91:
        return scan_array(s, p, depth)
    if b == ESC_Q:
        return scan_string(s, p)
    if b == 110:
        return scan_keyword(s, p, "null", 4)
    if b == 116:
        return scan_keyword(s, p, "true", 4)
    if b == 102:
        return scan_keyword(s, p, "false", 5)
    if b == 78:
        return scan_keyword(s, p, "NaN", 3)
    if b == 73:
        return scan_keyword(s, p, "Infinity", 8)
    if b == 45 and byte_or(s, p + 1) == 73:
        return scan_keyword(s, p + 1, "Infinity", 8)
    if is_number_start(b) == 1:
        return scan_number(s, p)
    return 0 - 1


def scan_keyword(s, i, lit, n) -> int:
    """`i` is at a bareword. `i + n` if it is `lit`, else -1."""
    if lit_at(s, i, lit) == 1:
        return i + n
    return 0 - 1


def scan_array(s, i, depth) -> int:
    """`i` is at `[`. The index after the `]`, or -1."""
    var p = skip_ws(s, i + 1)
    if byte_or(s, p) == 93:
        return p + 1
    while p < strlen(s):
        p = scan_value(s, p, depth + 1)
        if p < 0:
            return 0 - 1
        p = skip_ws(s, p)
        if byte_or(s, p) == 93:
            return p + 1
        if byte_or(s, p) != 44:
            return 0 - 1
        p = skip_ws(s, p + 1)
    return 0 - 1


def scan_object(s, i, depth) -> int:
    """`i` is at `{`. The index after the `}`, or -1."""
    var p = skip_ws(s, i + 1)
    if byte_or(s, p) == 125:
        return p + 1
    while p < strlen(s):
        if byte_or(s, p) != ESC_Q:
            return 0 - 1
        p = scan_string(s, p)
        if p < 0:
            return 0 - 1
        p = skip_ws(s, p)
        if byte_or(s, p) != 58:
            return 0 - 1
        p = skip_ws(s, p + 1)
        p = scan_value(s, p, depth + 1)
        if p < 0:
            return 0 - 1
        p = skip_ws(s, p)
        if byte_or(s, p) == 125:
            return p + 1
        if byte_or(s, p) != 44:
            return 0 - 1
        p = skip_ws(s, p + 1)
    return 0 - 1


def scan_text(s) -> int:
    """1 if `s` is one whole JSON text, 0 if not.

    "One whole" is RFC 8259's `JSON-text = ws value ws`, so trailing
    whitespace is allowed and a second value is not — which is CPython's rule
    too: `json.loads("1 2")` raises.
    """
    var e = scan_value(s, 0, 0)
    if e < 0:
        return 0
    if skip_ws(s, e) != strlen(s):
        return 0
    return 1


# ── the questions a program can ask ────────────────────────────────────────

def _kind_shape(s, i) -> int:
    """The kind of whatever is at `i`, by its first byte alone. See the K_
    codes. -1 if the byte cannot begin any value.

    The private half of `kind_at`, and it is private because the two have
    different contracts and only one of them is an answer a caller should act
    on: this one says what the text LOOKS like, so `"tab<TAB>here"` is a
    string here — its first byte is a quote — and `kind_at` says -1 for it,
    because it is not one.
    """
    var p = skip_ws(s, i)
    var b = byte_or(s, p)
    if b == 123:
        return K_OBJECT
    if b == 91:
        return K_ARRAY
    if b == ESC_Q:
        return K_STRING
    if b == 110:
        if lit_at(s, p, "null") == 1:
            return K_NULL
        return 0 - 1
    if b == 116:
        if lit_at(s, p, "true") == 1:
            return K_TRUE
        return 0 - 1
    if b == 102:
        if lit_at(s, p, "false") == 1:
            return K_FALSE
        return 0 - 1
    if b == 78:
        if lit_at(s, p, "NaN") == 1:
            return K_FLOAT
        return 0 - 1
    if b == 73:
        if lit_at(s, p, "Infinity") == 1:
            return K_FLOAT
        return 0 - 1
    if b == 45 and byte_or(s, p + 1) == 73:
        if lit_at(s, p + 1, "Infinity") == 1:
            return K_FLOAT
        return 0 - 1
    if is_number_start(b) == 1:
        return number_kind(s, p)
    return 0 - 1


def kind_at(s, i) -> int:
    """The kind of the value at `i`, or -1. See the K_ codes.

    A NAME CPYTHON'S `json` DOES NOT HAVE, marked as such at the top of this
    file. It has to exist: on this target a caller cannot tell a number from a
    string by looking at the value, because both are one word, so the question
    "which of these is it" needs an answer that is not the value.

    It VALIDATES, which is the difference from `_kind_shape` and the reason
    this is the one a caller should use: -1 means "this text is not that kind
    of JSON", and a program can act on that, where "it starts with a quote"
    is not something to act on. The oracle in `test_formal_json.py` is
    CPython's own `type(json.loads(text))`, which is validating for the same
    reason.
    """
    if scan_value(s, i, 0) < 0:
        return 0 - 1
    return _kind_shape(s, i)


def number_kind(s, p) -> int:
    """K_INT or K_FLOAT for the number at `p`, by whether it has a fraction
    or an exponent. -1 if it is not a number at all."""
    var e = scan_number(s, p)
    if e < 0:
        return 0 - 1
    var k = p
    while k < e:
        var b = byte_or(s, k)
        if b == 46 or b == 101 or b == 69:
            return K_FLOAT
        k = k + 1
    return K_INT


def valid(s) -> int:
    """1 if `json.loads(s)` would succeed, 0 if it would raise.

    A NAME CPYTHON'S `json` DOES NOT HAVE — CPython spells this by raising
    `JSONDecodeError`, and this path has no exceptions, so the question has to
    be a return value to be asked at all. The docstring for each name in this
    file says the same; this is the first one.
    """
    return scan_text(s)


def top_kind(s) -> int:
    """The kind of the whole document, or -1. See `kind_at`.

    The whole document, so trailing junk counts: `top_kind("1 2")` is -1
    because CPython raises on it, and a kind for a document the reader cannot
    read is a kind nobody asked for.
    """
    if scan_text(s) == 0:
        return 0 - 1
    return _kind_shape(s, 0)


def member_value(s, key) -> int:
    """The index of the value of top-level member `key`, or -1.

    The subscript as a function, because a subscript is a container read and
    this path has no containers. `payload["n"]` is `member_value(payload, "n")`
    and then one of the `member_*` functions below; the split is because an
    index is one word and a value read out of it is a different question with
    a different failure.
    """
    if top_kind(s) != K_OBJECT:
        return 0 - 1
    # `+ 1` and not `1`: the object's brace is after the LEADING whitespace,
    # and a document with any (`  {"n": 5}  `) would otherwise be read as
    # though its second byte were inside the object.
    var p = skip_ws(s, 0) + 1
    if byte_or(s, p) == 125:
        return 0 - 1
    while p < strlen(s):
        p = skip_ws(s, p)
        var e = scan_string(s, p)
        if e < 0:
            return 0 - 1
        if string_eq(s, p, e, key) == 1:
            var c = skip_ws(s, e)
            if byte_or(s, c) != 58:
                return 0 - 1
            return skip_ws(s, c + 1)
        p = skip_ws(s, e)
        if byte_or(s, p) != 58:
            return 0 - 1
        p = scan_value(s, p + 1, 0)
        if p < 0:
            return 0 - 1
        p = skip_ws(s, p)
        if byte_or(s, p) == 125:
            return 0 - 1
        if byte_or(s, p) != 44:
            return 0 - 1
        p = p + 1
    return 0 - 1


def escaped_byte(s, p) -> int:
    """The byte the escape at `s[p]` — a backslash — stands for, or -1.

    -1 is `\u`, the one escape with no one-byte answer; the two callers both
    want to know that, and one of them wants the four hex digits as well.
    The short escapes are spelled as their NUMBERS because a string literal
    here is copied byte for byte, so `"\\b"` is a backslash and a `b`. See the
    module docstring; `test_formal_json.py`'s `escapes` group is what says
    this table agrees with CPython.
    """
    var c = byte_or(s, p + 1)
    if c == 98:
        return 8
    if c == 102:
        return 12
    if c == 110:
        return 10
    if c == 114:
        return 13
    if c == 116:
        return 9
    if c == 34:
        return 34
    if c == 47:
        return 47
    if c == 92:
        return 92
    return 0 - 1


def string_eq(s, i, e, key) -> int:
    """1 if the string literal `s[i:e]` DECODES to `key`, else 0.

    Only the escapes RFC 8259 gives a one-byte answer for, which is every one
    of them except `\\u`. A key with a `\\u` in it does not match here; the
    keys in this tree do not have one, and a partial answer dressed as a
    complete one is the thing this file exists to avoid. It is stated at the
    definition rather than left to be found.
    """
    var p = i + 1
    var k = 0
    var kn = strlen(key)
    while p < e - 1:
        var b = byte_or(s, p)
        if b == ESC_BSLASH:
            b = escaped_byte(s, p)
            if b < 0:
                return 0
        if b != byte_or(key, k):
            return 0
        k = k + 1
        if k > kn:
            return 0
        p = p + 1
    if k != kn:
        return 0
    return 1


def member_kind(s, key) -> int:
    """The kind of top-level member `key`, or -1. See `kind_at`.

    -1 for an absent key, for a document that is not an object, and for a
    member whose value is not well formed — the three cases a caller cannot
    tell apart afterwards and would otherwise read as a kind.
    """
    var p = member_value(s, key)
    if p < 0:
        return 0 - 1
    return kind_at(s, p)


def loads_int(s) -> int:
    """`json.loads(s)` when the document is a number, as an integer.

    Exact for every document with no EXPONENT: an integer is exact, and
    `int(2.9)` is 2, which is the digit string up to the point — so truncation
    toward zero is the right answer for a fraction and not an approximation
    of one.

    0 for a document that carries an exponent, and that is a real limit rather
    than a shortcut: `json.loads("1e3")` is the float 1000.0, and a float is
    not a value on this path (`formal/hostmods/time.mojo` says the same about
    `time.time()`), so scaling a mantissa by 10**3 is not arithmetic this
    target has. A caller that needs it reads the digits itself; `top_kind`
    reports 4 so it knows that is what it has.

    0 also for an integer that does not fit a 64-bit word
    (`123456789012345678901234567890`), which is a value model limit and not
    a rounding: CPython's `int` is arbitrary-precision and this one is a word.

    0 also for a document that is not a number, and for `NaN` and `Infinity` —
    CPython's `int(nan)` raises `ValueError`, so there is no answer to return
    and 0 is the documented one. Use `top_kind` first when the difference
    matters, because 0 is also the answer for a document that IS the number
    zero.
    """
    var p = skip_ws(s, 0)
    if scan_value(s, p, 0) < 0:
        return 0
    var k = _kind_shape(s, p)
    if k != K_INT and k != K_FLOAT:
        return 0
    var neg = 0
    if byte_or(s, p) == 45:
        neg = 1
        p = p + 1
    var v = 0
    while is_digit(byte_or(s, p)) == 1:
        # 64-bit throughout, and CHECKED in BOTH directions. A formal value is
        # one 64-bit word, so an integer outside -2**63 .. 2**63-1 has no
        # representation; the accumulator is signed from the first digit so
        # that -2**63 — which is representable, and which a magnitude-first
        # accumulator would reject — is reached exactly. The two checks are a
        # pre-test on the accumulator and a look for the sign bit after the
        # multiply, because 2**63 and 2**63+1 both wrap to a NEGATIVE word and
        # would otherwise sail through a pre-test alone.
        #
        # Returning a WRAPPED value here would be the worst outcome in this
        # file — a plausible integer for a document that says something else —
        # so 0 is returned instead, and `test_formal_json.py` asserts 0 for
        # every integer past the boundary rather than a wrapped one.
        var d = byte_or(s, p) - 48
        if neg == 1:
            if v < 0 - 922337203685477580:
                return 0
            v = v * 10 - d
            if v > 0:
                return 0
        else:
            if v > 922337203685477580:
                return 0
            v = v * 10 + d
            if v < 0:
                return 0
        p = p + 1
    if byte_or(s, p) == 46:
        p = p + 1
        while is_digit(byte_or(s, p)) == 1:
            p = p + 1
    if byte_or(s, p) == 101 or byte_or(s, p) == 69:
        return 0
    return v


def loads_str(s) -> str:
    """`json.loads(s)` when the document is a string, unescaped.

    Every escape RFC 8259 defines, with `\\uXXXX` decoded to the character it
    names and a high/low surrogate PAIR decoded to the one code point the pair
    stands for — which is CPython's rule (`json.loads('"\\\\ud83d\\\\ude00"')`
    is one character there) and not a rule the RFC states, because RFC 8259
    does not mention surrogates. A lone surrogate is a code point of its own,
    here and in CPython. Returns the empty string for a document that is not a
    string, and the caller that cares uses `top_kind` first.
    """
    var p = skip_ws(s, 0)
    if _kind_shape(s, p) != K_STRING:
        return ""
    var e = scan_string(s, p)
    if e < 0:
        return ""
    var out: Pointer[UInt8] = malloc(4 * strlen(s) + 1)
    var u = unescape(s, p, e, out, 0)
    put_byte(out, u, 0)
    return out


def unescape(s, i, e, out, at) -> int:
    """Copy `s[i:e]`'s string to `out` from `at`, resolving escapes.

    The index after what was written. Byte-for-byte the same bytes for an
    unescaped one, so a document with no escape in it is a `memcpy`.

    The one piece of real work is the `\\u` arm, and it has three cases
    because CPython's decoder has three: a HIGH surrogate immediately followed
    by `\\u` and a LOW surrogate is one code point, and either surrogate on
    its own is a code point of its own. `json.loads('"\\\\ud83d\\\\ude00"')` is
    ONE character in CPython and
    `json.loads('"\\\\ud83d\\\\u0041"')` is TWO, and a decoder that always
    combines gets the second one wrong.
    """
    var u = at
    var p = i + 1
    while p < e - 1:
        var b = byte_or(s, p)
        if b != ESC_BSLASH:
            u = put_byte(out, u, b)
            p = p + 1
        elif escaped_byte(s, p) >= 0:
            u = put_byte(out, u, escaped_byte(s, p))
            p = p + 2
        else:
            var hi = hex4_value(s, p + 2)
            if hi >= 55296 and hi <= 56319 and p + 11 <= e - 2:
                if byte_or(s, p + 6) == ESC_BSLASH and byte_or(s, p + 7) == ESC_U:
                    var lo = hex4_value(s, p + 8)
                    if lo >= 56320 and lo <= 57343:
                        u = put_hex_cp(out, u, pair(hi, lo))
                        p = p + 12
                    else:
                        u = put_hex_cp(out, u, hi)
                        p = p + 6
                else:
                    u = put_hex_cp(out, u, hi)
                    p = p + 6
            else:
                u = put_hex_cp(out, u, hi)
                p = p + 6
    return u


def pair(hi, lo) -> int:
    """The code point a high surrogate and a low surrogate stand for.

    RFC 8259 does not mention surrogates at all and CPython's decoder accepts
    lone ones, so this is CPython's rule and not the RFC's: 0x10000 + ((hi -
    0xD800) << 10) + (lo - 0xDC00), with a `* 1024` for the shift because the
    arm64 immediate form of a left shift is wrong for every amount above 8
    (`bugs/FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md`).
    """
    return 65536 + ((hi - 55296) * 1024) + (lo - 56320)


def hex4_value(s, i) -> int:
    """The four hex digits at `s[i:]` as one number, 0..65535."""
    return hexdig(byte_or(s, i)) * 4096 + hexdig(byte_or(s, i + 1)) * 256 + hexdig(byte_or(s, i + 2)) * 16 + hexdig(byte_or(s, i + 3))


def put_hex_cp(out, u, cp) -> int:
    """Write `cp` as UTF-8, the encoding a formal string is in.

    A `char *` on this path is UTF-8 by construction — see
    `formal/hostmods/sys.mojo`'s `getfilesystemencoding` — so a decoded code
    point has to come back out as the bytes that spell it, and this is the one
    place that has to be right about all four lengths.
    """
    if cp < 128:
        return put_byte(out, u, cp)
    if cp < 2048:
        u = put_byte(out, u, 192 + (cp >> 6))
        return put_byte(out, u, 128 + (cp & 63))
    if cp < 65536:
        u = put_byte(out, u, 224 + (cp >> 12))
        u = put_byte(out, u, 128 + ((cp >> 6) & 63))
        return put_byte(out, u, 128 + (cp & 63))
    u = put_byte(out, u, 240 + (cp >> 18))
    u = put_byte(out, u, 128 + ((cp >> 12) & 63))
    u = put_byte(out, u, 128 + ((cp >> 6) & 63))
    return put_byte(out, u, 128 + (cp & 63))


def member_int(s, key) -> int:
    """`json.loads(s)[key]` when that member is a number. 0 if it is not."""
    var p = member_value(s, key)
    if p < 0:
        return 0
    return loads_int(s + p)


def member_str(s, key) -> str:
    """`json.loads(s)[key]` when that member is a string. "" if it is not."""
    var p = member_value(s, key)
    if p < 0:
        return ""
    return loads_str(s + p)


# ── writing a value out ────────────────────────────────────────────────────
#
# `dumps` of the three kinds whose answer is a word, so three names rather
# than one: a formal value is one 64-bit INTEGER word, so the module cannot
# see whether it was handed a `str` or an `int`, and a `dumps` that guessed
# would be a `dumps` that is wrong half the time.

def dumps_str(s) -> str:
    """`json.dumps(s)` for a `str`: a JSON string literal, byte for byte.

    CPython's default is `ensure_ascii=True`, so every non-ASCII code point
    becomes a `\\uXXXX` and a code point above the BMP becomes a surrogate
    PAIR — two escapes, high then low, which is the arithmetic this function
    exists to get right and which `test_formal_json.py` checks over every code
    point from 1 to 0x10FFFF that is not a surrogate.
    """
    var n = strlen(s)
    # Worst case per input byte: one input byte can start a 4-byte sequence
    # whose code point needs a surrogate pair, and there are far fewer than
    # n of those, so 6n + 2 is a bound and not an estimate.
    var out: Pointer[UInt8] = malloc(6 * n + 2)
    var u = put_byte(out, 0, ESC_Q)
    var i = 0
    while i < n:
        u = dumps_one(s, i, out, u)
        i = next_cp(s, i)
    u = put_byte(out, u, ESC_Q)
    put_byte(out, u, 0)
    return out


def lead_len(b) -> int:
    """The sequence length a UTF-8 lead byte declares, or 0 if it declares
    none. `0xC0` and `0xC1` are excluded because every sequence they could
    introduce is overlong, and CPython rejects all of them."""
    if b >= 240 and b <= 247:
        return 4
    if b >= 224 and b <= 239:
        return 3
    if b >= 194 and b <= 223:
        return 2
    if b >= 128:
        return 0
    return 1


def code_of_utf8(s, i, n) -> int:
    """The code point of the `n`-byte sequence at `s[i]`, `n` in 2..4.

    Assembled with multiplications rather than shifts because the arm64
    immediate form of a left shift is wrong for every amount above 8
    (`bugs/FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md`), and
    because `n` is not a constant here.
    """
    var b = byte_or(s, i)
    if n == 2:
        # `b - 192` and NOT `b - 194`: the two high bits of a two-byte lead are
        # always `110`, so the value contributes `b & 0x1F`, and `lead_len`
        # already refused 0xC0 and 0xC1 (which could only introduce an
        # overlong). `b - 194` is off by two for every one of them, and reads
        # as plausible: `Ã©` came out `\u0069` instead of `\u00e9`.
        return (b - 192) * 64 + (byte_or(s, i + 1) - 128)
    if n == 3:
        return ((b - 224) * 4096 + (byte_or(s, i + 1) - 128) * 64
                + (byte_or(s, i + 2) - 128))
    return ((b - 240) * 262144 + (byte_or(s, i + 1) - 128) * 4096
            + (byte_or(s, i + 2) - 128) * 64 + (byte_or(s, i + 3) - 128))


def utf8_bad_at(s, i) -> int:
    """How many bytes of an ILL-FORMED sequence start at `s[i]`, or 0 if the
    sequence there is well formed. Never 0 and never less than 1 when the byte
    is >= 0x80.

    The number is the length of the MAXIMAL VALID PREFIX, which is CPython's
    rule and is not the obvious one:

        b"\xe2\x82"          -> one U+FFFD, 2 bytes skipped
        b"\xe2\x41"          -> one U+FFFD, 1 byte skipped, then "A"
        b"\xf0\x9f\x41\x80"  -> one U+FFFD, 2 bytes skipped, then "A", then one
        b"\xf4\x90\x80\x80"  -> FOUR U+FFFD, one byte each
        b"\xed\xa0\x80"      -> three U+FFFD, one byte each

    The last two are the ones that are easy to get wrong in the other
    direction: a code point above U+10FFFF, and a SURROGATE, are each worth one
    U+FFFD and ONE byte — not one U+FFFD for the whole four. A surrogate is
    not encodable in UTF-8 and CPython's decoder refuses one, so `\xed\xa0\x80`
    is three replacement characters there and must be three here; without that
    check the sequence decodes to U+D800 and is written `\ud800`, which is the
    CESU-8 spelling of the same bytes and plausible enough to pass an eyeball.

    It is ONE function and two callers because the advance and the value have
    to agree: `next_cp` asks how far to step and `utf8_at` asks what to write,
    and two copies of this test would be two chances to disagree about a
    string CPython can decode.
    """
    var b = byte_or(s, i)
    if b < 128:
        return 0
    var n = lead_len(b)
    if n < 2:
        return 1
    var k = 1
    while k < n:
        if i + k >= strlen(s):
            return k
        var c = byte_or(s, i + k)
        if c < 128 or c > 191:
            return k
        k = k + 1
    var cp = code_of_utf8(s, i, n)
    if cp > 1114111:
        return 1
    if cp >= 55296 and cp <= 57343:
        return 1
    return 0


def next_cp(s, i) -> int:
    """The index just past the character at `s[i]`.

    One byte for an ASCII character, the declared length for a well-formed
    sequence, and the maximal valid prefix for an ill-formed one — which is
    what makes `dumps_str` agree with CPython's `errors="replace"` decoder
    byte for byte, and `test_formal_json.py`'s `dumps` group asserts that over
    truncated, overlong, out-of-range, surrogate and continuation-only
    sequences. It is a measured rule and not a guess; see `utf8_bad_at`.
    """
    var b = byte_or(s, i)
    if b < 128:
        return i + 1
    var bad = utf8_bad_at(s, i)
    if bad > 0:
        return i + bad
    return i + lead_len(b)


def dumps_one(s, i, out, u) -> int:
    """Write the character at `s[i]`, escaped. The index after what was
    written.

    The escape table is CPython's, byte for byte: `"` and `\\`, the five
    short escapes, and every other byte below 0x20 as `\\u00xx` with lowercase
    hex. Byte 0x7F is escaped as well — CPython escapes DEL, which is the kind
    of detail a table gets wrong.
    """
    var b = byte_or(s, i)
    if b == ESC_Q:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_Q)
    if b == ESC_BSLASH:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_BSLASH)
    if b == 8:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_B)
    if b == 12:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_F)
    if b == 10:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_N)
    if b == 13:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_R)
    if b == 9:
        u = put_byte(out, u, ESC_BSLASH)
        return put_byte(out, u, ESC_T)
    if b < 32 or b == 127:
        u = put_byte(out, u, ESC_BSLASH)
        u = put_byte(out, u, ESC_U)
        return put_hex4(out, u, b)
    if b < 128:
        return put_byte(out, u, b)
    return dumps_cp(out, u, utf8_at(s, i))


def utf8_at(s, i) -> int:
    """The code point of the character at `s[i]`, or 0xFFFD.

    0xFFFD for anything malformed, which is U+FFFD REPLACEMENT CHARACTER and
    is what CPython's own UTF-8 decoder produces with `errors="replace"` — the
    same decoder `next_cp` advances by, and `test_formal_json.py` checks the
    two against each other over a corpus of truncated, overlong, out-of-range
    and continuation-only sequences. CPython's `json.dumps` cannot be given a
    malformed byte at all, so this is not a divergence from it so much as the
    only answer available, and it is stated here rather than left to be
    discovered as a wrong code point.
    """
    var b = byte_or(s, i)
    if b < 128:
        return b
    if utf8_bad_at(s, i) > 0:
        return 0xFFFD
    return code_of_utf8(s, i, lead_len(b))


def dumps_cp(out, u, cp) -> int:
    """Write `cp` the way CPython's `ensure_ascii=True` encoder writes it."""
    if cp < 65536:
        u = put_byte(out, u, ESC_BSLASH)
        u = put_byte(out, u, ESC_U)
        return put_hex4(out, u, cp)
    var v = cp - 65536
    u = put_byte(out, u, ESC_BSLASH)
    u = put_byte(out, u, ESC_U)
    u = put_hex4(out, u, 55296 + (v >> 10))
    u = put_byte(out, u, ESC_BSLASH)
    u = put_byte(out, u, ESC_U)
    return put_hex4(out, u, 56320 + (v & 1023))


def dumps_int(n) -> str:
    """`json.dumps(n)` for an `int`: the shortest decimal spelling.

    `snprintf` rather than a hand-rolled digit loop, for the reason
    `formal/hostmods/os/_syscalls.mojo` gives for using `strlen`: a library
    routine that already is the answer is not a second implementation to keep
    in agreement with the first. -2^63 .. 2^63-1 is the whole range a formal
    value has.

    `%lld` and NOT `%d`, which is measured and not a matter of taste: a `%d`
    conversion is 32 bits wide on this path, so `snprintf("%d", 4294967296)`
    writes `-2147483648` (`bugs/FORMAL_string_value_model.md` §2, "the `-1` a
    `%d` prints for `~2**62` is the formatter, not the operator"). Every
    other `printf` in this tree that prints a number a caller could have made
    large is `%d` and is therefore only right below 2**31 — a 24-byte buffer
    is 20 digits plus a sign, which is the widest `-2^63` needs.
    """
    var b: Pointer[UInt8] = malloc(24)
    snprintf(b, 24, "%lld", n)
    return b


def dumps_bool(b) -> str:
    """`json.dumps(b)` for a `bool`: `true` or `false`.

    A second name rather than a parameter, for the same reason `sys` spells
    `version_info[0]` as `version_info_major()`: the module cannot see which
    kind of word it was handed.
    """
    if b == 0:
        return "false"
    return "true"


def dumps_null() -> str:
    """`json.dumps(None)`: `null`. A word in, no argument."""
    return "null"
