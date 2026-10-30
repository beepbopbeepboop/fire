#!/usr/bin/env python3
"""`formal/hostmods/textwrap.mojo`, differential against CPython's `textwrap`.

    python3 test_formal_textwrap.py [-v] [group ...]

Groups: `resolve`, `dedent`, `indent`, `surface`, `boundary`, `corpus`,
`absent`. With no argument, all. Every group but `resolve` and `corpus` builds
and RUNs an image on BOTH backends.

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
# string is NUL-terminated), and a byte outside printable ASCII cannot be SPELLED
# at all — `"a\nb"` in a Mojo source is three bytes, since `decoded_literal` runs
# inside `_intern_string` on both architectures, so the mask exists to make the
# corpus BYTES rather than to work around an undecoded literal.
#
# It is not redundant with a literal: it makes every corpus byte go through the
# SAME round trip, so a defect in the mask shows up as one failing corpus row
# rather than as a difference between two spellings. The `indent` case
# `quote and backslash` and `the tilde the mask escapes` are there to keep that
# honest, and `group_surface` runs the three real spellings this repository uses
# through a plain literal with no mask at all, so the two paths are checked
# against each other rather than one of them being assumed.

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

# The record carries the answer's LENGTH as well, and that length is computed BY
# THE IMAGE (`strlen` over its own answer) rather than supplied from here. That
# is not tidiness, it is the check: a value that got truncated in transport would
# otherwise compare unequal to CPython and be reported as a wrong ANSWER, which
# is a different bug with a different owner, and a value that grew would swallow
# the separator and re-align every record after it into a stream of right
# answers. `records` returns the length and every caller checks it against
# `len(want)`.
PRELUDE = ("import textwrap\n\n" + UNMASK + "\n" + HEXDIG +
           "\ndef emit(k, v):\n"
           "    printf(\"%lld:%lld:[%s]" + REC + "\", k, strlen(v), v)\n")


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
    """`<index>:<length>:[<value>` records, as `(index, length, value)`.

    Parsed by the LENGTH-independent route — the value is bracketed and the
    separator is two bytes a value cannot contain, because the mask escapes every
    `@` in the corpus as `~a` — and then the image's OWN `strlen` of the answer
    is returned beside it, for the reason `PRELUDE` gives.
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
        index, bar, length = head.partition(":")
        if not bar:
            raise Failure(f"record with no length: {rec!r}")
        got.append((int(index), int(length), val[:-1]))
    return got


