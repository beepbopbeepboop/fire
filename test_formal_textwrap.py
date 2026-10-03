#!/usr/bin/env python3
"""`formal/hostmods/textwrap.mojo`, differential against CPython's `textwrap`.

    python3 test_formal_textwrap.py [-v] [group ...]

Groups: `resolve`, `dedent`, `indent`, `boundary`, `absent`. With no argument,
all. Both groups build and RUN an image on BOTH backends.

WHY THE ORACLE IS CPython AND NOT A TABLE
------------------------------------------
`dedent` is the function in CPython whose correct-looking reimplementation is
most likely to be wrong, and wrong in a way no self-consistency check sees. Its
margin is NOT "the smallest indentation in the text": CPython takes the
lexicographic MINIMUM and MAXIMUM of the non-blank lines and walks the two in
step, which is a different number whenever the lines' CONTENT differs after
their indent. A hand-written `min(len(indent) for ...)` agrees with CPython on
every uniformly-indented block — which is every block anybody writes — and
disagrees on exactly the mixed ones.

So every case here is computed twice: once by this process's own `textwrap`
and once by an image built through the formal backend and EXECUTED. Nothing in
this file is a recorded constant. The corpus carries, on purpose:

  * lines whose content differs after a COMMON indent, so the min/max pair is
    exercised and the "smallest indent" reading is caught;
  * a TAB against a SPACE at the same offset, which is where the margin stops
    mid-run (CPython's docstring: tabs and spaces "are not equal");
  * 0x1C/0x1D/0x1E/0x1F, which `str.isspace()` is true of — 0x1F surprises,
    and `str.splitlines` is NOT, so a module that used one byte set for both
    questions fails here;
  * `\\r`, `\\r\\n` and `\\v`, which `dedent` does not treat as boundaries and
    `indent` does — the asymmetry the module's docstring is about;
  * the empty string, a lone newline, a trailing newline, a leading blank line
    and an all-whitespace input, because `dedent` REPLACES a whitespace line
    with the empty string rather than trimming it.

THE CORPUS IS ASCII, and says so
---------------------------------
`str.splitlines` also breaks on U+0085, U+2028 and U+2029. Those are not single
bytes and cannot be recognised in a byte string, so a corpus written in decoded
source bytes would compare this module against CPython over DIFFERENT text. Every
case below is ASCII, the two non-ASCII boundaries are named in the module's own
docstring as out of reach, and `boundary` pins the ASCII half of the set.

THE RECORD FORMAT
-----------------
`%lld:<value>` per case, one line per case. `%lld` and not `%d` because a `%d`
conversion is 32 bits wide on this path
(`bugs/FORMAL_string_value_model.md` §2) — and every value here is a
STRING, so the point is the `\\n` in the value rather than the width, but the
width is the same trap `test_formal_small_hosts.py` records for
`io.DEFAULT_BUFFER_SIZE`. The value is bracketed `[...]` so an empty answer is
visible and a value containing the terminator cannot be confused with two
records.

A corpus byte cannot be spelled directly, so the MASK below is the corpus's own
alphabet and `unmask` is the Mojo half. It is the same idea as
`test_formal_json.py`'s and the two must agree — which is why the mask is
defined once, here, and used by both halves.
"""

import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
TEXTWRAP_MODULE = os.path.join(HOSTMODS, "textwrap.mojo")
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
# agree. Every corpus byte is ASCII, so the mask only has to carry the bytes a
# Mojo string literal cannot hold directly: a NUL cannot occur at all (a formal
# string is NUL-terminated), and the escapes are not decoded, so every
# non-printable byte and the two literal metacharacters go through here.

def mask(b: bytes) -> str:
    out = []
    for c in b:
        if c == 0x7E:
            out.append("~~")
        elif c == 0x40:
            out.append("~a")
        elif c == 0x09:
            out.append("~t")
        elif c == 0x0A:
            out.append("~n")
        elif c == 0x0B:
            out.append("~v")
        elif c == 0x0C:
            out.append("~f")
        elif c == 0x0D:
            out.append("~r")
        elif c == 0x1C:
            out.append("~c")          # FS
        elif c == 0x1D:
            out.append("~g")          # GS
        elif c == 0x1E:
            out.append("~e")          # RS
        elif c == 0x1F:
            out.append("~u")          # US
        elif c == 0x22:
            out.append("~q")
        elif c == 0x5C:
            out.append("~b")
        elif 0x20 <= c <= 0x7E:
            out.append(chr(c))
        else:
            out.append("~x%02x" % c)
    return "".join(out)


