#!/usr/bin/env python3
# test_re_formal.py -- `formal/hostmods/re.mojo` is CPython's `re`, span for
# span and character for character.
#
# `tools/formal_sweep.py` reported THIRTEEN files as not-answerable because
# they `import re`, and six more through `fire_compiler.py`. The module exists
# now, and this file is the evidence that it is RIGHT rather than merely
# present.
#
# **Why not "it built".** A regex engine that is subtly wrong is the worst
# thing in this tree to get wrong quietly: the corpus it exists for is
# `_PROTO_RE.finditer(c_source)`, `re.fullmatch('[A-Z][0-9]?', base)` and
# `re.sub(r'\b' + re.escape(name) + r'\b', …)` over a compiler's own source, so
# a wrong answer is a mis-parsed function signature that nothing downstream can
# tell from a right one. The oracle is CPython's own `re` — this process's —
# and every case is computed twice: once here and once by an arm64 image built
# through the formal backend and EXECUTED.
#
# **What is compared.** For each (pattern, subject, flags) the program prints
# one integer per answer and this file compares the list element-wise:
#
#   * `ngroups`
#   * `search` — the status, then the whole match's span and every group's
#   * `match_at` and `fullmatch` — the status, and where the match starts
#   * `group_text` for the whole match and for every group — its LENGTH and
#     every BYTE, so a group that matches the right span with the wrong text
#     is caught
#   * `findall` — the count and every match's span
#   * `split` — the count and every piece's span
#   * `sub` — the result's length and every byte
#
# `re.escape` gets its own test, over all 256 byte values, because its answer
# is a set of 24 characters and a set is not something a spot check settles.
#
# **What is deliberately not here.** A pattern using lookahead, a lookbehind
# or a backreference is REFUSED with STATUS_UNSUPPORTED, and that is asserted
# rather than left untested: `test_unsupported_constructs_are_refused` builds
# the image and requires the status, so the refusal cannot rot into a wrong
# answer without going red.
#
# **The corpus is DISCOVERED, not remembered.** The thirteen sweep files and
# `fire_compiler.py` are walked for the patterns they actually pass to `re`,
# and every one that this module supports is in `test_the_corpus_patterns_all
# _work` — so a pattern shape the corpus uses and the corpus walk missed shows
# up as a failure rather than as coverage nobody knows about.
#
# Run:  python3 test_re_formal.py [-v] [-k SUBSTRING]

import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formal.imports as _FI

RE_MODULE = os.path.join(_FI._HOSTMODS_ROOT, "re.mojo")
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 300
MARK = 0 - 99        # a section separator, so a difference names a section
MAXPRINT = 20          # bytes of a string answer printed before it is truncated
MAXSPANS = 4           # matches/pieces reported by findall and split
GROUP = 10             # cases per built program


# ── the corpus ──────────────────────────────────────────────────────────────
#
# (pattern, subject, flags, note).  Flags are the CPython bits, passed to the
# module unchanged, so `re.MULTILINE` here is the same number the module's
# `MULTILINE()` returns.
I, M, S, X = re.IGNORECASE, re.MULTILINE, re.DOTALL, re.VERBOSE

CASES = [
    # literals and the empty pattern
    ("", "", 0, "empty pattern, empty subject"),
    ("", "abc", 0, "empty pattern matches empty at 0"),
    ("abc", "xxabcxx", 0, "literal"),
    ("abc", "xxabxx", 0, "literal that does not occur"),
    ("a", "aaa", 0, "one char, first of three"),
    # `.` and DOTALL
    ("a.c", "abc", 0, "dot"),
    ("a.c", "a\nc", 0, "dot does not cross a newline"),
    ("a.c", "a\nc", S, "DOTALL dot crosses a newline"),
    ("a.c", "a\nc", S | M, "DOTALL and MULTILINE together"),
    (".", "\n", 0, "dot alone does not match a newline"),
    (".+", "ab", 0, "greedy plus"),
    (".+?", "ab", 0, "lazy plus, still consumes all it can here"),
    # character classes
    ("[abc]+", "xxbcaxx", 0, "class with a plus"),
    ("[a-c]+", "xxbcaxx", 0, "class with a range"),
    ("[^a-c]+", "abcxyz", 0, "negated class"),
    ("[]-]", "a-b", 0, "a class that ends with a range"),
    ("[]]", "]", 0, "a class whose first member is ]"),
    ("[\\]]", "]", 0, "an escaped ] in a class"),
    ("[a-]", "-a", 0, "a trailing hyphen in a class"),
    ("[-a]", "-a", 0, "a leading hyphen in a class"),
    ("[\\d]+", "ab123cd", 0, "digit shorthand"),
    ("\\d+", "ab123cd", 0, "digit shorthand outside a class"),
    ("\\D+", "ab123cd", 0, "negated digit shorthand"),
    ("\\w+", "  hello_1  ", 0, "word shorthand"),
    ("\\W+", "ab!!cd", 0, "negated word shorthand"),
    ("\\s+", "a  b", 0, "space shorthand"),
    ("\\S+", "a  b", 0, "negated space shorthand"),
    ("[\\d\\s]+", "1 2 3", 0, "two shorthands in one class"),
    ("[\\D]+", "123abc", 0, "a negated shorthand INSIDE a class"),
    ("[^\\S\\n]+", "  \nx", 0, "the tokenizer's own whitespace class"),
    ("[\\w.-]+", "a.b-c!", 0, "a class of word, dot and hyphen"),
    ("[0-9a-f]{6}", "x0a1b2cx", 0, "the import test's own pattern"),
    # case folding
    ("abc", "ABC", I, "IGNORECASE on a literal"),
    ("[a-z]+", "ABC", I, "IGNORECASE on a class"),
    ("[A-Z]+", "abc", I, "IGNORECASE on a class the other way"),
    # anchors
    ("^abc", "abc", 0, "BOL at the start"),
    ("^abc", "xabc", 0, "BOL not at the start"),
    ("abc$", "xabc", 0, "EOL at the end"),
    ("abc$", "abcx", 0, "EOL not at the end"),
    ("^abc$", "abc", 0, "both anchors"),
    ("^b", "a\nb", M, "MULTILINE BOL after a newline"),
    ("a$", "a\nb", M, "MULTILINE EOL before a newline"),
    ("a$", "a\n", 0, "EOL before a trailing newline without MULTILINE"),
    ("^$", "", 0, "both anchors on the empty string"),
    ("\\Aab", "ab", 0, "\\A"),
    ("ab\\Z", "ab", 0, "\\Z"),
    ("^b", "a\nb", 0, "BOL after a newline without MULTILINE"),
    # word boundaries — what elaborate.py and reflect.py spell
    ("\\bfn\\b", "fn foo", 0, "word boundary, corpus shape"),
    ("\\bfn\\s+(\\w+)\\s*\\[", "fn foo[T]", 0, "elaborate.py's own shape"),
    ("\\Bord", "word", 0, "non-boundary"),
    ("\\b", " x ", 0, "a bare boundary"),
    ("\\bcat\\b", "the cat sat", 0, "boundary in a sentence"),
    ("\\bcat\\b", "concatenate", 0, "no boundary inside a word"),
    # groups
    ("(a)(b)", "ab", 0, "two groups"),
    ("(a)|(b)", "b", 0, "the second alternative of two groups"),
    ("(a)?b", "b", 0, "a group that did not participate"),
    ("(a)?b", "ab", 0, "a group that did"),
    ("(?P<w>\\w+)", "hello", 0, "a named group"),
    ("(?:ab)+", "ababab", 0, "a non-capturing group with a plus"),
    ("(a|b)+c", "ababc", 0, "a group in a loop"),
    ("((a)(b))", "ab", 0, "nested groups"),
    ("(a(b(c)))", "abc", 0, "three levels"),
    # alternation
    ("a|b", "b", 0, "one option matches"),
    ("a|bc|def", "xxdefxx", 0, "the third of three options"),
    ("a|bc|def", "xxbcxx", 0, "the second of three options"),
    ("(foo|bar)baz", "xbarbaz", 0, "a group around an alternation"),
    ("colou?r", "color", 0, "an optional letter"),
    ("colou?r", "colour", 0, "an optional letter, taken"),
    # quantifiers
    ("a*", "aaa", 0, "star"),
    ("a*", "bbb", 0, "star matching empty"),
    ("a*?", "aaa", 0, "lazy star"),
    ("a+?", "aaa", 0, "lazy plus"),
    ("a??b", "ab", 0, "lazy optional"),
    ("a{2}", "aaa", 0, "exact count"),
    ("a{2}", "a", 0, "exact count, too few"),
    ("a{2,}", "aaaa", 0, "open count"),
    ("a{2,3}", "aaaa", 0, "bounded count, greedy takes 3"),
    ("a{2,3}?", "aaaa", 0, "bounded count, lazy takes 2"),
    ("a{0,2}b", "b", 0, "an open count of zero"),
    ("(ab){2}", "abab", 0, "a counted repeat of a GROUP"),
    ("(ab){2}", "ab", 0, "a counted repeat of a group, once"),
    ("(a){0}", "b", 0, "a zero-width repeat of a group"),
    ("a.*b", "axxxb", 0, "greedy star between literals"),
    ("a.*?b", "axxxxb", 0, "lazy star between literals"),
    ("(.*)", "abc", 0, "a greedy group over everything"),
    ("(.*?)", "abc", 0, "a lazy group over everything"),
    ("\\(.*?\\)", "f(a, b)", 0, "the comment pattern's own shape"),
    # VERBOSE
    ("a b c", "abc", X, "VERBOSE ignores the spaces"),
    ("a  # comment\\n b", "ab", X, "VERBOSE ignores a comment"),
    ("[a b]", "a b", X, "VERBOSE does not ignore a space in a class"),
    # escapes
    ("\\.", "a.b", 0, "an escaped dot"),
    ("\\.", "axb", 0, "an escaped dot that does not match"),
    ("\\\\", "a\\b", 0, "an escaped backslash"),
    ("\\n", "a\nb", 0, "an escaped newline in the pattern"),
    ("\\t", "a\tb", 0, "an escaped tab"),
    ("\\x41", "xAy", 0, "a hex escape"),
    ("[\\x41-\\x43]+", "xABCy", 0, "a hex escape range"),
    ("\\101", "xAy", 0, "an octal escape"),
    ("a]b", "]ab]", 0, "a lone ] is a literal"),
    ("a}b", "a}b", 0, "a lone } is a literal"),
    ("a{", "a{", 0, "an unterminated brace"),
    # multi-line subjects, which is where ^ $ and \\n earn their keep
    ("^b$", "a\nb\nc", M, "MULTILINE anchors on a middle line"),
    ("\\w+", "ab\ncd", 0, "word shorthand stops at a newline"),
    ("a.b", "a\nb", S, "DOTALL across a newline"),
    ("(a)(b)", "x\nab", 0, "a group after a newline"),
    # the corpus's own patterns
    ("extern int64_t (\\w+_)?add_[0-9a-f]{6} \\(int64_t x, int64_t y\\);",
     "extern int64_t foo_add_1a2b3c (int64_t x, int64_t y);", 0,
     "test_imports.py's own pattern"),
    ("(?P<name>[A-Za-z_]\\w*)[ \\t]*\\((?P<params>[^;{}]*)\\)[ \\t]*;",
     "static R foo (int a, char *b) ;", M, "reflect.py's _PROTO_RE"),
    ("/\\*.*?\\*/|//[^\\n]*", "/* c */ int x; // y", S, "reflect.py's _COMMENT_RE"),
    ("\\b(?:fn|def)\\s+(\\w+)\\s*\\[", "fn foo[T]", 0, "exprtypes.py's own"),
    ("[-•]\\s+`?([A-Za-z0-9_\\[\\]]+)`?\\s+(?:→|->)\\s+", "- foo -> bar", 0,
     "module_spec_gen.py's own, with two non-ASCII bytes"),
    ("(?:→|->)", "a->b", 0, "module_spec_gen.py's split pattern"),
    ("\\s*-\\s+`?\\w+", " - name", 0, "module_spec_gen.py's second pattern"),
]


