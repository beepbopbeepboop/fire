#!/usr/bin/env python3
r"""`formal/hostmods/shlex.mojo`, differential against CPython's `shlex.quote`.

    python3 test_formal_shlex.py [-v] [group ...]

Groups: `resolve`, `quote`, `bytes`, `roundtrip`, `absent`. With no argument, all.
Every group that builds an image builds it on BOTH backends.

WHY THIS FILE EXISTS WHEN THE ROW IS ONE FILE
---------------------------------------------
`tools/formal_sweep_causes.py --host` ranks the host-import rows by files
blocked, and after `glob` landed this was the top of what was left that is both
unclaimed and reachable: **one file**, `tools/suite.py`, which spells
`shlex.quote` three times (`:3524`, `:4525`, `:4526`) and formats a SHELL line
with it. One file is a small win and that is the honest number — the value of
writing the module is that the row is then CLOSED rather than open.

Which also means the module has to be right rather than merely present, because
its one caller builds a command line out of the answer: `shlex.quote` is a
security-relevant function, and a `quote` that drops an unsafe byte returns a
string the shell will re-split. So the corpus is weighted towards the shapes
where being wrong is exploitable rather than towards the shapes where it is
visible — an argument containing a space, a semicolon, a dollar, a backtick, a
quote of each kind, and a byte above 0x7F.

WHAT IS ACTUALLY LOAD-BEARING IN THE FUNCTION
--------------------------------------------
Three things, and each is a case in `quote`'s corpus rather than a comment:

1. **THE EMPTY STRING IS `''`, NOT `""`.**  CPython's `if not s: return "''"`
   fires BEFORE the safe-set walk, and the empty string passes every byte test
   there — so a transcription that folds the case into the fast path answers the
   empty string, and `""` on a shell command line is a SYNTAX ERROR rather than
   an empty argument. This is the one case every transcription of `quote` gets
   wrong and it is the first row of the corpus for that reason.

2. **THE FAST PATH IS ALL-OR-NOTHING.**  There is no "strip the unsafe bytes"
   step anywhere in CPython's function: one byte outside the safe set causes the
   WHOLE string to be single-quoted. A module that filtered instead would agree
   with CPython on every all-safe input and answer something else entirely on
   every other one, and would be a plausible-looking answer.

3. **AN APOSTROPHE INSIDE BECOMES THE FIVE BYTES `'"'"'`.**  `quote("a'b")` is
   the nine-byte `'a'"'"'b'`, and the obvious spelling — replacing `'` with `\'` —
   is not a shell escape at all: inside single quotes a backslash is literal, so
   the answer would be `a\'b` and the shell would pass a trailing-backslash word
   and `b` as TWO arguments. `roundtrip` is the group that checks this one: it splits the
   answer back with the module's own `_split` and requires one token.

THE ORACLE IS CPTHON'S OWN `shlex.quote`, CALLED, NEVER TYPED
-------------------------------------------------------------
Nothing here records what `quote` answers. Every case is computed twice — once by
this process's `shlex` and once by an image built through the formal backend and
executed — and the two have to agree. A table of answers for a function that is
a scan and a substitution is a table that is wrong the moment someone transposes
a character, which is the one mistake a byte-oriented module cannot be allowed
to make.

A CORPUS BYTE CANNOT ALWAYS BE SPELLED, and the mask is the reason
------------------------------------------------------------------
A byte above 0x7F and an unprintable byte have no printable-ASCII representation
in a Mojo literal, so the corpus is written in the MASK alphabet below and
`unmask` is the Mojo half — the same arrangement `test_formal_html.py` and
`test_formal_textwrap.py` use, and for the same reason: every corpus byte goes
through the SAME round trip, so a defect in the mask shows up as one failing case
rather than as a difference between two spellings. The mask is SPELLING and not an
undecoded literal — `decoded_literal` runs inside `_intern_string` on both
architectures, so `"\t"` is a tab.

`bytes` sidesteps the mask entirely by building the input at RUN TIME with
`malloc` and a byte-put helper, which is what makes an exhaustive 1..255 sweep
possible at all.
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
SHLEX_MODULE = os.path.join(HOSTMODS, "shlex.mojo")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 120
REC = "@@"

TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for.

    BOTH, always, and for a sharper reason than the usual one: this function's
    answer is a SHELL COMMAND LINE, so a difference between the two backends
    would be a difference in what a build runs. `gimple_codegen.py` and
    `myinterpreter.py` are separately maintained lowerings of one AST
    (`CLAUDE.md`), and a byte-indexed walk with a computed output length is
    exactly the shape where a register-width difference shows up as a silently
    wrong answer rather than as a refusal.

    A host with no x86-64 support returns one name and `main` says so on the
    screen, rather than the x86-64 half passing over quietly.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def build(src, name, backend=None):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, f"{name}.{backend}" if backend else name)
    with open(tmp, "w") as f:
        f.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(tmp)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode == 0,
          f"build failed{(f' on --backend={backend}' if backend else '')}: "
          f"{(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image {os.path.basename(out)} exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")


def records(text):
    """`<index>:[<value>` records, as `(index, value)` pairs.

    Bracketed value and a two-byte separator, for the reasons
    `test_formal_html.py::records` gives: a value may contain the separator and
    may be empty (the `''` answer and the empty string both have to survive), and
    an INDEX is needed because one image prints many values and a diff that
    cannot say WHICH one went wrong is a diff nobody acts on.
    """
    got = []
    for rec in text.split(REC):
        if not rec:
            continue
        head, sep, val = rec.partition(":[")
        if not sep:
            raise Failure(f"record with no bracket: {rec!r}")
        if not val.endswith("]"):
            raise Failure(f"record with no closing bracket: {rec!r}")
        got.append((int(head), val[:-1]))
    return got


# ── the mask ───────────────────────────────────────────────────────────────
#
# One printable byte per value that has no printable form of its own, and the
# literal byte itself for everything in 0x20..0x7E. A corpus string is written
# in this alphabet and `unmask` is the Mojo half; the escape for `\` is last so
# that a backslash in the corpus is not confused with the start of one.
#
# `~q` for `"` and `~b` for `\` are the two that matter most here: `quote` is
# ABOUT quoting, so a corpus that could not carry a double quote would be a
# corpus that never tested the interesting case.
MASK = {"~t": "\t", "~n": "\n", "~r": "\r", "~q": '"', "~b": "\\",
        "~s": " ", "~z": "\0"}


def mask(text):
    out = []
    i = 0
    while i < len(text):
        if text[i] == "~" and text[i + 1:i + 2] in MASK:
            out.append(MASK[text[i + 1]])
            i += 2
            continue
        c = ord(text[i])
        if 0x20 <= c <= 0x7E and c != ord("~"):
            out.append(text[i])
        elif c < 0x20 or c == 0x7F:
            out.append("~x%02x" % c)
        else:
            out.append("~u%04x" % c)
        i += 1
    return "".join(out)


def unmask_literal(text):
    """The Mojo literal for a masked corpus string, escapes and all."""
    out = ['"']
    i = 0
    while i < len(text):
        if text[i] == "~" and text[i + 1:i + 3] == "x":
            out.append(f'"\\x{int(text[i + 2:i + 4], 16):02d}"')
            i += 4
            continue
        if text[i] == "~" and text[i + 1:i + 5] == "u":
            # A code point above 0xFF is spelled as UTF-8, because a formal
            # string is BYTES: a corpus string holding `é` must carry the two
            # bytes CPython's own encode would produce, and the module's byte
            # walk must quote them for the reason its docstring gives.
            out.append('"' + text[i + 1:i + 5].encode() and "")
            i += 5
            continue
        if text[i] == '"':
            out.append('\\"')
        elif text[i] == "\\":
            out.append("\\\\")
        elif text[i] == "~" and text[i + 1:i + 3] in ("t", "n", "r", "s", "z"):
            out.append({"t": "\\t", "n": "\\n", "r": "\\r", "s": " ",
                        "z": "\\0"}[text[i + 1]])
            i += 2
            continue
        else:
            out.append(text[i])
        i += 1
    out.append('"')
    return "".join(out)


UNMASK = r'''
def shlex_byte(s, i) -> int:
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()

def shlex_put(dst, at, v) -> int:
    var p: Pointer[UInt8] = dst + at
    p.value() = v
    return at + 1

def shlex_hexdig(c) -> int:
    if c >= 48 and c <= 57:
        return c - 48
    if c >= 97 and c <= 102:
        return c - 87
    if c >= 65 and c <= 70:
        return c - 55
    return 0

def unmask(t) -> str:
    var n = strlen(t)
    var out: Pointer[UInt8] = malloc(4 * n + 8)
    var used = 0
    var i = 0
    while i < n:
        var c = shlex_byte(t, i)
        if c == 126:
            var k = shlex_byte(t, i + 1)
            if k == 120:
                used = shlex_put(out, used, 16 * shlex_hexdig(shlex_byte(t, i + 2)) + shlex_hexdig(shlex_byte(t, i + 3)))
                i = i + 4
                continue
            if k == 117:
                var v = 4096 * shlex_hexdig(shlex_byte(t, i + 2)) + 256 * shlex_hexdig(shlex_byte(t, i + 3)) + 16 * shlex_hexdig(shlex_byte(t, i + 4)) + shlex_hexdig(shlex_byte(t, i + 5))
                # UTF-8, because the module walks BYTES and a corpus string with
                # a code point above 0xFF has to carry the same two bytes
                # CPython's own encode produces.
                if v < 0x80:
                    used = shlex_put(out, used, v)
                elif v < 0x800:
                    used = shlex_put(out, used, 192 + v // 64)
                    used = shlex_put(out, used, 128 + v % 64)
                else:
                    used = shlex_put(out, used, 224 + v // 4096)
                    used = shlex_put(out, used, 128 + (v // 64) % 64)
                    used = shlex_put(out, used, 128 + v % 64)
                i = i + 6
                continue
            if k == 116:
                used = shlex_put(out, used, 9)
                i = i + 2
                continue
            if k == 110:
                used = shlex_put(out, used, 10)
                i = i + 2
                continue
            if k == 114:
                used = shlex_put(out, used, 13)
                i = i + 2
                continue
            if k == 115:
                used = shlex_put(out, used, 32)
                i = i + 2
                continue
            if k == 122:
                used = shlex_put(out, used, 0)
                i = i + 2
                continue
            if k == 113:
                used = shlex_put(out, used, 34)
                i = i + 2
                continue
            if k == 98:
                used = shlex_put(out, used, 92)
                i = i + 2
                continue
        used = shlex_put(out, used, c)
        i = i + 1
    shlex_put(out, used, 0)
    return out
'''


# ── the corpus ─────────────────────────────────────────────────────────────
#
# Weighted towards the shapes where a wrong `quote` is EXPLOITABLE rather than
# visible, because this function's one caller builds a command line out of the
# answer. Every case is compared with CPython's own `shlex.quote` called here, so
# the table below is INPUTS and never answers.
#
# The three load-bearing cases are marked and are the first three, in the order
# the module docstring names them.
CORPUS = [
    # 1. THE EMPTY STRING. CPython answers `''` — two apostrophes — because the
    # `if not s` test fires before the safe-set walk, and `""` on a command line
    # is a syntax error rather than an empty argument.
    "",
    # 2. AN APOSTROPHE inside a quoted string. The five-byte expansion is the
    # case `roundtrip` proves: a `\'` spelling would pass the string comparison
    # on nothing and would split into two arguments at run time.
    "a'b",
    # 3. All-or-nothing: ONE unsafe byte in an otherwise safe string, so a module
    # that filtered instead of wrapping answers something else entirely.
    "abc def",
    # …and the rest of the unsafe set, one byte at a time. `#`, `!`, `$`, `&`,
    # `*`, `;`, `<`, `>`, `?`, `[`, `]`, `^`, backtick, `{`, `|`, `}`, `~` and the
    # space are ALL unsafe and every one of them is here because a set built from
    # the memorable half of the alphabet gets one of them wrong.
    "a#b", "a!b", "a$b", "a&b", "a*b", "a;b", "a<b", "a>b", "a?b", "a[b", "a]b",
    "a^b", "a`b", "a{b", "a|b", "a}b", "a~b", "a b",
    # …and the safe half, so a set that was too GENEROUS fails here rather than
    # passing everything: `%+,-./0123456789:=@A-Z_a-z` is exactly what CPython
    # passes through, and each run is a row.
    "abc", "ABC", "0123456789", "%+,-./", ":=@", "a_b", "/usr/bin/python3",
    "-c", "--flag", "x=1", "a:b", "a@b", "9",
    # Quoting characters of each kind, plus a backslash — which is inside single
    # quotes a LITERAL backslash, so `quote("a\\b")` must not gain one.
    'a"b', "a\\b", "a'b\"c", "''", '"', "\\", "'", '""',
    # Control bytes and whitespace the shell treats specially.
    "a\tb", "a\nb", "a\rb", "a\rb\nc",
    # A byte above 0x7F, and a UTF-8 sequence, for the reason the module's
    # docstring gives: every such byte is outside the safe set, so the answer is
    # the quoted form and the sequence must survive intact inside the quotes.
    "café", "日本", "a\x7fb",
    # Longer shapes, so the two-pass structure is exercised: a safe prefix and a
    # safe suffix around the unsafe middle, and the reverse.
    "abc def ghi", "!!!", "   ", "a  b", "a\tb\tc",
    # …and the exact strings `tools/suite.py` formats, because the module's one
    # caller is the test: an interpreter path, a tool path, a flag and a label.
    "/opt/homebrew/bin/python3", "tools/suite.py", "--gb", "8",
    "--label", "proofs bucket", "a b c",
]


def corpus_program(backend):
    """Every corpus case through `quote`, one record per case, in order."""
    import shlex as cpy

    lines = ["import shlex", "", UNMASK, "", "def main():"]
    for idx, case in enumerate(CORPUS):
        lines.append(f"    var s{idx} = unmask({unmask_literal(mask(case))})")
        lines.append(f'    printf("%lld:[%s]{REC}", {idx}, quote(s{idx}))')
    return records(run(build("\n".join(lines) + "\n", "shlex_quote", backend)))


def group_quote(tmpdir, verbose):
    """The corpus, each answer CPython's own `shlex.quote`, on both backends.

    `quote` is a scan and a substitution, so the interesting failures are the
    ones that produce a plausible answer: a set missing one byte, a fast path
    that filters instead of wrapping, an apostrophe expanded to a backslash. All
    three are cases here and the third is case 2.
    """
    for backend in backends():
        got = dict(corpus_program(backend))
        check(len(got) == len(CORPUS),
              f"{len(got)} record(s) for {len(CORPUS)} case(s) on {backend}")
        for idx, case in enumerate(CORPUS):
            want = cpy_shlex_quote(case)
            if got[idx] != want:
                raise Failure(
                    f"[{backend}] case {idx} {mask(case)!r}: the image answered "
                    f"{got[idx]!r}, CPython's shlex.quote answers {want!r}")
        if verbose:
            print(f"    {len(CORPUS)} case(s) agree with CPython on {backend}")
    return True, (f"{len(CORPUS)} case(s) x {len(backends())} backend(s) "
                  f"= {len(CORPUS) * len(backends())} answers, all CPython's")


def cpy_shlex_quote(s):
    """CPython's own answer as BYTES, called — never a table.

    **The encoding step is load-bearing and it is the one thing about this
    comparison that is easy to get wrong in the direction that hides a bug.**  A
    formal string is BYTES and CPython's `quote` is handed a decoded `str`, so
    for a case holding a code point above 0x7F the two sides are given different
    inputs: the image gets `caf\xc3\xa9` (the UTF-8 encoding, via the mask's
    `~u` escape) and CPython gets `caf\xe9` (one code point). Their ANSWERS then
    differ in bytes while agreeing in every decision the function made — which
    is what the module's docstring claims, and claiming it is not the same as
    having compared it.

    So the comparison is made on bytes: `run` decodes the image's output as
    latin-1, which is a bijection onto bytes, and this encodes CPython's answer
    as UTF-8, which is the encoding the mask put into the image. For every ASCII
    case the two are the same bytes and nothing changes; for `café`, `日本` and
    `a\x7fb` it is the difference between comparing the program's answer and
    comparing a re-encoding of it.

    What this does NOT do is compare the module against itself: the module's
    `quote` returned the bytes, `run` handed them over unchanged, and CPython's
    answer went through `str.encode` once. A module that emitted the QUOTED form
    with the wrong bytes still fails here.
    """
    import shlex as cpy
    return cpy.quote(s).encode("utf-8").decode("latin-1")


CONCAT = r"""
def shlex_concat(a, b) -> str:
    var n = strlen(a)
    var out: Pointer[UInt8] = malloc(n + strlen(b) + 1)
    memcpy(out, a, n)
    memcpy(out + n, b, strlen(b))
    shlex_put(out, n + strlen(b), 0)
    return out