def mj(s: str) -> str:
    """A Mojo string literal for the already-masked `s`."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


UNMASK = '''
def unmask(t) -> str:
    var out: Pointer[UInt8] = malloc(4 * strlen(t) + 1)
    var u = 0
    var i = 0
    while i < strlen(t):
        var c = textwrap_dedent_byte(t, i)
        if c != 126:
            u = textwrap_put_byte(out, u, c)
            i = i + 1
        elif textwrap_dedent_byte(t, i + 1) == 126:
            u = textwrap_put_byte(out, u, 126)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 116:
            u = textwrap_put_byte(out, u, 9)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 110:
            u = textwrap_put_byte(out, u, 10)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 118:
            u = textwrap_put_byte(out, u, 11)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 102:
            u = textwrap_put_byte(out, u, 12)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 114:
            u = textwrap_put_byte(out, u, 13)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 99:
            u = textwrap_put_byte(out, u, 28)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 103:
            u = textwrap_put_byte(out, u, 29)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 101:
            u = textwrap_put_byte(out, u, 30)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 117:
            u = textwrap_put_byte(out, u, 31)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 113:
            u = textwrap_put_byte(out, u, 34)
            i = i + 2
        elif textwrap_dedent_byte(t, i + 1) == 98:
            u = textwrap_put_byte(out, u, 92)
            i = i + 2
        else:
            u = textwrap_put_byte(out, u, textwrap_hexdig(
                textwrap_dedent_byte(t, i + 2)) * 16
                + textwrap_hexdig(textwrap_dedent_byte(t, i + 3)))
            i = i + 4
    textwrap_put_byte(out, u, 0)
    return out
'''

HEXDIG = '''
def textwrap_hexdig(c) -> int:
    if c >= 48 and c <= 57:
        return c - 48
    if c >= 97 and c <= 102:
        return c - 87
    if c >= 65 and c <= 70:
        return c - 55
    return 0

def textwrap_dedent_byte(s, i) -> int:
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()

def textwrap_put_byte(dst, at, v) -> int:
    var p: Pointer[UInt8] = dst + at
    p.value() = v
    return at + 1
'''

PRELUDE = ("import textwrap\n\n" + UNMASK + "\n" + HEXDIG +
           "\ndef emit(k, v):\n"
           "    printf(\"%lld:[%s]" + REC + "\", k, v)\n")


# ── the corpora ────────────────────────────────────────────────────────────
#
# `dedent`'s, chosen so that each case separates one rule from another. The
# comment on each is the rule it pins, and `test_formal_textwrap.py`'s own
# docstring says why the mixed-indent cases are the point.

DEDENT_CASES = [
    # uniform indent: what every hand-written version gets right
    (b"  a\n   b\n", "uniform indent"),
    (b"\ta\n\t\tb\n", "uniform TAB indent"),
    (b"a\nb\n", "no indent at all"),
    # a blank line is REPLACED by the empty string, not trimmed
    (b"   \n  a\n   b\n", "leading whitespace line becomes empty"),
    (b"  a\n  b\n\n  c\n", "interior empty line"),
    (b"x\n \n  y\n", "interior whitespace-only line becomes empty"),
    (b" \n \n", "every line whitespace"),
    # degenerate shapes
    (b"", "empty string"),
    (b"\n", "a lone newline"),
    (b"\n\n  a\n", "two newlines then an indented line"),
    (b"  a  \n  b  ", "no trailing newline; trailing spaces KEPT"),
    (b"  a\nb\n", "one line indented, one not"),
    # the min/max pair: content differs after a COMMON indent
    (b"  abc\n  abd\n", "common indent, content differs"),
    (b"   a\n  b\n", "indents differ by one"),
    (b"  ab\n   ab\n", "same content, indents differ"),
    # tabs and spaces are not equal: the margin stops mid-run
    (b"  \ta\n \tb\n", "TAB vs SPACE at offset 1"),
    (b" \ta\n \tb\n", "margin 1, then TAB both sides"),
    (b"  a\n\tb\n", "SPACE line vs TAB line"),
    (b"\t a\n \ta\n", "TAB+SPACE vs SPACE+TAB"),
    # l2 shorter than l1's walk: `dedent("ab\\nabc\\n")` is unchanged
    (b"ab\nabc\n", "min is a prefix of max"),
    (b"abc\nab\n", "max is a prefix of min"),
    # `\\r` is CONTENT to dedent, not a boundary
    (b"  \r\n  a\n", "CR is inside the line, deleted with the margin"),
    (b"\ta\r\n\tb\r\n", "CR after a TAB indent"),
    # isspace() is true of 0x1C..0x1F and dedent REPLACES such lines
    (b"  \x1c\n  a\n", "0x1C line is whitespace: replaced"),
    (b"  \x1f\n  a\n", "0x1F line is whitespace: replaced"),
    (b"  \x1c\n  a\x1d\n", "0x1C line then a line ending 0x1D"),
    # a non-blank line shorter than the margin is emptied by the slice
    (b"    \n  ab\n", "whitespace line then a shorter non-blank line"),
    (b"      \n  ab\n", "margin 2, non-blank line of 4"),
]

# `indent`'s: the prefix goes BEFORE the terminator, and `splitlines` breaks
# where `split('\n')` does not.
INDENT_CASES = [
    (b"a\nb", "no trailing newline"),
    (b"a\nb\n", "trailing newline"),
    (b"a\n\nb", "interior empty line gets NO prefix"),
    (b"", "empty string"),
    (b"\n", "a lone newline: whitespace, no prefix"),
    (b"  \n", "whitespace line gets no prefix"),
    (b"a\n  b\n", "indented line gets a prefix"),
    # splitlines boundaries that are not newlines
    (b"a\rb", "CR breaks the line"),
    (b"a\r\nb", "CRLF is ONE boundary, prefix before it"),
    (b"a\x0bb", "VT breaks the line"),
    (b"a\x0cb", "FF breaks the line"),
    (b"a\x1cb", "0x1C breaks the line"),
    (b"a\x1eb", "0x1E breaks the line"),
    (b"a\x1fb", "0x1F does NOT break the line"),
    (b"  \x1fa  \n", "0x1F inside a whitespace line"),
    (b"a\r", "a trailing CR"),
    (b"a\n\r\nb", "LF then CRLF"),
    (b"\ra", "leading CR"),
    (b"a\r\rb", "two CRs"),
    (b"x\ny\r\nz\x0cw", "every boundary in one string"),
    # the metacharacters, so a mask bug shows here rather than nowhere
    (b'a"b\nc\\d', "quote and backslash"),
    (b"~~a\nb", "the tilde the mask escapes"),
]


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


def backends():
    """The architectures to build for, and why the list is not longer.

    BOTH, always: a module whose answers agree with CPython on arm64 and differ
    on x86-64 is a module that is half a mirror of CPython, and the two
    emitters are separately maintained lowerings of one AST
    (`gimple_codegen.py`'s and `myinterpreter.py`'s, which is why
    `CLAUDE.md` makes a compiled-path change owe a full gate). This module is
    pure string arithmetic over `memcpy`/`memcmp`/`strspn`, which is exactly the
    shape where a register-width difference shows up as a silently wrong answer
    rather than as a refusal.

    A host with no x86-64 support at all is the one case that cannot run half of
    this, and it is SKIPPED with the reason printed rather than passed over
    silently — `test_formal_os_backing.py` and `test_formal_json.py` do the
    same, and the reason is a fact about the machine rather than about the
    module.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def records(text):
    """`<index>:[<value>` records, as `(index, value)` pairs.

    Parsed by the LENGTH-independent route: the value is bracketed and the
    separator is two bytes a value cannot contain, because the mask escapes
    every `@` in the corpus as `~a`.
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


def compare(label, cases, got, want_fn):
    check(len(got) == len(cases),
          f"{label}: image reported {len(got)} of {len(cases)} cases; "
          f"excess: {got[len(cases):][:3]}")
    bad = []
    for idx, val in got:
        want = want_fn(cases[idx][0])
        if val != want:
            bad.append((idx, cases[idx][1], val, want))
    # The detail is built only when there IS a bad case: an f-string is an
    # argument, so it is evaluated before `check` runs, and `bad[0]` on an
    # empty list would raise IndexError on the very run that PASSES.
    detail = ""
    if bad:
        detail = (f"; first: idx={bad[0][0]} ({bad[0][1]}) image "
                  f"{bad[0][2]!r} CPython {bad[0][3]!r}")
    check(not bad,
          f"{label}: {len(bad)} of {len(cases)} case(s) differ from CPython"
          + detail)


def program(fn, arg, cases, name, backend=None):
    """The corpus as ONE program, run, and its records.

    One build for the whole corpus rather than one per case: the module is
    compiled once, so 28 cases cost one build, and a defect in the module is
    reported once with its message instead of 28 times as a timeout. The case
    INDEX is the record's index, so `compare`'s `cases[idx]` is the case that
    produced it.
    """
    lines = [PRELUDE, "def main():"]
    for k, (raw, _why) in enumerate(cases):
        lines.append(f"    var t{k} = unmask({mj(mask(raw))})")
        lines.append(f"    emit({k}, textwrap.{fn}(t{k}, {mj(mask(arg))}))"
                     if fn == "indent"
                     else f"    emit({k}, textwrap.{fn}(t{k}))")
    return records(run(build("\n".join(lines) + "\n", name, backend)))


# ── group: resolve ─────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import textwrap` finds this file, in the resolver's own order.

    And `textwrap` is out of `HOST_MODELLED`: that set is a CLAIM that the
    module could be written, and `formal/imports.py` says a name leaves it by
    being written, because an entry left behind would refuse a file AFTER the
    module that answers it is sitting in the tree — a false statement rather
    than a conservative one.
    """
    check(os.path.isfile(TEXTWRAP_MODULE),
          f"no Mojo source for textwrap at {TEXTWRAP_MODULE}")
    sys.path.insert(0, HERE)
    import formal.imports as I
    got = I.resolve_module_path("textwrap")
    check(got is not None and os.path.samefile(got, TEXTWRAP_MODULE),
          f"import textwrap resolves to {got!r}, not {TEXTWRAP_MODULE!r}")
    tier = I.host_module_tier("textwrap")
    check(tier == "",
          f"textwrap is still in HOST_MODELLED (tier={tier!r}); its Mojo "
          f"source exists, so the entry is now a false statement")
    check(I._HOSTMODS_ROOT == HOSTMODS,
          f"the hostmods root moved to {I._HOSTMODS_ROOT!r}")
    for stray in ("textwrap.mojo",):
        check(not os.path.isfile(os.path.join(HERE, stray)),
              f"{stray} is at the repository root, which four independent "
              f"resolvers search — see _HOSTMODS_ROOT")
    if verbose:
        print(f"    import textwrap -> {os.path.relpath(got, HERE)}, "
              f"host_module_tier={tier!r}")
    return True, f"resolves to {os.path.relpath(got, HERE)}, out of HOST_MODELLED"