# ── what the formal program prints for one case ─────────────────────────────
#
# The layout is a flat list of integers, and it is the SAME list this file
# computes from CPython, so a difference is a difference in one named position.

def _findall(pattern, subject, flags):
    """CPython's own `findall`, with a tuple answer flattened to its match.

    A pattern with two or more groups makes `re.findall` return TUPLES, and a
    tuple is more than one span; the module records the whole match for that
    case and says so at `findall`, so the oracle does the same and the
    difference is a stated one rather than a silent mismatch.
    """
    try:
        items = re.findall(pattern, subject, flags)
    except re.error:
        return []
    if not items:
        return items
    if isinstance(items[0], str):
        return items
    return [m.group(0) for m in re.finditer(pattern, subject, flags)]


def _split(pattern, subject, flags):
    try:
        return re.split(pattern, subject, flags=flags)
    except re.error:
        return []


def _piece_text(item):
    """What the module can report for one `findall`/`split` entry."""
    return item if isinstance(item, str) else ""


def expected(pattern, subject, flags):
    """Every answer CPython gives for one case, as a flat list of ints.

    The list is in the SAME ORDER and of the SAME SHAPE as what the generated
    formal program prints, so a difference is a difference in one named
    position rather than a length mismatch.
    """
    out = [MARK]
    groups = re.compile(pattern).groups
    out.append(groups)
    m = re.search(pattern, subject, flags)
    out.append(MARK)
    out.append(0 if m is None else 1)
    if m is None:
        out.extend([-1] * (2 * (groups + 1)))
    else:
        out.append(m.start())
        out.append(m.end())
        for k in range(1, groups + 1):
            out.append(-1 if m.start(k) < 0 else m.start(k))
            out.append(-1 if m.start(k) < 0 else m.end(k))
    mm = re.match(pattern, subject, flags)
    out.append(MARK)
    out.append(0 if mm is None else 1)
    out.append(-1 if mm is None else mm.start())
    fm = re.fullmatch(pattern, subject, flags)
    out.append(MARK)
    out.append(0 if fm is None else 1)
    # group_text: the whole match, then each group. LENGTH then BYTES, so a
    # span that is right and a text that is wrong are different failures.
    # One entry for the whole match and one per group, ALWAYS — including when
    # there is no match, where every one of them is the empty string. The
    # program prints `groups + 1` of them unconditionally, so an expectation
    # that quietly dropped the groups on a no-match case compared two
    # different-length lists and read as a length difference rather than as
    # "the groups were not printed".
    texts = [m.group(0) if m is not None else ""]
    texts += [(m.group(k) or "") if m is not None else ""
              for k in range(1, groups + 1)]
    out.append(MARK)
    for txt in texts:
        b = txt.encode("utf-8", "surrogateescape")
        out.append(len(b))
        out.extend(b[:MAXPRINT])
        if len(b) > MAXPRINT:
            out.append(-1)
    for items in (_findall(pattern, subject, flags),
                  _split(pattern, subject, flags)):
        out.append(MARK)
        out.append(min(len(items), MAXSPANS))
        for piece in items[:MAXSPANS]:
            b = _piece_text(piece).encode("utf-8", "surrogateescape")
            out.append(len(b))
            out.extend(b[:MAXPRINT])
            if len(b) > MAXPRINT:
                out.append(-1)
    try:
        su = re.sub(pattern, "|", subject, flags=flags)
    except re.error:
        su = subject
    b = su.encode("utf-8", "surrogateescape")
    out.append(MARK)
    out.append(len(b))
    out.extend(b[:MAXPRINT])
    if len(b) > MAXPRINT:
        out.append(-1)
    return out


