#!/usr/bin/env python3
"""Build `json` for the formal backend and RUN it, compared with CPython's.

    python3 test_formal_json.py [-v] [group ...]

Why an oracle rather than a table of answers. Every case here is computed
twice — once through `python3 fire.py build --formal --no-prove` and executed,
once through `json` in this process — and the two have to agree. Nothing in
this file states what `json.dumps("a\\tb")` is; it asks. A digest or a scan
result is a pure function of its input, and a table of those answers is a
table that is wrong the moment someone transposes a character, which is the
one mistake a byte-oriented module cannot be allowed to make.

Building and RUNNING, not building. Every case here exits with a status this
file checks, and the value under test is the value the image printed.

THE PRIMITIVE GROUP IS THE POINT OF THE FILE
---------------------------------------------
`formal/hostmods/json.mojo` is built on three questions about the byte at
`text[i]`: is it equal to a byte, is it in a set, what is its value. The
first two are `memcmp` and `strspn`; the third is a one-byte load through a
declared `Pointer[UInt8]`.

A previous attempt at `json` (2026-09-29) recorded that third one as
UNAVAILABLE, on the strength of three implementations that all returned
plausible integers and all were wrong — a linear scan over the 256
candidates, a bisection over `strspn`, and a table lookup. **The `primitive`
group is the assertion that would have caught all three in one line**, and it
runs first because everything else in the file rests on it: every byte value
0..255 out of a buffer, and every printable ASCII value out of a string
literal, each printed as `value` and each compared against the byte the
source's own literal holds. 351 values, two builds.

The cause was a spelling and not a missing capability, which is the part worth
keeping: `(s + i).value()` asks an EXPRESSION for a pointee it does not
declare and is refused, and `var q: Pointer[UInt8] = s + i` followed by
`q.value()` is the same read. The docstring of `byte_at` in the module says so
at the definition.

A NOTE ON THE CORPUS, because it is a real constraint and not a style choice
--------------------------------------------------------------------------
A corpus spelled in decoded source bytes would make every awkward byte a thing
this file has to be right about twice — once in the expected document and once
in the literal — and a NUL cannot be spelled at all, because a formal string is
a NUL-terminated `char *`. So every corpus below is written in a MASKED
alphabet and the program unmasks it at run time:

    ~~  ->  ~        ~t -> TAB    ~n -> LF     ~r -> CR
    ~q  ->  "        ~b -> backslash           ~xHH -> byte 0xHH
    ~a  ->  @         (the record terminator's own character, so that the
                      code-point sweep in `dumps` can include U+0040)

and `unmask` is the only thing in the generated programs that knows it. Two
things the mask buys, and both are permanent: the expected document and the
produced one differ ONLY in the byte under test, and no byte depends on how
the lexer reads a non-ASCII character in the file. Byte 0 is not in the
alphabet, and cannot be: a formal string is a NUL-terminated `char *`, so a
NUL ends it. That is a property of the value model, it is stated in the
module's own docstring, and it is why the `dumps` corpus has no NUL in it.

The record format is `<len>:<value>@@`, with the LENGTH in front
precisely because a value here can be any byte at all. `@@` and not a
newline, for the reason every hostmod test in this tree gives
(`test_formal_dylib.py` states it): a separator this file can read back
without asking whether the image decoded a literal.

Groups: `resolve`, `primitive`, `valid`, `kinds`, `loads`, `members`,
`escapes`, `dumps`, `deep`, `absent`. With no argument, all.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
JSON_MODULE = os.path.join(HOSTMODS, "json.mojo")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120

REC = "@@"
TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


# ── the mask ───────────────────────────────────────────────────────────────
#
# `mask` is the Python half; `UNMASK` below is the Mojo half and the two must
# agree, which `test_formal_sweep_truth`-style drift would otherwise hide.

def mask(b: bytes) -> str:
    """The corpus spelling of `b`, a `bytes` value.

    Everything outside printable ASCII becomes `~xHH`, INCLUDING bytes
    0x80..0xFF: a non-ASCII character in a source literal would depend on how
    the lexer reads the file, and a corpus whose spelling depends on that is
    one more thing to be right about for no gain.
    """
    out = []
    for c in b:
        if c == 0x7E:
            out.append("~~")
        elif c == 0x40:
            # `@` is the record terminator's own character, and the whole point
            # of the code-point sweep is to include every printable one. The
            # escape is `~a` and NOT `~@`: the separator is `@@`, so an escape
            # ENDING in `@` puts `@@` at a case boundary and the driver's
            # two-byte scan finds it there instead of at the boundary.
            out.append("~a")
        elif c == 0x09:
            out.append("~t")
        elif c == 0x0A:
            out.append("~n")
        elif c == 0x0D:
            out.append("~r")
        elif c == 0x22:
            out.append("~q")
        elif c == 0x5C:
            out.append("~b")
        elif 0x20 <= c <= 0x7E:
            out.append(chr(c))
        else:
            out.append("~x%02x" % c)
    return "".join(out)


def mj(s) -> str:
    """A Mojo string literal for the already-masked `s`.

    Only `"` and `\\` need attention and the mask has already turned every
    other awkward byte into escape-free ASCII, so this is belt and braces.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# The Mojo half of the mask. `byte_at` and `put_byte` are exported by