# ── group: dedent ──────────────────────────────────────────────────────────

def group_dedent(tmpdir, verbose):
    """`dedent` over the corpus, each answer CPython's own, on BOTH backends."""
    import textwrap as CP
    for backend in backends():
        got = program("dedent", b"", DEDENT_CASES, "tw_dedent", backend)
        compare(f"dedent[{backend}]", DEDENT_CASES, got,
                lambda raw: CP.dedent(raw.decode("latin-1")))
    if verbose:
        print(f"    {len(DEDENT_CASES)} cases x {len(backends())} backends, "
              f"each against CPython's dedent")
    return True, (f"{len(DEDENT_CASES)} dedent answers agree with CPython "
                  f"on {len(backends())} backend(s)")


# ── group: indent ──────────────────────────────────────────────────────────

def group_indent(tmpdir, verbose):
    """`indent` over the corpus at three prefixes, each CPython's own, on BOTH.

    Three prefixes and not one because the empty prefix is the case where a
    module that always writes the separator looks right: with `prefix = ""` the
    answer is the input unchanged whenever the walk is correct, so a corpus run
    only at `""` cannot tell a correct `indent` from one that inserts nothing at
    all. The two non-empty prefixes then have to agree with each other, which
    is what pins the placement.
    """
    import textwrap as CP
    n = 0
    for backend in backends():
        for pref in (b">", b"    ", b""):
            got = program("indent", pref, INDENT_CASES,
                          f"tw_indent_{len(pref)}", backend)
            want = lambda raw: CP.indent(raw.decode("latin-1"),
                                         pref.decode("latin-1"))
            compare(f"indent[{backend}](prefix={pref!r})", INDENT_CASES,
                    got, want)
            n += len(INDENT_CASES)
    if verbose:
        print(f"    {len(INDENT_CASES)} cases x 3 prefixes x "
              f"{len(backends())} backends, each against CPython's indent")
    return True, (f"{n} indent answers agree with CPython "
                  f"({len(INDENT_CASES)} x 3 x {len(backends())})")