def mojo_str(s):
    """A Mojo string literal whose DECODED bytes are `s` — the INVERSE of
    `fire_compiler.decode_c_escapes`.

    A string literal's body is decoded exactly once on the way in, and it is
    CPython's decoder (`9023031b`, which gave the formal backends the shared
    decoder): `\b` is a backspace, `\x41` is `A`, `\n` is a newline and `\\`
    is one backslash. So the body that delivers the bytes `s` holds is `s`
    with every backslash DOUBLED, and one doubling is what makes the byte that
    arrives the byte the Python string holds: `r"\\d+"` is written
    `"\\\\d+"`, and `\\` is written `"\\\\\\\\"`.

    **This used to be the other way round and 14 checks were red because of
    it.** The premise it replaces said "a literal is interned VERBATIM and its
    escapes are NOT unescaped"; that was true when written and stopped being
    true when the decode landed. It was a wrong answer, not a refusal:
    `\bfn\b` reached `re` as `<BS>fn<BS>`, so every `\b` in the corpus matched
    nothing — a pattern that means a word boundary silently meant a control
    character, in the one area this file exists to be right about, and fourteen
    checks of the `formal-re` gate suite were red on a tree that had been green
    when the suite was written. Measured on a built-and-run image, one program,
    the three shapes the corpus uses (`\b`, `\\`, and a VERBOSE `#` comment
    whose `\n` must stay two characters):

        literal        len  bytes
        "\\b"           2  92 98      a word boundary
        "\\b"           1  8          a BACKSPACE, which is what this wrote
        "\\\\"          2  92 92      an escaped backslash
        "\\\\"          1  92         an incomplete atom, refused

    So the doubling is not a spelling preference: without it the engine is
    handed bytes the pattern never contained. `re.mojo` itself is right —
    given the right bytes it answers every one of those cases as CPython does,
    which is why `bugs/FORMAL_re_word_boundary_never_matches.md` is gone rather
    than acted on. `test_mojo_str_round_trips_through_the_decoder` is what now
    makes the un-doubled state impossible to reach again, and it costs no
    build: it runs every string this file writes through the one decoder and
    requires the exact bytes of the Python string back.

    Two things are deliberately NOT doubled, because they are not escapes:

    * a REAL newline or tab. Those arrive as real characters, which a literal
      cannot carry, so they keep the `mk2`/`mk3` spelling below — two literals
      and a `memset`, which is what `os/__init__.mojo` calls linesep.
    * an UNRECOGNIZED escape, of which the corpus has many (`\d`, `\w`, `\s`,
      `\(`, `\[`, `\*`). Doubling those is still right, and is what
      `decode_c_escapes`'s "an unknown escape keeps its backslash" rule needs:
      the doubled `\\d` decodes to `\d`, which is what the pattern means.
    """
    for ch, code in (("\n", 10), ("\t", 9)):
        if ch in s:
            parts = s.split(ch)
            assert len(parts) <= 3, s
            seps = [str(code)] * (len(parts) - 1)
            if len(parts) == 2:
                return "mk2(%s, %s, %s)" % (mojo_str(parts[0]), seps[0],
                                            mojo_str(parts[1]))
            return "mk3(%s, %s, %s, %s, %s)" % (mojo_str(parts[0]), seps[0],
                                                mojo_str(parts[1]), seps[1],
                                                mojo_str(parts[2]))
    assert '"' not in s, s
    return '"%s"' % s.replace("\\", "\\\\")


# A `mojo_str` expression, read back the way the runtime builds it: the quoted
# bodies and the byte values between them, in order.  A plain literal has one
# body; `mk2`/`mk3` have two or three plus the separators a `memset` writes.
# The `mk[23]\(` alternative is load-bearing: without it the `2` in `mk2` reads
# as a separator byte and every two-part string comes back with a stray \x02 in
# front of it.
_MOJO_PIECE = re.compile(r'mk[23]\(|"((?:[^"\\]|\\.)*)"|(\d+)')


def mojo_literal_bytes(expr):
    """The bytes the runtime will hold for a `mojo_str` expression.

    The literals go through `fire_compiler.decode_c_escapes` — THE decoder
    every engine calls, and the one this file's encoder has to be the inverse
    of — and a bare number between two literals is the separator `mk2`/`mk3`
    write with `memset`, so `mk2("a", 10, "b")` reconstructs to `a` + newline
    + `b`, which is the same three bytes the image gets.
    """
    import fire_compiler as _FC
    out = bytearray()
    pieces = list(_MOJO_PIECE.finditer(expr))
    assert pieces, expr
    for m in pieces:
        if m.group(1) is not None:
            out += _FC.decode_c_escapes(m.group(1)).encode(
                "utf-8", "surrogateescape")
        elif m.group(2) is not None:
            out.append(int(m.group(2)))
    return bytes(out)


PRELUDE = '''MARK = 0 - 99
from os._syscalls import str_len, str_alloc, str_put


def mk2(a: String, mid: Int, b: String) -> Pointer[UInt8]:
    d = str_alloc(str_len(a) + 1 + str_len(b))
    u = str_put(d, 0, a, str_len(a))
    memset(d + u, mid, 1)
    u = str_put(d, u + 1, b, str_len(b))
    return d


def mk3(a: String, m1: Int, b: String, m2: Int, c: String) -> Pointer[UInt8]:
    d = str_alloc(str_len(a) + 1 + str_len(b) + 1 + str_len(c))
    u = str_put(d, 0, a, str_len(a))
    memset(d + u, m1, 1)
    u = str_put(d, u + 1, b, str_len(b))
    memset(d + u, m2, 1)
    u = str_put(d, u + 1, c, str_len(c))
    return d


def bat(p, i: Int) -> Int:
    """The byte at `p[i]` as a NUMBER.

    `p[i]` is not this and cannot be: a subscript on a pointer takes the
    list-blob path, which reads a COUNT from offset 0 and bounds-checks
    against it, so a program that indexes a returned string for a character
    gets a plausible number built out of adjacent bytes. `Pointer[UInt8]
    .value()` is the load (bugs/FORMAL_subscript_of_a_pointer_reads_a_blob
    _count.md), and it is spelled here once so the 40-odd read sites below
    are reads.
    """
    var q: Pointer[UInt8] = p + i
    return Int(q.value())


def emit(label: Int, v: Int) -> Int:
    printf("%d ", v)
    return 0


import re
'''