# `json.mojo` precisely so a program can build an input the module cannot
# otherwise be handed; see their docstrings.
UNMASK = '''
def unmask(t) -> str:
    var out: Pointer[UInt8] = malloc(4 * strlen(t) + 1)
    var u = 0
    var i = 0
    while i < strlen(t):
        var b = json.byte_at(t, i)
        if b != 126:
            u = json.put_byte(out, u, b)
            i = i + 1
        elif json.byte_at(t, i + 1) == 126:
            u = json.put_byte(out, u, 126)
            i = i + 2
        elif json.byte_at(t, i + 1) == 116:
            u = json.put_byte(out, u, 9)
            i = i + 2
        elif json.byte_at(t, i + 1) == 110:
            u = json.put_byte(out, u, 10)
            i = i + 2
        elif json.byte_at(t, i + 1) == 114:
            u = json.put_byte(out, u, 13)
            i = i + 2
        elif json.byte_at(t, i + 1) == 97:
            u = json.put_byte(out, u, 64)
            i = i + 2
        elif json.byte_at(t, i + 1) == 113:
            u = json.put_byte(out, u, 34)
            i = i + 2
        elif json.byte_at(t, i + 1) == 98:
            u = json.put_byte(out, u, 92)
            i = i + 2
        else:
            var h = 16 * json.hexdig(json.byte_at(t, i + 2)) + json.hexdig(json.byte_at(t, i + 3))
            u = json.put_byte(out, u, h)
            i = i + 4
    json.put_byte(out, u, 0)
    return out
'''

# Corpus plumbing: a module-level string constant, split on `@@`, and a
# length-checked string comparison. Kept in the PRELUDE so every group is the
# same program with a different `main`.
SPLIT = '''
def ndelim(s, i) -> int:
    """The index of the next `@@`, or -1.

    TWO `@` and not one. The mask escapes every literal `@` as `~@`, so a
    masked case cannot contain `@@` — which is what makes the two-byte
    separator the right one, and a one-byte `@` the wrong one: the code-point
    sweep in `dumps` covers U+0040, and with a one-byte separator a case
    holding it would be cut in half and the parser would report a length
    mismatch on a value that was never wrong.
    """
    var p = i
    while p + 1 < strlen(s):
        if json.byte_at(s, p) == 64 and json.byte_at(s, p + 1) == 64:
            return p
        p = p + 1
    return 0 - 1

def sub(s, i, j) -> str:
    var out: Pointer[UInt8] = malloc(j - i + 1)
    memcpy(out, s + i, j - i)
    memcpy(out + (j - i), "", 1)
    return out
'''


def build(src, name):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, name)
    with open(tmp, "w") as f:
        f.write(src)
    r = subprocess.run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                        "-o", out, tmp],
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"build failed: {(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")


def records(text):
    """`<len>:<value>` records, as `(position, len, value)` triples.

    `text` is what the image printed, read as latin-1 so every byte survives.
    The length is CHECKED rather than trusted: a value here can be any byte at
    all, and a parser that split on a separator alone would silently mis-align
    on the first value that contained one — and then report a wrong answer
    rather than an error.
    """
    got = []
    for rec in text.split(REC):
        if not rec:
            continue
        head, sep, val = rec.partition(":")
        if not sep:
            # The `idx=value` form, for a value that is a plain number and so
            # cannot contain the terminator or a colon. Still length-checked
            # below, against the value itself.
            _, _, val = rec.partition("=")
            got.append((len(got), len(val), val))
            continue
        # The index is the record's POSITION, not a field: a value here can
        # contain a colon (`{"a:b": 1}` decodes to one), so a record that
        # carried its own index would be ambiguous. Every group emits exactly
        # one record per case, in order, and `compare` says so.
        got.append((len(got), int(head), val))
    return got


def reader(got, n, per):
    """The `n`-th of `per` interleaved readers' records, re-indexed from 0.

    A program that reads one document several ways emits `per` records per
    case, so its record positions are 0, per, 2*per, ... and the slice keeps
    those. Re-indexing here rather than in `records` is what keeps `records`
    honest about what a record IS: its position in the output, nothing else.
    """
    return [(i, ln, v) for i, (_, ln, v) in enumerate(got[n::per])]