def compare(label, cases, got, want_fn):
    check(len(got) == len(cases),
          f"{label}: image reported {len(got)} of {len(cases)} cases; "
          f"excess: {got[len(cases):][:3]}")
    bad = []
    for idx, length, val in got:
        want = want_fn(cases[idx][0])
        if val != want:
            bad.append((idx, cases[idx][1], val, want))
        elif length != len(val):
            bad.append((idx, cases[idx][1],
                        f"the record claims {length} bytes and carries "
                        f"{len(val)}", want))
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
        for idx, length, val in recs:
            c = vals[idx // 2]
            if idx % 2 == 0:
                want = CP.dedent(chr(c))
            else:
                want = CP.indent(chr(c), ">")
            if val != want:
                bad.append((c, val, want))
            elif length != len(val):
                bad.append((c, f"the record claims {length} bytes and carries "
                              f"{len(val)}", want))
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


# ── group: surface ──────────────────────────────────────────────────────────

# The two spellings this repository actually uses, at FULL SIZE and through a
# PLAIN LITERAL — no mask, no `unmask`.
#
# The three case groups above all carry their corpus through the mask, so every
# byte in them arrives by the same route and a defect in that route is one
# failing row. This group is the other direction: the argument shape the module
# exists for is a triple-quoted source literal handed straight to `dedent`, and
# that spelling goes through the decoder instead. Escapes rather than `~xHH` and
# rather than the unmask machinery, because the point is precisely that a Mojo
# literal decodes — `decoded_literal` runs inside `_intern_string` on both
# architectures — so escaping the corpus would test the mask twice.
# (label, the Mojo spelling written into the generated program, the same text as
# BYTES, the CPython function, and that function's extra arguments). The Mojo
# column is a real Mojo string literal with real escapes and the bytes column is
# what those escapes decode to, so the two columns are checked against each other
# by BEING the same text rather than by being transcribed consistently — a
# version that carried the expectation as an `eval`'d source string disagreed with
# the literal it was describing on every row containing a newline.
_SURFACE = [
    ("dedent", 'textwrap.dedent("    def f():\\n        return 1\\n")',
     b"    def f():\n        return 1\n", "dedent", ()),
    ("dedent-blank", 'textwrap.dedent("    a\\n\\n    b\\n")',
     b"    a\n\n    b\n", "dedent", ()),
    ("indent", 'textwrap.indent("a\\nb\\n", "    ")', b"a\nb\n", "indent",
     ("    ",)),
]


def group_surface(tmpdir, verbose):
    """The tree's real call shapes, through a plain Mojo literal, on both.

    Every other group masks its corpus. This one does not, and it is the only
    place the ESCAPE ROUND TRIP is exercised: a literal in the generated source
    has to decode to the same bytes CPython's string has, or the three rows here
    would answer about different text than the mask groups do.
    """
    import textwrap as CP
    for backend in backends():
        parts = [PRELUDE, "def main():"]
        for k, row in enumerate(_SURFACE):
            parts.append(f"    emit({k}, {row[1]})")
        recs = records(run(build("\n".join(parts) + "\n", "tw_surface",
                                 backend)))
        check(len(recs) == len(_SURFACE),
              f"surface[{backend}]: the image reported {len(recs)} of "
              f"{len(_SURFACE)}")
        bad = []
        for idx, length, val in recs:
            label, _mojo, raw, fn, extra = _SURFACE[idx]
            want = getattr(CP, fn)(raw.decode("latin-1"), *extra)
            if val != want:
                bad.append((label, val, want))
            elif length != len(val):
                bad.append((label, f"the record claims {length} and carries "
                            f"{len(val)}", want))
        check(not bad,
              f"surface[{backend}]: {len(bad)} of {len(_SURFACE)} spelling(s) "
              f"differ from CPython" + (f"; first: {bad[0]}" if bad else ""))
    if verbose:
        print(f"    {len(_SURFACE)} literal spellings x {len(backends())} "
              f"backends, through a plain literal with no mask")
    return True, (f"{len(_SURFACE)} literal spellings agree with CPython on "
                  f"{len(backends())} backend(s)")


# ── group: corpus ───────────────────────────────────────────────────────────

# The rows the module's whole design rests on, by BYTES rather than by a short
# name. A corpus row is cheap to delete and every deletion is a hole, because
# every row here is whitespace: two rows dropped in a diff are two rows that look
# identical. Keying on the bytes means the requirement cannot drift away from the
# corpus when a row is reworded, and it is why these are a SELECTION of
# `DEDENT_CASES` rather than a second corpus.
_REQUIRED_DEDENT = {
    b"  a\n\tb\n": "margin 0: a tab and a space are both whitespace and are "
                     "NOT equal, which is the only reason CPython takes a "
                     "lexicographic min/max instead of the minimum length. This "
                     "is THE discriminating row — see `group_corpus`",
    b"  \ta\n \tb\n": "the same rule with the tab one byte further in, so a "
                          "margin walk that stops at the first difference still "
                          "gets this one right by accident",
    b"  a\n   b\n": "the ordinary case, and the one a min-of-lengths would "
                     "also get RIGHT — so the corpus needs it beside the row it "
                     "gets wrong, or every row is adversarial and the suite "
                     "cannot tell a rule from an accident",
    b"\ta\n\t\tb\n": "the ordinary case again over TABs rather than spaces, "
                          "because a margin walk written against `' '` alone "
                          "passes every space row",
    b" \n \n": "no non-blank line at all, so the margin is 0 and a whitespace "
                "line contributes NOTHING — not even its terminator",
    b"   \n  a\n   b\n": "a blank line loses its width entirely, and it is "
                          "REPLACED rather than trimmed",
    b"  \r\n  a\n": "`dedent` splits on `\\n` and NOT on `splitlines`, so a "
                     "`\\r` is a character INSIDE a line and is deleted with the "
                     "margin",
    b"": "the empty string, where the min/max have no `default` to fall back on "
        "and the answer is `''`",
}


def _lead_ws_len(line):
    """How many leading space/tab bytes `line` has — a COUNT, not a remainder.

    Named for what it returns because the first version of this returned the
    remainder and the caller took `len()` of it, which is the length of the
    CONTENT (1 for `"  a"`) rather than the length of the INDENT (2) — so the
    "wrong rule" it was meant to compute answered exactly what CPython answers
    and the premise check below failed for a reason that had nothing to do with
    CPython. A helper whose name does not say which of the two it is, in a check
    that exists to catch a wrong answer, is how a check stops working.
    """
    i = 0
    while i < len(line) and line[i] in " \t":
        i += 1
    return i


def _min_margin_answer(text):
    """What the WRONG rule answers, so the corpus row has something to reject.

    CPython's `dedent` takes a lexicographic min/max of the non-blank lines and
    counts the ` `/`\\t` prefix the two extremes agree on. The rule that LOOKS
    equivalent and is not takes the MINIMUM of the leading-run lengths. This is
    that rule, spelled out, so the corpus row that discriminates them can be
    checked for still discriminating.

    Everything else is CPython's own structure — the join over `split('\\n')`,
    the whitespace-line-becomes-empty rule, the `default=0` margin — so the ONLY
    difference between the two functions is the margin. That is what makes the
    comparison mean "these two rules" rather than "these two programs": an
    earlier version of this helper rebuilt the join over the FILTERED lines, so
    it dropped blank lines instead of emptying them and disagreed with CPython on
    every corpus row that has one, which would have made the check pass for a
    reason that had nothing to do with the margin.
    """
    lines = text.split("\n")
    non_blank = [l for l in lines if l and not l.isspace()]
    margin = min((_lead_ws_len(l) for l in non_blank), default=0)
    return "\n".join(l[margin:] if not l.isspace() else "" for l in lines)


def group_corpus(tmpdir, verbose):
    """The corpus covers the rules the module's design rests on, and still does.

    Two failures, and the second is the one a corpus cannot catch by itself:

      * a DELETED row. Every `DEDENT_CASES` row is whitespace, so dropping the
        two that discriminate the margin rule leaves a model that takes the
        minimum leading-whitespace length passing every remaining row.
      * CPython CHANGING. If CPython's `dedent` ever agreed with the
        min-of-lengths rule on the discriminating row, that row would stop
        discriminating — and the module's docstring, which is entirely about the
        min/max pair, would be describing a rule that is no longer the
        difference. Asserted here so the two cannot drift apart silently.
    """
    present = {raw for raw, _why in DEDENT_CASES}
    missing = sorted(set(_REQUIRED_DEDENT) - present)
    check(not missing,
          "the dedent corpus is missing rows the module's design rests on:\n    "
          + "\n    ".join(f"{r!r} — {_REQUIRED_DEDENT[r]}" for r in missing))
    import textwrap as TW
    tab = b"  a\n\tb\n".decode("latin-1")
    check(TW.dedent(tab) != _min_margin_answer(tab),
          "CPython's dedent now agrees with the minimum-of-run-lengths rule on "
          "the tab-vs-space row, so this corpus row no longer discriminates and "
          "`formal/hostmods/textwrap.mojo`'s docstring is describing a rule "
          "that is no longer the difference")
    if verbose:
        print(f"    {len(_REQUIRED_DEDENT)} required rows present, and the "
              f"discriminating row still discriminates")
    return True, (f"all {len(_REQUIRED_DEDENT)} required rows present and the "
                  f"margin rule still discriminates")


GROUPS = {
    "resolve": group_resolve,
    "dedent": group_dedent,
    "indent": group_indent,
    "surface": group_surface,
    "boundary": group_boundary,
    "corpus": group_corpus,
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