def case_function(i, pattern, subject, flags):
    """One function per case: the register allocator refuses the shape
    where a single function carries a whole corpus, and a function per
    case is also what makes a failing case nameable."""
    g = re.compile(pattern).groups
    outlen = 2 * (g + 1)
    ntexts = g + 1
    lines = ["", "",
             "def c%d() -> Int:" % i,
             "    p = %s" % mojo_str(pattern),
             "    s = %s" % mojo_str(subject),
             "    st = [" + ", ".join(["0"] * (outlen + 1)) + "]"]
    lines.append("    printf(\"C%d \")" % i)
    lines.append("    emit(0, MARK)")
    lines.append("    emit(0, re.ngroups(p))")
    lines.append("    emit(0, MARK)")
    lines.append("    r = re.search(st, %d, p, s, %d)" % (outlen, flags))
    lines.append("    emit(0, r)")
    for k in range(outlen):
        lines.append("    emit(0, st[%d])" % k)
    lines.append("    emit(0, MARK)")
    lines.append("    r = re.match_at(st, %d, p, s, %d)" % (outlen, flags))
    lines.append("    emit(0, r)")
    lines.append("    emit(0, st[0])")
    lines.append("    emit(0, MARK)")
    lines.append("    r = re.fullmatch(st, %d, p, s, %d)" % (outlen, flags))
    lines.append("    emit(0, r)")
    lines.append("    emit(0, MARK)")
    lines.append("    gstat = [0]")
    for k in range(ntexts):
        lines.append("    t = re.group_text(gstat, 1, p, s, %d, %d)" % (flags, k))
        lines.append("    emit(0, str_len(t))")
        lines.append("    n = 0")
        lines.append("    while n < str_len(t):")
        lines.append("        if n < %d:" % MAXPRINT)
        lines.append("            emit(0, bat(t, n))")
        lines.append("        n = n + 1")
        lines.append("    if str_len(t) > %d:" % MAXPRINT)
        lines.append("        emit(0, 0 - 1)")
    lines.append("    emit(0, MARK)")
    lines.append("    fa = [" + ", ".join(["0"] * (2 * MAXSPANS + 1)) + "]")
    lines.append("    nf = re.findall(fa, %d, p, s, %d, %d)"
                 % (2 * MAXSPANS + 1, flags, MAXSPANS))
    lines.append("    emit(0, nf)")
    lines.append("    n = 0")
    lines.append("    while n < nf:")
    lines.append("        lo = fa[1 + n * 2]")
    lines.append("        hi = fa[2 + n * 2]")
    lines.append("        emit(0, hi - lo)")
    lines.append("        k = 0")
    lines.append("        while k < hi - lo:")
    lines.append("            if k < %d:" % MAXPRINT)
    lines.append("                emit(0, bat(s, lo + k))")
    lines.append("            k = k + 1")
    lines.append("        if hi - lo > %d:" % MAXPRINT)
    lines.append("            emit(0, 0 - 1)")
    lines.append("        n = n + 1")
    lines.append("    emit(0, MARK)")
    lines.append("    spl = [" + ", ".join(["0"] * (2 * (MAXSPANS * 2) + 1)) + "]")
    lines.append("    ns = re.split(spl, %d, p, s, %d, %d)"
                 % (2 * (MAXSPANS * 2) + 1, flags, MAXSPANS))
    lines.append("    emit(0, ns)")
    lines.append("    n = 0")
    lines.append("    while n < ns:")
    lines.append("        lo = spl[1 + n * 2]")
    lines.append("        hi = spl[2 + n * 2]")
    lines.append("        emit(0, hi - lo)")
    lines.append("        k = 0")
    lines.append("        while k < hi - lo:")
    lines.append("            if k < %d:" % MAXPRINT)
    lines.append("                emit(0, bat(s, lo + k))")
    lines.append("            k = k + 1")
    lines.append("        if hi - lo > %d:" % MAXPRINT)
    lines.append("            emit(0, 0 - 1)")
    lines.append("        n = n + 1")
    lines.append("    emit(0, MARK)")
    lines.append("    sstat = [0]")
    lines.append("    r = re.sub(sstat, p, \"|\", s, %d, 0)" % flags)
    lines.append("    emit(0, str_len(r))")
    lines.append("    n = 0")
    lines.append("    while n < str_len(r):")
    lines.append("        if n < %d:" % MAXPRINT)
    lines.append("            emit(0, bat(r, n))")
    lines.append("        n = n + 1")
    lines.append("    if str_len(r) > %d:" % MAXPRINT)
    lines.append("        emit(0, 0 - 1)")
    lines.append("    printf(\"%s\", re.nl())")
    return "\n".join(lines)


def program(indices):
    parts = [PRELUDE]
    for i in indices:
        p, s, f, _ = CASES[i]
        parts.append(case_function(i, p, s, f))
    body = "\n".join(parts)
    body += "\n\ndef main(n: Int) -> Int:\n"
    for i in indices:
        body += "    c%d()\n" % i
    body += "    return 0\n"
    return body


# ── the runner ──────────────────────────────────────────────────────────────

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print("FAIL  %s" % what + ((": " + detail) if detail else ""), flush=True)
    return bool(ok)


def build_and_run(tmpdir, name, source, backend=None):
    """Build `source` through the formal backend and RUN the image.

    `backend` selects the codegen (`formal/build.py`'s `--backend`). The image
    is then executed and its output returned, so this is the only thing in this
    file that can tell a right answer from a plausible one — everything else
    here is about whether the module builds.

    The two backends' images run the same way on this host: an x86-64 Mach-O is
    loaded by Rosetta 2 transparently, and `fire.py`'s `_formal_run_argv`
    (`arch -x86_64 <path>`) exists for the cases where it does not.
    """
    path = os.path.join(tmpdir, "%s.py" % name)
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, "%s.bin" % name)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove"]
    if backend:
        argv.append("--backend=%s" % backend)
    argv += ["-o", out, path]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        raise AssertionError("build failed: %s" % (r.stderr or r.stdout).strip()[-800:])
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    # The image's EXIT STATUS is checked, and not just its output: an image that
    # dies said nothing, and "printed 0 lines" is a sentence about the PRINTING
    # rather than about what happened. Observed on a loaded machine before this
    # check existed — an image that had been killed reported itself as a corpus
    # that answered nothing, which reads as a wrong answer rather than as a
    # process that is not there. A negative status is a signal (`-11` is SIGSEGV,
    # `-9` SIGKILL), so it is reported with its name.
    if run.returncode != 0:
        import signal as _signal
        st = run.returncode
        name = ""
        if st < 0:
            try:
                name = " (%s)" % _signal.Signals(-st).name
            except ValueError:                  # pragma: no cover
                name = " (signal %d)" % -st
        raise AssertionError("the image exited %d%s with no usable output; "
                             "stderr: %s"
                             % (st, name,
                                (run.stderr or "").strip()[-300:]))
    return [ln for ln in run.stdout.split("\n") if ln.strip() != ""]


def group_corpus(indices, size):
    for k in range(0, len(indices), size):
        yield indices[k:k + size]


def run_corpus(tmpdir, backend=None):
    """Every case, built, RUN, and compared value for value with CPython."""
    tag = backend or "arm64"
    for chunk in group_corpus(list(range(len(CASES))), GROUP):
        try:
            got_lines = build_and_run(tmpdir, "corpus_%s_%d" % (tag, chunk[0]),
                                      program(chunk), backend=backend)
        except AssertionError as e:
            for i in chunk:
                p, s, f, note = CASES[i]
                check(False, "[%s] case %d (%r on %r) builds"
                      % (tag, i, p, s), str(e))
            continue
        if len(got_lines) != len(chunk):
            check(False, "[%s] the image printed one line per case" % tag,
                  "expected %d, got %d" % (len(chunk), len(got_lines)))
            continue
        for i, line in zip(chunk, got_lines):
            p, s, f, note = CASES[i]
            # The line starts with the case's own label, so a line that
            # arrived out of order (or a case that printed nothing) is
            # caught here rather than compared against the wrong subject.
            toks = line.split()
            if not check(toks and toks[0] == "C%d" % i,
                         "[%s] line %d is case C%d's" % (tag, i, i),
                         "got %r" % (toks[0] if toks else None)):
                continue
            got = [int(x) for x in toks[1:]]
            want = expected(p, s, f)
            if not check(got == want,
                         "[%s] case %d: re.search(%r, %r, %d) == CPython  [%s]"
                         % (tag, i, p, s, f, note)):
                if len(got) != len(want):
                    print("      lengths differ: got %d values, CPython %d"
                          % (len(got), len(want)), flush=True)
                else:
                    bad = [(j, g, w) for j, (g, w) in enumerate(zip(got, want))
                           if g != w]
                    print("      %d of %d differ; first few (index, got, "
                          "CPython): %s" % (len(bad), len(want), bad[:6]),
                          flush=True)