def compare(label, cases, got, want_fn):
    """`cases` is the corpus in order; `want_fn` gives CPython's answer.

    `got` is ONE READER'S records. A group that reads a document several ways
    (`loads` reads it as a kind, an integer and a string; `members` reads five
    keys) slices the record list per reader before calling here, so the record
    position is the case index and no stride is needed.
    """
    check(len(got) == len(cases),
          f"{label}: image reported {len(got)} of {len(cases)} cases; "
          f"first excess: {got[len(cases)][:3] if len(got) > len(cases) else ''}")
    bad = []
    for idx, ln, val in got:
        if ln != len(val):
            bad.append((idx, f"length {ln} but {len(val)} bytes"))
            continue
        want = want_fn(cases[idx])
        if val != want:
            bad.append((idx, f"{val!r} != {want!r}"))
    check(not bad, f"{label}: {len(bad)} case(s) differ from CPython; first: "
                   + (f"idx={bad[0][0]} {bad[0][1]}" if bad else ""))


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import json` finds this file, in the resolver's own order.

    And `json` is out of `HOST_MODELLED`: that set is a CLAIM that the module
    could be written, and `formal/imports.py` says a name leaves it by being
    written, because an entry left behind would refuse a file AFTER the module
    that answers it is sitting in the tree — a false statement rather than a
    conservative one.
    """
    check(os.path.isfile(JSON_MODULE),
          f"no Mojo source for json at {JSON_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("json")
    check(got is not None and os.path.samefile(got, JSON_MODULE),
          f"import json resolves to {got!r}, not {JSON_MODULE!r}")
    tier = I.host_module_tier("json")
    check(tier == "",
          f"json is still in HOST_MODELLED (tier={tier!r}); its Mojo source "
          f"exists, so the entry is now a false statement about the target")
    # The layout rule, asserted from `formal/imports.py` rather than spelled
    # out: a Mojo `json` anywhere else would be found by other resolvers too.
    check(I._HOSTMODS_ROOT == HOSTMODS,
          f"the hostmods root moved to {I._HOSTMODS_ROOT!r}")
    for stray in ("json.mojo",):
        check(not os.path.isfile(os.path.join(HERE, stray)),
              f"{stray} is at the repository root, which four independent "
              f"resolvers search — see _HOSTMODS_ROOT")
    if verbose:
        print(f"    import json -> {os.path.relpath(got, HERE)}, "
              f"host_module_tier={tier!r}")
    return True, f"resolves to {os.path.relpath(got, HERE)}, out of HOST_MODELLED"


# ── group: primitive ───────────────────────────────────────────────────────

def group_primitive(tmpdir, verbose):
    """`byte_at` returns the right value for every byte, in both spellings.

    The two spellings are two different code paths and both are used by
    `json.mojo`: a `malloc`'d buffer, which is what a decoded document is, and
    a string literal, which is what a program's own JSON text is. A byte read
    that is right for one and wrong for the other is exactly the failure a
    previous attempt at this module had, in all three of its
    implementations of the read.
    """
    # (a) every value 0..255, out of a buffer the program fills itself.
    src_buf = ['''import json

def fill(buf) -> int:
    var k = 0
    while k < 256:
        json.put_byte(buf, k, k)
        k = k + 1
    return 0

def main():
    var buf: Pointer[UInt8] = malloc(256)
    fill(buf)
    var k = 0
    while k < 256:
        printf("%d=%d%s", k, json.byte_at(buf, k), "@@")
        k = k + 1
''']
    got = run(build("\n".join(src_buf), "prim_buf"))
    recs = records(got)
    check(len(recs) == 256, f"buffer sweep reported {len(recs)} of 256")
    bad = [(i, v) for i, ln, v in recs if v != str(i)]
    check(not bad, f"{len(bad)} buffer byte(s) wrong; first: "
                   + (f"idx={bad[0][0]} got {bad[0][1]!r} want "
                      f"{str(bad[0][0])!r}" if bad else ""))

    # (b) every printable ASCII value, out of string literals — 32 at a time
    # so no single literal is enormous, and so a truncation in one of them
    # shows up as a length mismatch rather than as a plausible number. The
    # literals go through the same MASK every other corpus uses, because
    # `"` and `\` are among the 95 and a source literal cannot hold either.
    vals = list(range(32, 127))
    runs = [vals[i:i + 32] for i in range(0, len(vals), 32)]
    parts = ["import json", "", UNMASK]
    for idx, r in enumerate(runs):
        parts.append(
            "def sum_S%d(s) -> int:\n"
            "    var a = 0\n"
            "    var i = 0\n"
            "    while i < %d:\n"
            "        a = a + json.byte_at(s, i) * (i + 1)\n"
            "        i = i + 1\n"
            "    return a\n" % (idx, len(r)))
    parts.append("def main():")
    for idx, r in enumerate(runs):
        parts.append("    var S%d = unmask(%s)"
                     % (idx, mj(mask(bytes(r)))))
        parts.append("    var t%d = sum_S%d(S%d)" % (idx, idx, idx))
    parts.append("    var acc = 0")
    for idx in range(len(runs)):
        parts.append("    acc = acc + t%d" % idx)
    parts.append('    printf("0=%d%s", acc, "@@")')
    got = run(build("\n".join(parts) + "\n", "prim_lit"))
    m = re.findall(r"^0=(\d+)@@$", got)
    check(m, f"literal sweep produced {got!r}, which is not one number record")
    # The weight is the index inside the run, and the expectation is built
    # from `vals` — the bytes the UNMASKED literal holds. So a mask that
    # disagreed with Python, or an unmask that lost a byte, moves this number
    # and not only the per-value check below.
    want = sum(v * (i + 1) for r in runs for i, v in enumerate(r))
    check(m[0] == str(want),
          f"literal byte sweep: image {m[0]!r}, unmasked bytes imply {want}")

    # (c) and the same thing value by value for the literals, against CPython's
    # own `ord`, so a checksum that happened to agree cannot hide a swap.
    parts = ["import json", "", UNMASK, "def main():", "    var k = 0"]
    for idx, r in enumerate(runs):
        parts.append("    var S%d = unmask(%s)"
                     % (idx, mj(mask(bytes(r)))))
    for idx, r in enumerate(runs):
        for i in range(len(r)):
            parts.append(f'    printf("%d=%d' + REC + '", k, json.byte_at('
                         f'S{idx}, {i}), "' + REC + '")')
            parts.append("    k = k + 1")
    got = run(build("\n".join(parts) + "\n", "prim_lit2"))
    recs = records(got)
    check(len(recs) == len(vals),
          f"per-value literal sweep reported {len(recs)} of {len(vals)}")
    bad = [(idx, v, want_v) for (idx, ln, v), want_v in zip(recs, vals)
           if int(v) != want_v]
    check(not bad, f"{len(bad)} literal byte(s) wrong; first: "
                   + (f"idx={bad[0][0]} got {bad[0][1]} want {bad[0][2]}"
                      if bad else ""))
    if verbose:
        print(f"    {256} buffer byte values and {len(vals)} literal byte "
              f"values, each against CPython's ord")
    return True, f"351 byte values ({256} buffer + {len(vals)} literal)"