# ── group: boundary ────────────────────────────────────────────────────────

def group_boundary(tmpdir, verbose):
    """Every ASCII byte, asked which question it answers `True` to.

    `str.isspace()` and `str.splitlines` disagree about 0x1F, and both answers
    are OBSERVABLE through this module: a 0x1F line is whitespace (so `dedent`
    replaces it and `indent` gives it no prefix) and it is not a boundary (so
    both functions run through it). A module that used ONE byte set for both
    questions would answer 0x1F one way here and the other way in every case
    group, and this group is what says so at the byte level rather than by
    example.

    Two spellings of the question, because the module has two: `dedent` asks
    `isspace` about a whole line, `indent` asks it about a line INCLUDING its
    terminator. Both are computed here through the same module, which is why
    this is not a duplicate of the two case groups: it is the exhaustive sweep
    over the byte set, where those are the samples.
    """
    vals = [c for c in range(1, 128)]
    import textwrap as CP
    for backend in backends():
        parts = [PRELUDE, "def main():"]
        for idx, c in enumerate(vals):
            # The line is exactly this one byte, built as a `malloc`'d buffer
            # because that is what a decoded document is on this path and
            # because a string LITERAL is a read-only page (`p.value() = ...`
            # through one is refused by `formal/build.py`).
            #
            # `malloc` and the byte are SEPARATE statements on purpose:
            # `textwrap_put_byte` answers the new OFFSET, so folding the two
            # into one binding would name the offset and then hand `dedent`
            # the integer 1 as a `char *`. The first version of this group
            # did exactly that and every one of its 127 images died of
            # SIGSEGV, which is worth recording: a helper returning an int
            # and a helper returning a pointer are indistinguishable at a
            # call site, and the compiler cannot tell them apart either.
            parts.append(f"    var a{idx}: Pointer[UInt8] = malloc(2)")
            parts.append(f"    textwrap_put_byte(a{idx}, 0, {c})")
            parts.append(f"    textwrap_put_byte(a{idx}, 1, 0)")
            parts.append(f'    emit({2 * idx}, textwrap.dedent(a{idx}))')
            parts.append(f"    var b{idx}: Pointer[UInt8] = malloc(2)")
            parts.append(f"    textwrap_put_byte(b{idx}, 0, {c})")
            parts.append(f"    textwrap_put_byte(b{idx}, 1, 0)")
            parts.append(f'    emit({2 * idx + 1}, textwrap.indent(b{idx}, ">"))')
        recs = records(run(build("\n".join(parts) + "\n", "tw_boundary",
                                 backend)))
        check(len(recs) == 2 * len(vals),
              f"boundary sweep[{backend}] reported {len(recs)} of "
              f"{2 * len(vals)}")
        bad = []
        for idx, val in recs:
            c = vals[idx // 2]
            if idx % 2 == 0:
                want = CP.dedent(chr(c))
            else:
                want = CP.indent(chr(c), ">")
            if val != want:
                bad.append((c, val, want))
        detail = ""
        if bad:
            detail = (f"; first: 0x{bad[0][0]:02x} image {bad[0][1]!r} "
                      f"CPython {bad[0][2]!r}")
        check(not bad,
              f"{len(bad)} byte(s) differ from CPython on {backend}" + detail)
        if verbose:
            print(f"    [{backend}] {len(vals)} bytes x 2 spellings = "
                  f"{2 * len(vals)} answers")
    return True, (f"{2 * len(vals)} per-byte answers agree with CPython on "
                  f"{len(backends())} backend(s) (isspace and splitlines "
                  f"over bytes 1..127)")


# ── group: absent ──────────────────────────────────────────────────────────

def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused with a reason.

    Pinned because an absent name and a wrong answer look the same to a caller
    only if nothing checks, and because `wrap`/`fill` are exactly the two a
    reader would expect to find: they are the module's reason for existing in
    CPython. Each is refused NAMING ITSELF, so a caller that wants one is told
    which one and why rather than getting a link error.
    """
    for name in ("wrap", "fill", "shorten", "TextWrapper", "dedent_text"):
        src = (f"import textwrap\n\ndef main():\n"
               f"    printf(\"%lld\\n\", textwrap.{name}("
               f"'a', 3))\n")
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
              f"textwrap.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for textwrap.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    if verbose:
        print("    wrap, fill, shorten, TextWrapper each refused by name")
    return True, "4 absent names each refused, naming themselves"


GROUPS = {
    "resolve": group_resolve,
    "dedent": group_dedent,
    "indent": group_indent,
    "boundary": group_boundary,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS) + [],
                    default=[])
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    with tempfile.TemporaryDirectory(prefix="twtest") as td:
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
        print(f"\nformal textwrap: PASS={npass} FAIL={nfail}")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())