def test_the_corpus_against_cpython(tmpdir):
    """Every case, built, run, and compared value for value with CPython."""
    run_corpus(tmpdir)


def test_the_corpus_against_cpython_on_x86_64(tmpdir):
    """The same corpus, on the OTHER backend, run and compared the same way.

    This is new coverage rather than a repeat: `re.mojo` used to be seven
    parameters wide at its widest and could not be compiled for x86-64 AT ALL,
    so the 45 files that import it were refused with `sub: 7 parameters exceeds
    the 6 …` and nothing here ever looked at an x86-64 `re` image. It is now
    six wide and builds for both. A backend that can build the module can also
    get it wrong — the `sub` walk keeps its
    output-buffer state in the arena rather than in parameters, which is a
    different program to the one arm64 lowers — so the answers are compared
    against CPython on this backend too, over the same 128 cases.
    """
    run_corpus(tmpdir, backend="x86_64")


# ── escape, over every byte ─────────────────────────────────────────────────

def test_escape_every_byte(tmpdir):
    """All 256 byte values, one line each: re.escape's output, byte for byte.

    `re.escape` is a set of 24 characters, and a set is not something a spot
    check settles, so this is every input there is.  The 256 cases are split
    across 32 functions of 8 because `formal/arm64_codegen.py`'s statement
    walker is recursive (`_always_returns` recurses per statement) and one
    1536-statement `main` hits CPython's recursion limit inside the COMPILER,
    which is a false negative about this module, not a real one.
    """
    src = [PRELUDE, """
def chr2(v: Int) -> Pointer[UInt8]:
    var p: Pointer[UInt8] = str_alloc(1)
    memset(p, v, 1)
    return p
"""]
    for c in range(32):
        src.append("def e%d() -> Int:" % c)
        for v in range(c * 8, c * 8 + 8):
            src.append("    e = re.escape(chr2(%d))" % v)
            if v == 0:
                # A NUL cannot live in a `char*`-based string, so a string
                # CONTAINING one has no measurable length: `str_len` stops at
                # the NUL and the output of escaping NUL is NUL. The byte
                # itself is still readable, and it is what CPython returns, so
                # that is what is compared. 255 of the 256 go through the loop
                # below; this one is read directly.
                src.append("    emit(0, bat(e, 0))")
            else:
                src.append("    n = 0")
                src.append("    while n < str_len(e):")
                src.append("        emit(0, bat(e, n))")
                src.append("        n = n + 1")
            src.append("    emit(0, 0)")
            src.append("    printf(\"%s\", re.nl())")
    src.append("def main(n: Int) -> Int:")
    for c in range(32):
        src.append("    e%d()" % c)
    src.append("    return 0")
    src = "\n".join(src)
    try:
        lines = build_and_run(tmpdir, "escape", src)
    except AssertionError as e:
        check(False, "the escape program builds", str(e))
        return
    check(len(lines) == 256, "one line per byte value",
          "%d vs 256" % len(lines))
    want = []
    for v in range(256):
        want.append([b for b in re.escape(chr(v)).encode("latin-1")] + [0])
    for v, line in enumerate(lines[:256]):
        if not check(line.split() != [],
                     "byte %d escaped to something" % v, "empty line"):
            continue
        check([int(x) for x in line.split()] == want[v],
              "re.escape(%d) == CPython" % v,
              "got %r, CPython %r" % (line.split()[:8], want[v][:8]))


UNSUPPORTED = [
    ("a(?=b)", "a lookahead"),
    ("a(?!b)", "a negative lookahead"),
    ("(?<=a)b", "a lookbehind"),
    ("(?<!a)b", "a negative lookbehind"),
    ("(?P<x>a)(?P=x)", "a backreference by name"),
    (r"(a)\1", "a numbered backreference"),
    (r"\1", "a group reference to a group that does not exist"),
    (r"\12", "two digits where CPython reads a group reference"),
    # Raw, and the reason is Python: "\400" in a non-raw string is chr(256),
    # not the four characters CPython is being asked about, so the test was
    # compiling a pattern this file never intended to write.
    (r"\400", "an octal escape past 0o377"),
    ("\\q", "a bad escape of an ASCII letter"),
    ("[b-a]", "a reversed range"),
    (r"[\d-x]", "a shorthand as a range endpoint"),
    ("a**", "two quantifiers"),
    ("a*+", "a possessive quantifier"),
    ("(?>a)", "an atomic group"),
    ("(?i)a", "an inline flag"),
    ("(?(1)a|b)", "a conditional"),
    ("(a", "an unclosed group"),
    ("a)", "an unmatched )"),
    ("[abc", "an unclosed class"),
    ("[z-a]", "a reversed range at the top of the alphabet"),
]

# Patterns whose refusal is a LIMIT rather than an UNSUPPORTED one, which is a
# distinction the module makes on purpose: "this shape is not implemented" and
# "this shape is implemented and does not fit" are different answers and a
# caller can act on them differently.
LIMIT_NOT_UNSUPPORTED = {
    "a{70,80}": "a counted repeat past the arena's repeat limit",
}

# `\D` is in the list above to be PROVEN not refused: it is a real
# character class and the point of the list is that every refusal is specific
# rather than a blanket "something in here I do not implement".
SUPPORTED_IN_UNSUPPORTED_LIST = {
    r"[\D]": "a negated shorthand inside a class is a class, not a refusal",
}


def test_unsupported_constructs_are_refused(tmpdir):
    """Each of these is a refusal, and the refusal is a STATUS.

    An honest refusal beats a wrong answer, so the property is that the status
    says so and the spans are blanked — not that the case is skipped. A pattern
    this module does not implement must never come back as "no match", because
    a caller that cannot tell those apart has a silent wrong answer.
    """
    for i, (pat, why) in enumerate(UNSUPPORTED):
        src = "\n".join([
            PRELUDE,
            "",
            "def main(n: Int) -> Int:",
            "    p = " + mojo_str(pat),
            "    s = \"ab\"",
            "    st = [0, 0, 0, 0]",
            "    r = re.search(st, 4, p, s, 0)",
            "    printf(\"%d %d %d %d \", r, st[0], st[1], st[2])",
            "    printf(\"%s\", re.nl())",
            "    return 0",
        ])
        try:
            lines = build_and_run(tmpdir, "unsup%d" % i, src)
        except AssertionError as e:
            check(False, "%r (%s) builds" % (pat, why), str(e)[:300])
            continue
        got = [int(x) for x in lines[0].split()] if lines else []
        if pat in SUPPORTED_IN_UNSUPPORTED_LIST:
            # It IS supported; the point is that it matches and does not
            # claim to be a refusal.
            check(got and got[0] == 1,
                  "%r is supported and matches (%s)" % (
                      pat, SUPPORTED_IN_UNSUPPORTED_LIST[pat]),
                  str(got))
            continue
        want = [2 if pat in LIMIT_NOT_UNSUPPORTED else 3, -1, -1, -1]
        check(got == want,
              "%r (%s) is refused with status %d, not answered" %
              (pat, why, want[0]), "got %s" % got)