# ── the corpora ────────────────────────────────────────────────────────────
#
# Written for SHAPES rather than for words, and every one of them is fed to
# CPython as well, so the corpus is never a claim about what the answer is.

VALID_CORPUS = [
    b'null', b'true', b'false',
    b'0', b'-0', b'1', b'-1', b'123', b'-123', b'1234567890',
    b'0.0', b'1.5', b'-1.5', b'1e10', b'1E10', b'1e+10', b'1e-10', b'-1.5e-3',
    b'0.0001', b'123456789012345678901234567890',
    b'""', b'"a"', b'" "', b'"\\u0041"', b'"\\ud83d\\ude00"', b'"\\ud800"',
    b'"\\udc00\\ud800"', b'"\\/"', b'"\\b\\f\\n\\r\\t"', b'"\\"\\\\"',
    b'"a\x7fb"', b'"tab\there"',
    b'[]', b'[1]', b'[1,2,3]', b'[[]]', b'[{}]', b'[[[]]]', b'[null,true,false]',
    b'[1,[2,[3,[4]]]]', b'[{"a":1},{"b":2}]', b'["",1,null]',
    b'{}', b'{"a":1}', b'{"a":1,"b":2}', b'{"":""}', b'{"a":{"b":{"c":1}}}',
    b'{"a":[1,2,{"b":null}]}', b'{"a b":1}', b'{"\\u0041":1}',
    b'  null  ', b'\t\r\n{"a" : 1 , "b" : [ 1 , 2 ] }\t\n',
    b'NaN', b'Infinity', b'-Infinity',
]

INVALID_CORPUS = [
    b'', b' ', b'\t', b'{', b'}', b'[', b']', b':', b',',
    b'nul', b'tru', b'fals', b'NULL', b'True', b'False',
    b'-', b'+1', b'.5', b'1.', b'01', b'-01', b'1e', b'1e+', b'1e-', b'--1',
    b'1.2.3', b'1..2', b'0x10', b'1 2', b'{} {}', b'[] []',
    b'[1,]', b'[,1]', b'{,}', b'[1 2]', b'{"a"}', b'{"a":}', b'{"a":1,}',
    b'{"a":1 "b":2}', b'{"a":1]', b'{:1}', b'{"a" "b"}', b'{"a":1}}',
    b'"unterminated', b'"bad \\q escape"', b'"\\u12"', b'"\\uZZZZ"',
    b'"\\u', b'"tab\there"', b'"nl\nhere"', b'"cr\rhere"',
    b'"\\x41"', b'nans', b'infinity', b'-infinity', b'InfinityX', b'NaNX',
    b'truetrue', b'[', b'{"a":}',
]

# Every escape RFC 8259 defines, in both directions, plus the two spellings
# CPython accepts for nothing at all.
ESCAPE_CORPUS = [
    b'"\\b\\f\\n\\r\\t"', b'"\\"\\\\\\/"', b'"\\u0041\\u00e9\\u20ac"',
    b'"\\uD83D\\uDE00"', b'"\\ud83d\\ude00"', b'"\\u001f\\u007f"',
    b'"\\uFFFF"', b'"\xef\xbf\xbf"', b'"\\u0041\\u0042"',
    b'"\\uD83D\\uDE00\\uD83D"', b'"\\uD83D\\uDE00x"', b'"\\uD83D\\uDE00\\u0041"',
    b'"\\b"', b'"\\f"', b'"\\n"', b'"\\r"', b'"\\t"', b'"\\u0008"',
    b'"\\a"', b'"\\v"', b'"\\0"', b'"\\U0041"', b'"\\u 041"',
    b'"\\u041"', b'"\\u041g"', b'"\\uD83D"', b'"\\uDE00"',
    b'"\\uDC00\\uD800"', b'"\\uD800x"', b'"\\uD83D\\uDE"',
    # `\u0000` is in NO corpus here and cannot be: a formal string is a
    # NUL-terminated `char *`, so a decoded NUL ends the string and every byte
    # after it is past the end. Stated at `loads_str` and under the module's
    # own "WHAT IS NOT HERE", and the first version of this corpus HAD one and
    # failed on exactly that.
]

# `dumps_str` inputs. No NUL (a formal string cannot hold one) and no `@`
# (the record terminator is `@@`, and a value containing one would mis-align
# the parser — stated here rather than discovered). The malformed UTF-8 at the
# end are for `utf8_at`'s documented U+FFFD answer.
DUMPS_CORPUS = [
    b'', b'a', b'abc', b'plain text', b'with space',
    b'quote"', b'backslash\\', b'both"\\', b'slash/',
    b'\x01\x07\x08\t\n\x0b\x0c\r\x1f', b'\x7f', b' \x7f ',
    b'\x1b[0m', b'\xc3\xa9', b'\xc3\xa9\xc3\xa8', b'\xe2\x82\xac',
    b'\xf0\x9f\x98\x80', b'\xf0\x9f\x98\x80\xf0\x9f\x98\x81',
    b'\x01\x02\x03', b'\x1f\x7f ', b'\x20', b'~',
    b'\xf4\x8f\xbf\xbf', b'\xef\xbf\xbd', b'\xc2\x80', b'\xc2\xa9',
    b'mixed "q" and \\b\\ and \xc3\xa9', b'tab\ttab', b'nl\nnl',
    b'\xed\xa0\x80', b'\xf4\x90\x80\x80', b'\xc3', b'\xe2\x82',
    b'\x80', b'\xbf', b'\xf8\x88\x80\x80\x80', b'~~', b'a~b',
]