"""


def _quote_bytes(cpy, raw):
    """CPython's `quote` on an arbitrary byte string, as the same bytes.

    `surrogateescape` on both sides is what makes this exact for a byte that is
    not a character: 0x80..0xFF decode to U+DC80..U+DCFF, which `quote` treats
    as ordinary non-safe code points, and encode back to the original byte. For
    0x01..0x7F the whole round trip is the identity, so the row is a plain
    comparison.
    """
    text = raw.decode("utf-8", "surrogateescape")
    return cpy.quote(text).encode("utf-8", "surrogateescape")


def bytes_program(backend):
    """Every byte 1..255 as a ONE-BYTE string, and again after a safe byte.

    The exhaustive half, and a separate group from `quote`'s corpus because it
    is a different CLAIM: the corpus says the function is right on the
    characters anyone writes, this says its byte set is indexed right for every
    byte there is. A module whose set were built from `string.ascii_letters +
    string.digits + "_-./"` passes the whole corpus and fails here at `!`.

    The two-byte form is the half the corpus cannot reach: a byte is only unsafe
    if it appears AT ALL, so `a` followed by an unsafe byte must be quoted whole.
    A module that checked the LAST byte, or that checked the first and assumed
    the rest, agrees on every one-byte case and disagrees on every two-byte one.

    The input is built at RUN TIME with `malloc`, which is what makes the sweep
    possible: a byte above 0x7F has no printable spelling in a Mojo literal. The
    helper that concatenates is a function DEFINED IN THE PROGRAM rather than one
    imported, because `shlex.mojo`'s own `_prefix`-shaped helpers are private and
    a private name is not exported — which is the same fact `roundtrip`'s
    docstring records about the `_split` that was removed.
    """
    vals = list(range(1, 256))
    lines = ["import shlex", "", UNMASK, "", CONCAT, "",
             "def mkbyte(v) -> str:",
             "    var b: Pointer[UInt8] = malloc(2)",
             "    shlex_put(b, 0, v)",
             "    shlex_put(b, 1, 0)",
             "    return b",
             "", "def main():"]
    for idx, c in enumerate(vals):
        lines.append(f'    printf("%lld:[%s]{REC}", {idx}, '
                     f'quote(mkbyte({c})))')
        lines.append(f'    printf("%lld:[%s]{REC}", {len(vals) + idx}, '
                     f'quote(shlex_concat(mkbyte(97), mkbyte({c}))))')
    return records(run(build("\n".join(lines) + "\n", "shlex_bytes", backend)))


def group_bytes(tmpdir, verbose):
    """510 answers per backend (255 one-byte and 255 two-byte), CPython's own.

    Every one of them is computed by calling CPython's `shlex.quote` on a
    `bytes` object decoded as latin-1, so the oracle has the same BYTES the image
    was given and there is no encoding step for the two to disagree about.
    """
    import shlex as cpy

    for backend in backends():
        got = dict(bytes_program(backend))
        vals = list(range(1, 256))
        check(len(got) == 2 * len(vals),
              f"{len(got)} record(s) for {2 * len(vals)} on {backend}")
        for idx, c in enumerate(vals):
            # The oracle for a byte CPython's `quote` cannot be handed as a
            # character: `surrogateescape` maps 0x80..0xFF to U+DC80..U+DCFF and
            # back, so `quote`'s answer re-encodes to the EXACT byte the image
            # was handed.
            #
            # This is not a detail and the first version of it was wrong in the
            # direction that hides a bug: latin-1 maps 0x80 to U+0080, whose
            # UTF-8 encoding is TWO bytes, so the oracle's answer for a single
            # 0x80 was `\xc2\x80` while the image's was `\x80` and the row
            # reported the module's safe set as wrong when the safe set was
            # right. Every byte 0x80..0xFF would have failed the same way. With
            # `surrogateescape` the round trip is the identity for 0x01..0x7F
            # and exact for the rest, and a byte that is not in the safe set
            # fails here on its own merits.
            one = _quote_bytes(cpy, bytes([c])).decode("latin-1")
            two = _quote_bytes(cpy, b"a" + bytes([c])).decode("latin-1")
            if got[idx] != one:
                raise Failure(
                    f"[{backend}] byte 0x{c:02x} alone: the image answered "
                    f"{got[idx]!r}, CPython answers {one!r} — the safe set is "
                    f"wrong about this byte")
            if got[len(vals) + idx] != two:
                raise Failure(
                    f"[{backend}] `a` then 0x{c:02x}: the image answered "
                    f"{got[len(vals) + idx]!r}, CPython answers {two!r} — the "
                    f"test is all-or-nothing and this one is not")
        if verbose:
            print(f"    {2 * len(vals)} byte answer(s) agree on {backend}")
    return True, (f"{2 * len(vals)} answer(s) x {len(backends())} backend(s) "
                  f"= {2 * len(vals) * len(backends())}, all CPython's")


def group_roundtrip(tmpdir, verbose):
    """CPython's own `shlex.split` on the module's answer, and the input back.

    `quote`'s string answer is CPython's, and `quote`'s corpus already checks
    that; what no other group here checks is that the answer is ONE SHELL WORD.
    That is the property the module's one caller depends on —
    `tools/suite.py` builds a command line out of it — and it is not a property
    of the string: a module that agreed with CPython byte for byte and produced
    an answer CPython's own parser splits in two would pass `quote` and fail a
    build.

    **The oracle is CPython's parser, not a transcription of it.**  This group
    existed first with the module's own `_split` as the reader, and that was
    wrong twice over: a private name is not exported, so the group was refused
    with the export rule's sentence, and a second transcription of the same
    function in the same tree could agree with a broken module by being broken
    the same way.  CPython's `shlex.split` is the thing the answer has to
    survive, so it is what asks.

    The empty string is the one case that does not round-trip, and it does not
    round-trip in CPython either: `shlex.split(shlex.quote(""))` is `["''"]`,
    two characters, because `quote("")` is the two-character string `''` and the
    shell word it denotes is that string's CONTENTS, which is empty. So the row
    for it is `["''"]` and the assertion is on CPython's own answer rather than
    on a hand-written expectation — which is also why this group compares
    against `cpy.split(...)` and not against `[case]`.
    """
    import shlex as cpy

    for backend in backends():
        got = dict(corpus_program(backend))
        check(len(got) == len(CORPUS),
              f"{len(got)} record(s) for {len(CORPUS)} case(s) on {backend}")
        for idx, case in enumerate(CORPUS):
            answer = got[idx].encode("latin-1").decode("utf-8")
            want = cpy.split(answer)
            if case == "":
                # CPython's own answer, measured rather than asserted: the empty
                # argument is quoted as `''` and the shell word it denotes is
                # the two characters `''`, because that is what `''` is.
                expect = cpy.split(cpy.quote(""))
                if want != expect or len(expect) != 1:
                    raise Failure(
                        f"[{backend}] case {idx}: the empty string's answer "
                        f"{answer!r} splits to {want!r}, and CPython's own "
                        f"`split(quote(''))` is {expect!r} — one argument, "
                        f"whose text is the two characters")
            elif want != [case]:
                raise Failure(
                    f"[{backend}] case {idx} {mask(case)!r}: the image's answer "
                    f"{answer!r} splits to {want!r}, not back to "
                    f"[{case!r}] — the quoting is not ONE shell word, which is "
                    f"the only property `tools/suite.py` needs of it")
        if verbose:
            print(f"    {len(CORPUS)} answer(s) re-split to the input on "
                  f"{backend}")
    return True, (f"{len(CORPUS)} answer(s) x {len(backends())} backend(s) "
                  f"re-split by CPython's own shlex.split to the input")


def group_resolve(tmpdir, verbose):
    """`import shlex` finds this file, and it is out of `HOST_UNREACHABLE`.

    And the diagnostic that used to be wrong about it is gone with the entry:
    `shlex` was in NEITHER tier, which made `unresolvable_import_error` say "not
    a stdlib or sibling module, and no such file exists" — a false statement
    about a name CPython ships. `formal/imports.py`'s own rule is that a name
    LEAVES a tier by being written, and an entry left behind would refuse a file
    AFTER the module that answers it is sitting in the tree.
    """
    check(os.path.isfile(SHLEX_MODULE),
          f"no Mojo source for shlex at {SHLEX_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("shlex")
    check(got is not None and os.path.samefile(got, SHLEX_MODULE),
          f"import shlex resolves to {got!r}, not {SHLEX_MODULE!r}")
    tier = I.host_module_tier("shlex")
    check(tier == "",
          f"shlex is still tiered ({tier!r}); its Mojo source exists, so the "
          f"entry is now a false statement about the target")
    check(I._HOSTMODS_ROOT == HOSTMODS,
          f"the hostmods root moved to {I._HOSTMODS_ROOT!r}")
    check(not os.path.isfile(os.path.join(HERE, "shlex.mojo")),
          "shlex.mojo is at the repository root, which four independent "
          "resolvers search — see _HOSTMODS_ROOT")
    if verbose:
        print(f"    import shlex -> {os.path.relpath(got, HERE)}, "
              f"host_module_tier={tier!r}")
    return True, f"resolves to {os.path.relpath(got, HERE)}, out of every tier"


def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused naming themselves.

    `split` is the one a reader expects, because `shlex.split` is pure and
    nothing about it looks like a list until you notice that its ANSWER is one.
    `join` is a generator and a list; `shlex` is the class; `punct_chars` and
    `whitespace` and `commenters` are module-level SETS, which on this path have
    no storage at all (`bugs/FORMAL_module_state_no_storage.md`).

    Each is refused NAMING ITSELF, so a caller that wants one is told which one
    and why rather than getting a link error — and `_split` is checked to still
    be absent, because the module keeps it for its own test and a reader who
    finds it exported would conclude the public one is reachable too.
    """
    for name, arg in (("split", '"a b"'), ("join", '""'),
                      ("shlex", '""'), ("punct_chars", ""),
                      ("whitespace", ""), ("commenters", "")):
        src = ("import shlex\n\ndef main():\n"
               f'    printf("%lld\\n", shlex.{name}({arg}))\n')
        tmp = os.path.join(TEMP, "absent.mojo")
        out = os.path.join(TEMP, "absent")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                            "--no-prove", "-o", out, tmp],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        msg = (r.stderr or r.stdout)
        check(r.returncode != 0,
              f"shlex.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for shlex.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    return True, "6 absent names refused, each naming itself"


GROUPS = {
    "resolve": group_resolve,
    "quote": group_quote,
    "bytes": group_bytes,
    "roundtrip": group_roundtrip,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    with tempfile.TemporaryDirectory(prefix="shlextest") as td:
        TEMP = td
        npass = nfail = 0
        for nm in names:
            try:
                _ok, msg = GROUPS[nm](td, args.verbose)
                print(f"PASS {nm:10} {msg}")
                npass += 1
            except Failure as e:
                print(f"FAIL {nm:10} {e}")
                nfail += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {nm:9} {type(e).__name__}: {e}")
                nfail += 1
        print(f"\nformal shlex: PASS={npass} FAIL={nfail} "
              f"(backends: {', '.join(backends())})")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())