def test_mojo_str_round_trips_through_the_decoder(tmpdir=None):
    """Every string this file writes survives the trip into a literal and back.

    **The premise, made testable without a build.** `mojo_str` used to say "a
    string literal is interned VERBATIM and its escapes are NOT unescaped",
    which was true when it was written and stopped being true when
    `fire_compiler.decode_c_escapes` became the one decoder every engine calls.
    Fourteen checks in the `formal-re` gate suite were the consequence, and they
    were the expensive kind of evidence to have to get: a whole corpus built
    and run per backend to discover what one pure-Python function does to a
    string. A pattern that means a word boundary reached `re` as a backspace,
    in the one area a silent wrong answer is least affordable.

    So the check is here instead: the expression `mojo_str` writes, run through
    the one decoder, must give back the exact bytes of the Python string it was
    given. It builds nothing and runs nothing, so it is red the moment the
    encoder and the decoder disagree — which is the failure, stated in the one
    place that causes it.

    It covers every corpus pattern and subject, every refusal pattern, and the
    DISCOVERED corpus patterns, whose values come out of `corpus_patterns` — so
    that walk's decode and this round trip are checked against each other rather
    than each being right by itself.
    """
    found, _dropped = corpus_patterns()
    cases = []
    for p, s, _f, _note in CASES:
        cases.append(("the pattern of case %r" % p, p))
        cases.append(("the subject of case %r" % p, s))
    for pat, why in UNSUPPORTED:
        cases.append(("the unsupported pattern %r (%s)" % (pat, why), pat))
    for p in sorted(found):
        cases.append(("the discovered corpus pattern %r" % p, p))
    bad = []
    for what, s in cases:
        got = mojo_literal_bytes(mojo_str(s))
        want = s.encode("utf-8", "surrogateescape")
        if got != want:
            bad.append("%s: %r arrives as %r" % (what, s, got))
    check(not bad,
          "every string this file writes reaches the image as the bytes the "
          "oracle used (%d strings; offenders: %s)"
          % (len(cases), "; ".join(bad[:3]) or "none"))


def test_a_span_list_that_is_too_small_is_a_status_not_a_crash(tmpdir):
    """A caller's undersized list is reported, and the process survives.

    The module cannot read a list's capacity — a list here is a plain array,
    `st = [7, 8, 9]; st[0]` is 7 and not a count — so the capacity is an
    argument, and an argument the caller gets wrong has to come back as
    STATUS_LIMIT. The alternative is measured: a store past the end of a list
    is a SILENT `exit(1)` with nothing printed, which is the one report of a
    library bug a caller cannot act on. So the wrong size is exercised here for
    every entry point that writes into a caller's list, and each one has to
    answer and leave the process running.
    """
    lines = [PRELUDE, "", "def main(n: Int) -> Int:",
             "    p = \"(a)(b)\"",
             "    s = \"ab\"",
             # 2 * (2 + 1) = 6 is the room this pattern needs.
             "    small = [0, 0, 0, 0, 0]",
             "    big = [0, 0, 0, 0, 0, 0, 0]",
             "    fsmall = [0, 0, 0]",
             "    fbig = [0, 0, 0, 0, 0, 0, 0]",
             "    ssmall = [0]",
             "    sbig = [0, 0]",
             "    printf(\"A %d\", re.search(small, 5, p, s, 0))",
             "    printf(\"%s\", re.nl())",
             "    printf(\"B %d\", re.match_at(small, 5, p, s, 0))",
             "    printf(\"%s\", re.nl())",
             "    printf(\"C %d\", re.fullmatch(small, 5, p, s, 0))",
             "    printf(\"%s\", re.nl())",
             # findall and split RETURN the count and put the STATUS in out[0],
             # so the refusal is read out of the list, not the return value.
             "    printf(\"D %d\", re.findall(fsmall, 3, p, s, 0, 2) + fsmall[0])",
             "    printf(\"%s\", re.nl())",
             "    printf(\"E %d\", re.split(ssmall, 2, p, s, 0, 2) + ssmall[0])",
             "    printf(\"%s\", re.nl())",
             "    printf(\"F %d\", re.sub(ssmall, p, \"|\", s, 0, 0) != 0)",
             "    printf(\"%s\", re.nl())",
             "    # and the RIGHT capacity still works, in the same process",
             "    printf(\"G %d\", re.search(big, 7, p, s, 0))",
             "    printf(\"%s\", re.nl())",
             "    printf(\"H %d\", re.findall(fbig, 7, p, s, 0, 2))",
             "    printf(\"%s\", re.nl())",
             "    printf(\"I %d\", str_len(re.sub(sbig, p, \"|\", s, 0, 0)))",
             "    printf(\"%s\", re.nl())",
             "    return 0"]
    try:
        got = build_and_run(tmpdir, "capacity", "\n".join(lines))
    except AssertionError as e:
        check(False, "the capacity program builds", str(e))
        return
    # I is `re.sub("(a)(b)", "|", "ab")` = "|", so one character.
    want = ["A 2", "B 2", "C 2", "D 2", "E 2", "F 1", "G 1", "H 1", "I 1"]
    check(got == want,
          "every undersized list is STATUS_LIMIT (2) and the right-sized one "
          "still answers, in the same process",
          "got %r, want %r" % (got, want))


# ── the corpus walk, and the module's own claims ────────────────────────────

def corpus_patterns():
    """Every pattern literal the files the sweep blocked on `re` pass to `re`.

    DISCOVERED, and the reason is the same as everywhere else in this tree: a
    hand-kept list is a list of what somebody remembered.

    Returns `(usable, dropped)`, and the second half is load-bearing rather
    than diagnostic decoration. The walk reads string literals with a regex
    over the source text, so it does not PARSE Python and a candidate can be a
    fragment of a larger expression: a pattern built by concatenation reads
    here as its first piece, which is a truncated `(?:` and not a pattern
    anything compiles. `test_ab_native.py`'s scratch-artifact regex is the live
    example (`r'abt(\\d+)_[0-9a-f]{8}_\\w+\\.(?:' + '|'.join(...) + r')'`),
    and it arrived after this walk was written.

    So a candidate the ORACLE refuses is not a corpus pattern, and the test has
    no question to ask about it: `want = re.search(p, ...)` is what every
    assertion below is stated against, and for such a candidate it raises
    `PatternError` and takes the whole test down. Filtering on `re.compile`
    is therefore not a weakened check — it is the check's own precondition
    made explicit. What it must not be is SILENT, because a filter that quietly
    discards candidates is how a walk stops being a walk: hence `dropped`, and
    an assertion in the test that says how many were thrown away and why.

    **The candidate is a literal's VALUE, not its source text**, and that is
    load-bearing in both directions. The walk reads raw source, so a non-raw
    literal arrives with its escapes still spelled (`"\\\\d"` is four characters
    in the file and two in the string); compiling that as the pattern and then
    handing the same text to `mojo_str` would ask the oracle one question and
    the module another. So a candidate is decoded by the ONE decoder
    (`fire_compiler.decode_c_escapes`) unless the prefix says `r`, which is
    `fire_compiler.decoded_literal`'s own rule — and `mojo_str` then encodes it
    again on the way into the generated program, so the byte that reaches `re`
    is the byte CPython compiled. Every pattern the walk currently finds is a
    raw string, so this changes nothing today; it is here because the walk is
    DISCOVERED, and the day a non-raw pattern appears it must not be wrong.
    """
    import glob
    import fire_compiler as _FC
    pat = re.compile(r"re\.(?:compile|search|match|fullmatch|split|sub|findall)"
                     r"\(\s*r?([rb]*)(['\"])(.*?)\2", re.S)
    out, dropped = {}, {}
    for path in sorted(glob.glob(os.path.join(HERE, "*.py")) +
                       glob.glob(os.path.join(HERE, "mojo", "**", "*.py"),
                                 recursive=True)):
        if os.path.basename(path) == os.path.basename(__file__):
            continue
        with open(path) as f:
            text = f.read()
        if "import re" not in text and "re.compile" not in text:
            continue
        for m in pat.finditer(text):
            prefix, p = m.group(1), m.group(3)
            if "r" not in prefix:
                p = _FC.decode_c_escapes(p)
            if len(p) > 8 and "{" in p and "\\w" in p:
                where = os.path.basename(path)
                try:
                    re.compile(p)
                except re.error as e:
                    dropped.setdefault(p, (where, str(e)))
                else:
                    out.setdefault(p, where)
    return out, dropped