# `dumps_str` inputs whose every code point is in a range, generated so the
# surrogate-pair arithmetic is checked over the WHOLE range and not at four
# hand-picked points. These are emitted one program per chunk, each chunk
# small, because `main` is a few hundred statements per program before
# `bugs/FORMAL_always_returns_recurses_past_the_stack_on_a_large_function.md`
# bites.
CP_RANGES = [
    (0x01, 0x7F), (0x80, 0xFF), (0x100, 0x2FF), (0x300, 0x4FF),
    (0x500, 0x6FF), (0x700, 0x8FF), (0x900, 0xAFF), (0xB00, 0xCFF),
    (0xD00, 0xD7FF), (0xE000, 0xEFFF), (0xF000, 0xFFFF),
    (0x10000, 0x100FF), (0x10300, 0x103FF), (0x10400, 0x104FF),
    (0x1D000, 0x1D0FF), (0x1F600, 0x1F6FF), (0x20000, 0x200FF),
    (0x2FFFF, 0x30000), (0x10FF00, 0x10FFFF),
]

MEMBER_CORPUS = [
    b'{}', b'{"a":1}', b'{"n":42}', b'{"s":"x"}', b'{"b":true}',
    b'{"n":-7}', b'{"n":0}', b'{"a":{"n":1}}', b'{"a":[1,2]}',
    b'{"n":1,"m":2}', b'{"m":2,"n":1}', b'{"n":1.9}', b'{"n":1e3}',
    b'{"n":"7"}', b'{"ab":1}', b'{"":1}', b'[{"n":1}]', b'{"n":null}',
    b'{"n":NaN}', b'  {"n" : 5 }  ', b'{"a b":9}', b'{"a\\"b":3}',
    b'{"A":1,"a":2}', b'{"n":-0}', b'{"n":123456789012345678901234567890}',
]

LOADS_CORPUS = [
    b'0', b'1', b'-1', b'42', b'-42', b'  42  ', b'0.0', b'2.9', b'-2.9',
    b'1e3', b'1E3', b'-1e-3', b'0.5', b'-0.5', b'123456789', b'-123456789',
    b'9007199254740993', b'1e400', b'-0', b'0.000001',
    b'9223372036854775807', b'-9223372036854775808',
    b'9223372036854775808', b'99999999999999999999',
    b'"a"', b'""', b'"hello world"', b'"\\t"', b'"\\u0041"', b'"\\u00e9"',
    b'"\\n\\r\\t"', b'"quote\\"inside"', b'"back\\\\slash"',
    b'  "padded"  ', b'"\\ud83d\\ude00"',
    b'true', b'false', b'null', b'[1]', b'{}', b'NaN', b'Infinity',
    b'-Infinity', b'not a number', b'', b'   ',
]


def py_dumps(b: bytes) -> str:
    """CPython's `json.dumps` of what those bytes are, `errors="replace"`.

    `replace` rather than `surrogatepass` because it is the decoder whose rule
    `utf8_at` and `next_cp` are written to match: one U+FFFD per byte that
    starts nothing well-formed. Every case in `DUMPS_CORPUS` therefore HAS a
    CPython oracle, malformed sequences included, which is the point of
    matching it rather than inventing a rule of our own.
    """
    return json.dumps(b.decode("utf-8", "replace")).encode("ascii",
                                                           "backslashreplace"
                                                           ).decode("latin-1")


def py_valid(b: bytes) -> str:
    try:
        json.loads(b.decode("utf-8"))
    except Exception:
        return "0"
    return "1"


def py_kind(b: bytes) -> str:
    try:
        v = json.loads(b.decode("utf-8"))
    except Exception:
        return "-1"
    if v is None:
        return "0"
    if v is False:
        return "1"
    if v is True:
        return "2"
    if isinstance(v, int):
        return "3"
    if isinstance(v, float):
        return "4"
    if isinstance(v, str):
        return "5"
    if isinstance(v, list):
        return "6"
    return "7"


# The `@@`-joined, masked corpus a generated program carries.
def corpus_const(cases):
    """The `CASES` module-level constant the generated programs carry.

    A TRAILING separator, and the reason is a measured one: the driver's loop
    finds the next `@@` and then skips two, so a corpus with no trailing
    separator leaves the last index reading past the end, `sub` is handed
    `j = -1`, and `malloc` is handed a negative size. The image died with
    SIGSEGV before its first record, which is a worse way to find that out
    than a separator at the end of the string.
    """
    masked = []
    for c in cases:
        m = mask(c)
        if REC in m:
            raise Failure(f"corpus case {c!r} masks to {m!r}, which contains "
                          f"the record terminator; the parser would mis-align")
        masked.append(m)
    return "CASES = " + mj(REC.join(masked) + REC)


def group_valid(tmpdir, verbose):
    """`json.valid` against CPython's accept/reject, over both corpora."""
    cases = VALID_CORPUS + INVALID_CORPUS
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           '        printf("%d=%d%s", k, json.valid(s), "@@")',
           "        i = j + 2",
           "        k = k + 1"]
    got = run(build("\n".join(src) + "\n", "valid"))
    compare("valid", cases, records(got), py_valid)
    if verbose:
        print(f"    {len(cases)} documents, {len(VALID_CORPUS)} of them valid")
    return True, f"{len(cases)} documents agree with CPython"


def group_kinds(tmpdir, verbose):
    """`json.top_kind` against CPython's own type of the parsed value."""
    cases = VALID_CORPUS + INVALID_CORPUS
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           '        printf("%d=%d%s", k, json.top_kind(s), "@@")',
           "        i = j + 2", "        k = k + 1"]
    got = run(build("\n".join(src) + "\n", "kinds"))
    compare("kinds", cases, records(got), py_kind)
    if verbose:
        print(f"    {len(cases)} documents, kind 0..7 and -1 for malformed")
    return True, f"{len(cases)} kinds agree with CPython"


def group_loads(tmpdir, verbose):
    """`loads_int` / `loads_str` against CPython, for every scalar document.

    One program, three records per case: the kind, then the integer, then the
    string. They are three separate modules' worth of question and three
    separate failure modes, and a corpus that only had integers in it would
    let a broken string reader through.
    """
    cases = LOADS_CORPUS
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           '        printf("%d=%d%s", k, json.top_kind(s), "@@")',
           '        printf("%d=%lld%s", k, json.loads_int(s), "@@")',
           '        var t = json.loads_str(s)',
           '        printf("%d:%s%s", strlen(t), t, "@@")',
           "        i = j + 2", "        k = k + 1"]
    got = records(run(build("\n".join(src) + "\n", "loads")))
    kinds, ints, strs = reader(got, 0, 3), reader(got, 1, 3), reader(got, 2, 3)
    compare("loads/top_kind", cases, kinds, py_kind)
    compare("loads/loads_int", cases, ints, py_loads_int)
    compare("loads/loads_str", cases, strs, py_loads_str)
    if verbose:
        print(f"    {len(cases)} documents x 3 readers")
    return True, f"{len(cases)} x 3 loads agree with CPython"


_HAS_EXPONENT = re.compile(rb"^-?\d+(\.\d+)?[eE]")


def py_loads_int(b: bytes) -> str:
    try:
        v = json.loads(b.decode("utf-8"))
    except Exception:
        return "0"
    if isinstance(v, bool) or v is None or not isinstance(v, (int, float)):
        return "0"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return "0"
        # An EXPONENT in the spelling means the value is a float that was
        # reached through one, and `loads_int` documents 0 for that: a float is
        # not a value on this target, so scaling a mantissa is not arithmetic
        # it has. `repr` is the test's own rule for "was an exponent needed",
        # and a float whose shortest repr carries no `e` was written exactly.
    # An EXPONENT in the SPELLING means the value is a float that was reached
    # through one, and `loads_int` documents 0 for that: a float is not a
    # value on this target, so scaling a mantissa is not arithmetic it has.
    # The test's rule is "does the document carry an exponent", read off the
    # document — not `repr` of the value, because `repr(1000.0)` is
    # `'1000.0'` and would have hidden exactly the case this is about.
    if _HAS_EXPONENT.match(b.strip()):
        return "0"
    # CPython's int() on a float truncates toward zero, and truncating the
    # digit string up to the point is the same answer for a fraction.
    n = int(v)
    if not -2**63 <= n < 2**63:
        # A formal value is ONE 64-bit word, so an integer outside it has no
        # representation; `loads_int` documents 0 rather than wrapping, and
        # this is the test saying the same thing about CPython's answer.
        return "0"
    return str(n)


def py_loads_str(b: bytes) -> str:
    try:
        v = json.loads(b.decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(v, str):
        return ""
    return v.encode("utf-8", "surrogatepass").decode("latin-1")


def group_members(tmpdir, verbose):
    """`member_int` / `member_str` / `member_kind` against `d["key"]`.

    Three keys per document — the one that is there, one that is not, and one
    that differs only in case — because "not found" and "found and wrong" are
    different failures and a corpus with only the first key present cannot
    tell them apart.
    """
    cases = MEMBER_CORPUS
    keys = ["n", "zz", "N"]
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           '        printf("%d=%d%s", k, json.member_kind(s, "n"), "@@")',
           '        printf("%d=%lld%s", k, json.member_int(s, "n"), "@@")',
           '        var t = json.member_str(s, "n")',
           '        printf("%d:%s%s", strlen(t), t, "@@")',
           '        printf("%d=%d%s", k, json.member_kind(s, "zz"), "@@")',
           '        printf("%d=%d%s", k, json.member_kind(s, "N"), "@@")',
           "        i = j + 2", "        k = k + 1"]
    got = records(run(build("\n".join(src) + "\n", "members")))
    kd, iv, sv, miss, wrongcase = (reader(got, 0, 5), reader(got, 1, 5),
                                   reader(got, 2, 5), reader(got, 3, 5),
                                   reader(got, 4, 5))
    compare("members/member_kind", cases, kd, lambda b: py_member_kind(b, "n"))
    compare("members/member_int", cases, iv, lambda b: py_member_int(b, "n"))
    compare("members/member_str", cases, sv, lambda b: py_member_str(b, "n"))
    compare("members/absent", cases, miss, lambda b: py_member_kind(b, "zz"))
    compare("members/case", cases, wrongcase, lambda b: py_member_kind(b, "N"))
    if verbose:
        print(f"    {len(cases)} objects x 5 reads (present, absent, case)")
    return True, f"{len(cases)} x 5 member reads agree with CPython"


_ABSENT = object()


def _member(b, key):
    """The value of `key`, or `_ABSENT`.

    A distinct sentinel and not `None`, because `{"n": null}` HAS the key and
    `None` is what it is worth: a `None` sentinel reports that document as
    having no `n` at all, and the first version of this test did exactly that
    and called the module wrong for it.
    """
    try:
        v = json.loads(b.decode("utf-8"))
    except Exception:
        return _ABSENT
    if not isinstance(v, dict) or key not in v:
        return _ABSENT
    return v[key]