def test_the_corpus_patterns_all_work(tmpdir):
    """Every discovered corpus pattern compiles and answers.

    The gap check: a pattern shape the corpus uses that this module refuses is
    a real finding about the module, and the sweep's "13 files import re"
    becomes 13 files that can build. The subjects here are synthetic and short;
    what is being checked is that the pattern COMPILES and the call returns a
    status, not that a synthetic subject is the file's own text.
    """
    found, dropped = corpus_patterns()
    check(len(found) >= 4,
          "the corpus walk found patterns to check (%d)" % len(found))
    # The filter `corpus_patterns` applies, asserted rather than trusted: a
    # candidate is dropped only because CPython's own `re` refuses it, and
    # every drop is accounted for by name so a candidate that stops being
    # droppable — a real corpus pattern that regressed into a fragment — is
    # visible here instead of silently moving a line.
    for p, (where, why) in sorted(dropped.items()):
        try:
            re.compile(p)
        except re.error as e:
            check(str(e) == why,
                  "the dropped candidate from %s is dropped for the reason "
                  "recorded (%s)" % (where, why), "now: %s" % e)
        else:                                          # pragma: no cover
            check(False, "%r from %s compiles now, so the walk should have "
                  "kept it" % (p, where))
    lines = [PRELUDE, "", "def main(n: Int) -> Int:"]
    pats = sorted(found)
    for i, p in enumerate(pats):
        lines.append("    p%d = %s" % (i, mojo_str(p)))
        lines.append("    st%d = [0, 0, 0, 0, 0, 0]" % i)
    for i, p in enumerate(pats):
        lines.append("    printf(\"P%d \")" % i)
        lines.append("    r%d = re.search(st%d, 6, p%d, \"fn foo[T] struct bar[x]\", "
                     "re.MULTILINE())" % (i, i, i))
        lines.append("    emit(0, r%d)" % i)
        lines.append("    emit(0, st%d[0])" % i)
        lines.append("    printf(\"%s\", re.nl())")
    src = "\n".join(lines) + "    return 0\n"
    try:
        out_lines = build_and_run(tmpdir, "corpuspat", src)
    except AssertionError as e:
        check(False, "the corpus-pattern program builds", str(e))
        return
    check(len(out_lines) == len(pats),
          "one line per corpus pattern",
          "%d vs %d" % (len(out_lines), len(pats)))
    for i, p in enumerate(pats):
        if i >= len(out_lines):
            break
        want = re.search(p, "fn foo[T] struct bar[x]", re.MULTILINE)
        toks = out_lines[i].split()
        if not check(toks and toks[0] == "P%d" % i,
                     "line %d is pattern P%d's" % (i, i),
                     "got %r" % (toks[0] if toks else None)):
            continue
        got = [int(x) for x in toks[1:]]
        # "Compiles" is a status, and 0 is one of the three good ones: most of
        # these patterns are about C function declarations and the synthetic
        # subject is a line of Mojo, so the right answer for most of them is
        # "no match", and demanding a match was demanding the wrong thing.
        # What must never happen is a REFUSAL (2 or 3) for a pattern the
        # corpus actually uses.
        check(got[0] == (1 if want is not None else 0),
              "corpus pattern %r compiles and agrees with CPython (found in %s)"
              % (p, found[p]), "status %s" % got[0])
        if want is not None and got[0] == 1:
            check(got[1] == want.start(),
                  "corpus pattern %r finds the same span CPython does" % p,
                  "got %d, CPython %d" % (got[1], want.start()))


def test_the_corpus_reaches_the_module_as_the_bytes_python_holds(tmpdir=None):
    """`mojo_str` writes the INVERSE of the literal decoder, and this says so.

    Every other comparison in this file is between what CPython computed and
    what an image computed, and this is the one that says the two were asked
    the SAME question: the pattern the module compiles is only the pattern
    CPython compiled if the bytes that arrived are the bytes the Python
    string holds, and a literal's body is decoded once on the way in. The
    harness's spelling is part of the measurement, not a detail of it.

    `fire_compiler.decode_c_escapes` is the decoder every engine in this tree
    calls (CLAUDE.md: one implementation, not one per engine), so decoding
    what `mojo_str` wrote is precisely what the image does to it — and that
    makes the round trip decidable here, in microseconds, with no build. It
    is not a synthetic check: the three shapes that failed are all in the
    corpus (`\b` in five cases, `\\` in one, a VERBOSE `#` comment whose `\n`
    has to stay two characters in one), and without this they arrive as a
    backspace, an incomplete atom and a real newline respectively — measured,
    with the byte tables in `mojo_str`'s docstring.

    The set walked is every pattern and subject in `CASES` and `UNSUPPORTED`,
    plus the shapes below that no case happens to hold: an empty string, one
    backslash, an octal escape, a hex escape, and a real tab.
    """
    import fire_compiler as F

    def round_trips(s):
        """True when what `mojo_str` writes DECODES to exactly `s`."""
        lit = mojo_str(s)
        if lit.startswith('"'):
            return F.decode_c_escapes(lit[1:-1]) == s
        # `mk2`/`mk3`: two or three literals with a `memset` of the
        # separator's byte code between them, so the pieces are checked
        # individually and the separator read back out of its own argument.
        pieces = re.findall(r'"([^"]*)"', lit)
        seps = [int(x) for x in re.findall(r", (\d+),", lit)]
        out = []
        for i, piece in enumerate(pieces):
            out.append(F.decode_c_escapes(piece))
            if i < len(seps):
                out.append(chr(seps[i]))
        return "".join(out) == s

    strings = set()
    for pat, subj, _flags, _note in CASES:
        strings.add(pat)
        strings.add(subj)
    for pat, _why in UNSUPPORTED:
        strings.add(pat)
    for extra in ("", "\\", "\\\\", "\\1", "\\101", "\\x41", "\t",
                  "a\tb", "a\nb\nc", r"\bcat\b", "\\d+", "\\W+"):
        strings.add(extra)
    for s in sorted(strings):
        check(round_trips(s),
              "the bytes %r reaches the module as the bytes Python holds" % s,
              "mojo_str wrote %s, which decodes to %r"
              % (mojo_str(s),
                 [F.decode_c_escapes(p) for p in
                  (re.findall(r'"([^"]*)"', mojo_str(s)) or
                   [mojo_str(s)[1:-1]])]))