def py_member_kind(b, key):
    v = _member(b, key)
    if v is _ABSENT:
        return "-1"
    return py_kind(json.dumps(v).encode("utf-8", "surrogatepass"))


_MEMBER_TEXT = {}


def _member_text(b: bytes, key: str):
    """The member's raw value TEXT in the document, or None.

    Only for the exponent question. `loads_int` documents 0 for a number
    SPELLED with an exponent, and re-serialising the parsed value loses the
    spelling: `json.dumps(1000.0)` is `'1000.0'`, so `{"n": 1e3}` and
    `{"n": 1000.0}` would be indistinguishable and the oracle would be wrong
    about one of them. A regex over the document is enough to tell them apart,
    and it is a TEST's reader, not a second JSON parser in the module.
    """
    m = re.search(rb'"' + re.escape(key.encode()) + rb'"\s*:\s*([^,}]+)', b)
    return m.group(1).strip() if m else None


def py_member_int(b, key):
    v = _member(b, key)
    if v is _ABSENT:
        return "0"
    spelled = _member_text(b, key)
    if spelled is not None and _HAS_EXPONENT.match(spelled):
        return "0"
    return py_loads_int(json.dumps(v).encode("utf-8", "surrogatepass"))


def py_member_str(b, key):
    v = _member(b, key)
    if v is _ABSENT:
        return ""
    if not isinstance(v, str):
        return ""
    return v.encode("utf-8", "surrogatepass").decode("latin-1")


def group_escapes(tmpdir, verbose):
    """The escape table, both directions, against CPython.

    `valid`/`top_kind` check that the scanner ACCEPTS what RFC 8259 defines and
    REFUSES what it does not; `dumps` checks the encoder's spelling of the
    same table. This group is the decoder alone — `loads_str` over a corpus
    that is nothing but escapes — because a decoder that is wrong in a way
    `valid` cannot see (a `\\u0041` that decodes to `B`) is the most likely
    remaining bug in the file.
    """
    cases = ESCAPE_CORPUS
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           '        printf("%d=%d%s", k, json.valid(s), "@@")',
           '        var t = json.loads_str(s)',
           '        printf("%d:%s%s", strlen(t), t, "@@")',
           "        i = j + 2", "        k = k + 1"]
    got = records(run(build("\n".join(src) + "\n", "escapes")))
    compare("escapes/valid", cases, reader(got, 0, 2), py_valid)
    compare("escapes/loads_str", cases, reader(got, 1, 2), py_loads_str)
    if verbose:
        print(f"    {len(cases)} escape spellings, accepted and decoded")
    return True, f"{len(cases)} escape spellings agree with CPython"


def group_dumps(tmpdir, verbose):
    """`dumps_str` / `dumps_int` / `dumps_bool` / `dumps_null`, byte for byte.

    Two parts. The corpus is the hand-picked shapes — every escape class, both
    UTF-8 lengths that need a surrogate pair, the two bytes either side of
    each length boundary, and the malformed sequences `utf8_at` has an answer
    for. Then every code point in nineteen ranges is checked, because the
    surrogate-pair arithmetic is the part of this module most likely to be
    wrong at exactly one point, and four hand-picked points is four chances to
    miss it.
    """
    cases = DUMPS_CORPUS
    src = ["import json", "", corpus_const(cases), UNMASK, SPLIT, "",
           "def main():", "    var i = 0", "    var k = 0",
           "    while i < strlen(CASES):",
           "        var j = ndelim(CASES, i)",
           "        var s = unmask(sub(CASES, i, j))",
           "        var t = json.dumps_str(s)",
           '        printf("%d:%s%s", strlen(t), t, "@@")',
           "        i = j + 2", "        k = k + 1"]
    got = run(build("\n".join(src) + "\n", "dumps"))
    compare("dumps/str", cases, records(got), py_dumps)

    # Every code point in every range, one small program per chunk so `main`
    # stays under the statement count that crashes the backend. The code point
    # is handed to the program as its UTF-8 bytes through the same mask every
    # other corpus uses, so there is no second way of spelling a string here
    # that could disagree with the first.
    #
    # ONE program per range, and not one per case or per small chunk: the
    # statement count of the generated `main` is the same whatever the corpus
    # holds, because the corpus is a string constant and the driver is a loop.
    # A 256-case range costs the same build as a 64-case chunk, and the first
    # version of this chunked at 64 and wanted 1021 of them — an hour of wall
    # clock for coverage the statement count says is free.
    n_cp = 0
    for lo, hi in CP_RANGES:
        part = [c for c in range(lo, hi + 1) if not 0xD800 <= c <= 0xDFFF]
        enc = [chr(c).encode("utf-8") for c in part]
        src = ["import json", "", corpus_const(enc), UNMASK, SPLIT, "",
               "def main():", "    var i = 0", "    var k = 0",
               "    while i < strlen(CASES):",
               "        var j = ndelim(CASES, i)",
               "        var s = unmask(sub(CASES, i, j))",
               "        var t = json.dumps_str(s)",
               '        printf("%d:%s%s", strlen(t), t, "@@")',
               "        i = j + 2", "        k = k + 1"]
        got = records(run(build("\n".join(src) + "\n", f"dumps_cp{lo}")))
        n_cp += len(part)
        check(len(got) == len(part),
              f"dumps_str over U+{lo:04X}..U+{hi:04X}: image reported "
              f"{len(got)} of {len(part)} code points")
        bad = []
        for (idx, ln, v), c in zip(got, part):
            want = json.dumps(chr(c)).encode("ascii").decode("latin-1")
            if v != want:
                bad.append((idx, hex(c), v, want))
        check(not bad, "dumps_str over " + (
            f"U+{lo:04X}..U+{hi:04X}: {len(bad)} code point(s) wrong; first: "
            f"U+{bad[0][1]} image {bad[0][2]!r} CPython {bad[0][3]!r}"
            if bad else ""))

    # The other three, in one program: the scalars whose names exist because a
    # formal value is one word and the module cannot see which it was handed.
    src = ["import json", "", "def main():",
           '    printf("%s%s", json.dumps_int(0), "@@")',
           '    printf("%s%s", json.dumps_int(-1), "@@")',
           '    printf("%s%s", json.dumps_int(1234), "@@")',
           '    printf("%s%s", json.dumps_int(0 - 1234), "@@")',
           '    printf("%s%s", json.dumps_int(9223372036854775807), "@@")',
           '    printf("%s%s", json.dumps_int(0 - 9223372036854775807 - 1), "@@")',
           '    printf("%s%s", json.dumps_bool(1), "@@")',
           '    printf("%s%s", json.dumps_bool(0), "@@")',
           '    printf("%s%s", json.dumps_null(), "@@")']
    got = run(build("\n".join(src) + "\n", "dumps_scalars"))
    want = ["0", "-1", "1234", "-1234", "9223372036854775807",
            "-9223372036854775808", "true", "false", "null"]
    bad = [(i, v) for i, v in enumerate(got.split(REC)[:len(want)])
           if v != want[i]]
    check(len(got.split(REC)) == len(want) + 1,
          f"dumps scalars: image reported {len(got.split(REC)) - 1} of "
          f"{len(want)}")
    check(not bad, f"dumps scalars: {len(bad)} wrong; first: {bad[0] if bad else ''}")
    if verbose:
        print(f"    {len(cases)} shapes + {n_cp} code points + 9 scalars")
    return True, f"{len(cases)} + {n_cp} + 9 dumps agree with CPython"