def test_no_signature_is_wider_than_the_smaller_abi(tmpdir=None):
    """No function in `re.mojo` takes more parameters than the SMALLER of the
    two backends' integer argument register files passes — six.

    **That ceiling is no longer the ABI's, and the check is now narrower than
    the rule on purpose.**  Both conventions put the arguments past the register
    file in the caller's frame (`_MAX_INCOMING_ARGS` = 24 in each backend), so
    `sub: 7 parameters` builds on x86-64 as it always did on arm64, and the
    ceiling a module written today has to fit is twenty-four rather than six.
    `re.mojo`'s widest signatures are six (`split`, `group_text`, `findall`,
    `_term`, `_subwalk`, `_subfill`, `_run`, `_push`) because its functions were
    NARROWED to fit six registers while there was no alternative; nothing needs
    them wider now, and widening a host module's signatures back out is a
    decision somebody should take rather than drift nobody notices.  So the check
    stays at six and says why.

    It is still the cheap pre-check it was written as.  The x86-64 half of
    `test_the_module_builds_as_a_dylib_on_both_backends` is the real check and
    it costs a whole module compile; this one parses and costs nothing, so it
    says WHICH function is too wide instead of that a build failed.

    The ceiling is DERIVED from the two emitters rather than written down, for
    `test_struct_formal.py`'s reason: a hardcoded 6 would keep passing if either
    ABI changed, and would then be testing nothing. A function that RETURNS A
    FRAME needs one further word for the hidden block address
    (`formal/x86_64_codegen.py`'s prologue), so such a function has one fewer
    parameter to spend; `re.mojo` has none, and the build is what says so.
    """
    try:
        import fire_compiler as F
        from formal.arm64_codegen import _ABI_ARG_REGS
        from formal.x86_64 import ARG_REGS
    except Exception as e:                       # pragma: no cover
        check(False, "the two ABIs import", repr(e))
        return
    ceiling = min(_ABI_ARG_REGS, len(ARG_REGS))
    with open(RE_MODULE) as f:
        src = f.read()
    lines = src.split("\n")
    wide = []
    i = 0
    while i < len(lines):
        m = re.match(r"^def (\w+)\((.*)$", lines[i])
        if not m:
            i += 1
            continue
        sig = m.group(2)
        while sig.count("(") > sig.count(")") or sig.count("[") > sig.count("]"):
            i += 1
            sig += " " + lines[i].strip()
        depth = 0
        end = len(sig)
        for k, ch in enumerate(sig):             # cut the return annotation
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        params, cur, depth = [], "", 0
        for ch in sig[:end]:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            if ch == "," and depth == 0:
                params.append(cur)
                cur = ""
            else:
                cur += ch
        params.append(cur)
        n = len([p for p in params if p.strip()])
        if n > ceiling:
            wide.append("%s(%d) at line %d" % (m.group(1), n, i + 1))
        i += 1
    check(not wide,
          "every signature in re.mojo fits the %d integer argument registers "
          "both backends pass (widest offenders: %s)"
          % (ceiling, ", ".join(wide[:4]) or "none"))


def test_module_resolves_and_host_modelled_is_gone(tmpdir):
    """`re` resolves to the module source, and HOST_MODELLED no longer claims
    it. Without this the tests above would pass against a module no importer
    can reach, which is the shape the HOST_MODELLED entry used to have."""
    import formal.imports as I
    probe = os.path.join(HERE, "formal", "arm64.py")
    path = I.resolve_module_path("re", relative_to=probe, project_root=probe)
    check(path == RE_MODULE,
          "`import re` resolves to %s; got %r" % (RE_MODULE, path))
    check("re" not in I.HOST_MODELLED,
          "`re` is no longer in HOST_MODELLED — the entry claimed the module "
          "was reachable but unimplemented, and it is implemented")


def test_the_module_builds_as_a_dylib_on_both_backends(_tmpdir=None):
    """`re.mojo` compiles for arm64 AND x86-64.

    The same question `test_struct_formal.py` asks, for the same reason, and it
    used to have a premise that has since stopped being true: "a module compiled
    for BOTH backends has to fit the smaller of their integer argument register
    files" was right while neither ABI had a stack area, and both do now, so the
    constraint is a shared frame budget rather than a register count. The check
    is unaffected — it asserts the module builds for both — and it is now a
    statement about something weaker than it was.

    It is here because the widest signature in the file USED to be `sub`'s seven
    parameters, six of which the x86-64 ABI did not pass in registers, so this
    whole half of the test was unreachable: the build raised the arity refusal
    before a container was ever chosen, and the refusal was caught by the
    `except` arm below, which accepted it. Nothing here had ever looked at an
    x86-64 `re` dylib, and `sub` has since been narrowed to six.

    The container is asserted against `default_format(arch)` and NOT hardcoded,
    for `test_struct_formal.py`'s reason and because this check used to carry
    the premise `bugs/CODEGEN_x86_64_module_dylib_emitted_as_macho.md` was
    filed on and that doc's own author measured to be FALSE: on a macOS host an
    x86-64 image is a Mach-O, because an x86-64 binary that RUNS here has to be
    one Rosetta 2 will load and `fire.py`'s `_formal_run_argv` is what runs it.
    Asserting ELF would be asserting that the module library and the image
    linking it must disagree.
    """
    import tempfile as _tf
    try:
        import formal.build as B
        from formal.imports import build_module_dylib
    except Exception as e:                       # pragma: no cover
        check(False, "formal.imports imports", repr(e))
        return
    with _tf.TemporaryDirectory() as d:
        try:
            out = build_module_dylib("re", RE_MODULE, d, "arm64",
                                     project_root=RE_MODULE)
            check(bool(out) and os.path.isfile(out),
                  "re.mojo produces a module dylib for arm64")
        except Exception as e:
            check(False, "re.mojo compiles for arm64", str(e)[:300])
    with _tf.TemporaryDirectory() as d:
        try:
            out = build_module_dylib("re", RE_MODULE, d, "x86_64",
                                     project_root=RE_MODULE)
            produced = bool(out) and os.path.isfile(out)
            if produced:
                with open(out, "rb") as f:
                    magic = f.read(4)
                want = (b"\xcf\xfa\xed\xfe" if B.default_format("x86_64")
                        == "macho" else b"\x7fELF")
                check(magic == want,
                      "the x86-64 module dylib's container is %r, expected %r "
                      "— the format this host builds x86-64 in. A module "
                      "library and the image linking it must agree on it."
                      % (magic, want))
            else:
                check(False, "re.mojo produces a module dylib for x86_64")
        except Exception as e:
            check(False,
                  "re.mojo produces a module dylib for x86_64; it was refused "
                  "or mis-containered: %s" % str(e)[:300])


def test_the_sweep_files_no_longer_refuse_on_the_import(tmpdir):
    """None of the thirteen is refused for `re` any more.

    The measurement this whole change exists for. Each file is BUILT, and the
    verdict checked is specifically that `re` is no longer what stops it — a
    file that moved from "blocked on re" to "blocked on os" is exactly the
    progress this is meant to make, and what must NOT happen is the `re`
    message coming back.
    """
    files = ["consolidate_string_pool.py", "elaborate.py", "module_spec_gen.py",
             "mojo/backend_gimple/spec_gen.py", "mojo/middle/exprtypes.py",
             "reflect.py", "test_imports.py", "fire_compiler.py"]
    for rel in files:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            check(False, "%s exists" % rel)
            continue
        try:
            r = subprocess.run(
                [sys.executable, FIRE, "build", "--formal", "--no-prove",
                 "-o", os.path.join(tmpdir, os.path.basename(rel) + ".bin"),
                 path], capture_output=True, text=True, timeout=900, cwd=HERE)
        except subprocess.TimeoutExpired:
            check(False, "%s builds (timed out)" % rel)
            continue
        text = r.stderr + r.stdout
        check("imports 're'" not in text,
              "%s is no longer refused for importing `re`" % rel,
              text.strip()[-300:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", default=None,
                    help="only run tests whose name contains this")
    args = ap.parse_args()

    tests = [
        test_module_resolves_and_host_modelled_is_gone,
        test_the_corpus_reaches_the_module_as_the_bytes_python_holds,
        test_no_signature_is_wider_than_the_smaller_abi,
        test_mojo_str_round_trips_through_the_decoder,
        test_the_module_builds_as_a_dylib_on_both_backends,
        test_the_corpus_against_cpython,
        test_the_corpus_against_cpython_on_x86_64,
        test_escape_every_byte,
        test_unsupported_constructs_are_refused,
        test_a_span_list_that_is_too_small_is_a_status_not_a_crash,
        test_the_corpus_patterns_all_work,
        test_the_sweep_files_no_longer_refuse_on_the_import,
    ]
    with tempfile.TemporaryDirectory(prefix="re_formal_") as tmpdir:
        for t in tests:
            if args.k and args.k not in t.__name__:
                continue
            before = len(RESULTS)
            try:
                t(tmpdir)
            except Exception as e:
                check(False, "%s raised" % t.__name__, repr(e))
            if args.verbose:
                for ok, what in RESULTS[before:]:
                    print("  %s  %s" % ("ok  " if ok else "FAIL", what))

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%d/%d checks passed" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