def group_deep(tmpdir, verbose):
    """Nesting depth, at and past `MAX_DEPTH`.

    `scan_value` -> `scan_array` -> `scan_value` is two frames per level and
    a formal image's stack is the machine stack, so the bound is a real one and
    this group is where it is MEASURED rather than chosen: with no bound at
    all, 28 levels of `[` is answered and 29 is SIGSEGV. `MAX_DEPTH` is 24 —
    below the ceiling, because the check runs inside the frame it is testing
    for — and the levels here straddle both numbers so that a bound which
    stopped answering at all, or one that stopped refusing, would both show.

    The deep side is the half that matters, and it is what the bound is FOR:
    a document nested past it is reported INVALID, so the image answers
    instead of dying. A test that only checked the depths that work would pass
    with no bound at all — `valid` on a 400-deep document crashing is a
    perfectly green run of everything below it.
    """
    levels = 1, 8, 16, 24, 26, 27, 28, 29, 30, 40, 64, 100
    src = ["import json", "", "def nest(n) -> str:",
           "    var out: Pointer[UInt8] = malloc(2 * n + 1)",
           "    var k = 0",
           "    while k < n:",
           '        memcpy(out + k, "[", 1)',
           "        k = k + 1",
           "    var j = 0",
           "    while j < n:",
           '        memcpy(out + k, "]", 1)',
           "        k = k + 1",
           "        j = j + 1",
           "    json.put_byte(out, k, 0)",
           "    return out", "", "def main():"]
    for n in levels:
        src.append(f'    printf("%d=%d{REC}", {n}, json.valid(nest({n})), "{REC}")')
    got = records(run(build("\n".join(src) + "\n", "deep")))
    # Indexed by the record's POSITION, which is the level: one record per
    # level, in the order `levels` gives them.
    want = ["1" if n <= 24 else "0" for n in levels]
    bad = [(levels[i], v) for (i, ln, v) in got if v != want[i]]
    check(not bad, "nesting: " + (f"{len(bad)} depth(s) wrong; first: depth "
                                 f"{bad[0][0]} answered {bad[0][1]} "
                                 f"(the bound is MAX_DEPTH = 24)" if bad else ""))
    if verbose:
        print(f"    depths {levels[0]}..{levels[-1]}, bound at 24")
    return True, f"nesting bound at 24, {len(levels)} depths checked"


def group_absent(tmpdir, verbose):
    """The absent names, asserted as refusals rather than left to discovery.

    Each of these is a CPython `json` name with no representation on this
    target, and the module docstring says which capability each one needs (a
    container cannot cross a dylib boundary; a type is not a value; a float is
    not a formal value). An omission that is not pinned is indistinguishable
    from an implementation, so each is pinned here as a build that fails with
    a message naming the module and the name.
    """
    absent = ["load", "loads", "dump", "dumps", "JSONDecodeError",
              "JSONEncoder", "JSONDecoder", "detect_encoding"]
    for name in absent:
        src = ("import json\n\ndef main() -> int:\n"
               f"  json.{name}()\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_{name}"), tmp],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"json.{name}() built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"json.{name}() failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


GROUPS = {
    "resolve": group_resolve,
    "primitive": group_primitive,
    "valid": group_valid,
    "kinds": group_kinds,
    "loads": group_loads,
    "members": group_members,
    "escapes": group_escapes,
    "dumps": group_dumps,
    "deep": group_deep,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
