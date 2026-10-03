"""`textwrap` — the two pure string functions, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this file
is what `import textwrap` binds to. `textwrap` left `HOST_MODELLED` when it
landed, because that set is a CLAIM that a module could be written and
`formal/imports.py`'s own rule is that a name LEAVES it by being written: an
entry left behind would refuse a file AFTER the module that answers it is
sitting in the tree, which is a false statement rather than a conservative one.

WHAT IS HERE, AND WHY THESE TWO
-------------------------------
CPython's `textwrap` is eleven names. Two of them are pure computation over
strings a value already is, and they are the two this repository actually
calls — measured, not read:

    textwrap.dedent   x78 call sites, over 5 files
    textwrap.indent   x2  call sites, both `textwrap.indent(body, "    ")`

`test_runtime_diff.py`, `test_interp_oracle.py` and `test_comptime_parity.py`
are three of those five files, and they are the whole reason this module is
worth writing: each of them stopped on `import textwrap` and on NOTHING ELSE,
so each is one `dedent` away from building. That is 3 files of the sweep's
host-import row bought by a module with no dependency on anything.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `wrap` — a SEQUENCE. It answers a list of strings, and a list on this path
    lives in the frame of the function that made it and cannot cross a dylib
    boundary (`bugs/FORMAL_listdir_no_run_time_sequence.md`). This is the same
    reason `fnmatch.filter` is absent from `fnmatch.mojo`.
  * `fill` — the same shape one step later: `fill` is `wrap`'s answer joined
    by newlines, so it is answerable, and it is absent because NOTHING on this
    path calls it. `formal/hostmods/argparse.mojo` has its own transcription of
    `textwrap`'s greedy fill (`_wrap_into`, with `_chunk_end`,
    `_hyphen_break` and `_squashed` beside it), and that one is a function of a
    help string at ONE width with the formatter's own indent arithmetic: it is
    not a general `fill`, and re-exporting it under this module's name would
    make the module's `fill` a second, differently-parameterised copy of a
    transcription `test_formal_argparse.py` already checks case for case.
    Naming that here is the honest reason, and it is the reasoning
    `fnmatch.mojo` gives for `translate`.
  * `shorten` — `TextWrapper(width, max_lines=1)` plus a `' '.join(split())`.
    It is `fill` plus a word count, so it inherits `fill`'s absence; and
    `TextWrapper` is an object with nine pieces of mutable configuration, which
    is at least nine words where a value on this path is one
    (`formal/model.py`; `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_
    run_time.md` is the measurement, and it is `collections`' and `copy`'s
    blocker too). Note the consequence honestly: `wrap`/`fill` being ABSENT
    means the absent `TextWrapper` costs nothing extra, because nothing that
    wanted the object was going to get the function either.
  * `TextWrapper`, `HTMLWrapper`, `BackslashWrapper` — CLASSES, per above.
  * `dedent`'s cousin `inspect.cleandoc` is NOT re-exported here and must not
    be: it is a different function (it expands tabs and strips leading and
    trailing blank lines), it lives in `inspect`, and this tree reads
    `inspect`'s answers off a live interpreter.

THE TWO FUNCTIONS SHARE NO CODE, and the reason is about their DATA
--------------------------------------------------------------------
`dedent` splits on `\\n` alone; `indent` uses `str.splitlines`, which breaks on
`\\r`, `\\v`, `\\f`, `\\x1c`, `\\x1d`, `\\x1e` too, and treats `\\r\\n` as ONE
boundary. So `indent("a\\rb", ">")` is `">a\\r>b"` where a `\\n`-only walk gives
`">a\\rb"`, and `dedent("  \\r\\n  a\\n")` puts the `\\r` INSIDE the first line
so it is deleted with the margin where `indent` would prefix before it. One
shared "walk the lines" helper would have to carry that as a flag, and a
walker with a flag is two walkers — which is the shape
`bugs/FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with.md` and
`contextlib.mojo`'s `closing` both refuse to ship.

THE BYTE SETS ARE BUILT WITH `memset`, and that is not a style choice
-------------------------------------------------------------------
A string LITERAL's escapes are NOT unescaped on this path
(`bugs/FORMAL_string_literal_escape_is_not_decoded.md`), so `"\\t"` in a Mojo
source is a backslash and a `t`. Every separator set in this module is a
`memset` byte for that reason, exactly as `argparse.mojo` does it and for the
reason its `_ws_set` gives. `test_formal_textwrap.py` is the assertion that the
two sets are RIGHT and that they are DIFFERENT sets: CPython's `isspace()` is
true of 0x1F and `splitlines` is not, and a corpus carrying a 0x1F line is what
would catch one set copied into the other.
"""

from os._syscalls import str_alloc, str_put, str_len, str_prefix


# ── the byte sets ───────────────────────────────────────────────────────────
#
# Built with `memset` because a literal cannot spell them (module docstring,
# last section). Each is a NUL-terminated `strspn` accept-set, built per call
# rather than cached: a module-level name has no storage on this path.

def _indent_set() -> str:
    """The bytes `dedent`'s margin walk accepts: space and tab, and nothing else.

    CPython's test is `c not in ' \\t'`, so this set is exactly its complement
    among the bytes that can occur: a `\\r` at the margin position is neither and
    must STOP the walk, which is what `dedent("  \\r\\n  a\\n")` measures.
    """
    s = str_alloc(3)
    memset(s, 32, 1)          # space
    memset(s + 1, 9, 1)       # tab
    memset(s + 2, 0, 1)
    return s


def _space_set() -> str:
    """The bytes CPython's `str.isspace()` is true of, in ASCII.

    MEASURED on this interpreter rather than read off a table, because the set
    is larger than the four separators everyone remembers:

        >>> [c for c in range(128) if chr(c).isspace()]
        [9, 10, 11, 12, 13, 28, 29, 30, 31, 32]

    0x1F (UNIT SEPARATOR) is the one that surprises and it is IN the set,
    because `str.isspace()` says so. `test_formal_textwrap.py`'s corpus
    includes a 0x1F line, which is the case that catches a set built from
    `" \\t\\n\\v\\f\\r"`.

    A NUL is not in the set and cannot be: a formal string is NUL-terminated, so
    a NUL byte cannot occur in one at all.
    """
    s = str_alloc(11)
    memset(s, 9, 1)           # \t
    memset(s + 1, 10, 1)      # \n
    memset(s + 2, 11, 1)      # \v
    memset(s + 3, 12, 1)      # \f
    memset(s + 4, 13, 1)      # \r
    memset(s + 5, 28, 1)      # \x1c  FILE SEPARATOR
    memset(s + 6, 29, 1)      # \x1d  GROUP SEPARATOR
    memset(s + 7, 30, 1)      # \x1e  RECORD SEPARATOR
    memset(s + 8, 31, 1)      # \x1f  UNIT SEPARATOR
    memset(s + 9, 32, 1)      # space
    memset(s + 10, 0, 1)
    return s


def _splitlines_set() -> str:
    """The ASCII bytes `str.splitlines` breaks on, MEASURED not remembered.

        >>> [c for c in range(128) if len(('a'+chr(c)+'b').splitlines(True))==2]
        [10, 11, 12, 13, 28, 29, 30]

    So it is `\\n`, `\\v`, `\\f`, `\\r` and the three C separators, and **not**
    0x1F — which is in `isspace()` (above) and not in `splitlines`. A set
    copied from the `isspace` one would therefore split `indent` on a 0x1F
    where CPython does not, and the test's corpus carries a 0x1F case so the two
    cannot be the same set by accident.

    `str.splitlines` also breaks on U+0085, U+2028 and U+2029, which are not
    single bytes and cannot be recognised in a byte string at all; the corpus
    is ASCII and says so.
    """
    s = str_alloc(8)
    memset(s, 10, 1)          # \n
    memset(s + 1, 11, 1)      # \v
    memset(s + 2, 12, 1)      # \f
    memset(s + 3, 13, 1)      # \r
    memset(s + 4, 28, 1)      # \x1c
    memset(s + 5, 29, 1)      # \x1d
    memset(s + 6, 30, 1)      # \x1e
    memset(s + 7, 0, 1)
    return s


# ── reading the lines of a string ───────────────────────────────────────────

def _line_end(text, i, n) -> int:
    """The index of the first `\\n` at or after `i`, or `n` if there is none.

    `dedent`'s boundary, which is `\\n` and ONLY `\\n`. Returns `n` for a line
    that runs to the end of the string, and the caller distinguishes "the last
    line, unterminated" from "an empty final line" by whether the index is `n`.
    """
    j = i
    while j < n:
        var b: Pointer[UInt8] = text + j
        if b.value() == 10:
            return j
        j = j + 1
    return n


def _is_blank(s, ln, sp) -> int:
    """1 if the `ln` bytes at `s` are empty or are ALL in the space set.

    CPython's `not l or l.isspace()` in one predicate, because `dedent` splits
    on `\\n` and therefore CAN produce the empty string where `splitlines` cannot.
    """
    if ln == 0:
        return 1
    var i: Pointer[UInt8] = s
    var k = 0
    while k < ln:
        if strspn(i + k, sp) == 0:
            return 0
        k = k + 1
    return 1


# ── `dedent` ────────────────────────────────────────────────────────────────

def dedent(text) -> str:
    """`textwrap.dedent(text)`: the common leading whitespace, removed.

    CPython's algorithm, transcribed from `textwrap.py`'s own body:

        lines = text.split('\\n')
        non_blank_lines = [l for l in lines if l and not l.isspace()]
        l1 = min(non_blank_lines, default='')
        l2 = max(non_blank_lines, default='')
        margin = 0
        for margin, c in enumerate(l1):
            if c != l2[margin] or c not in ' \\t':
                break
        return '\\n'.join([l[margin:] if not l.isspace() else '' for l in lines])

    THE MINIMUM AND MAXIMUM ARE LEXICOGRAPHIC AND BOTH ARE NEEDED, and that is
    not a detail. The pair is what makes the margin a property of EVERY
    non-blank line rather than of the first one: walking `l1` alone stops at the
    first line whose content differs and under-counts, walking `l2` alone
    over-counts. The loop's `margin` is the index at which it BREAKS, which is
    why `margin` is 0 for an empty input and for one with no non-blank line —
    `enumerate` never runs and the initialiser is the answer.

    `l2[margin]` is indexed with `margin` rather than walked separately, so `l2`
    must be at least as long as the walk. It is: `l1 <= l2` lexicographically
    implies `len(l2) >= len(l1)` unless `l2` is a PROPER PREFIX of `l1`, which
    `<=` excludes. `test_formal_textwrap.py`'s corpus includes the
    `("ab", "abc")` shape that makes this observable: `dedent("ab\\nabc\\n")` is
    unchanged, and a copy that read `l2` past its end would not be.

    Three behaviours fall out of the transcription and each is a case in the
    test:

      * **A whitespace line becomes EMPTY, not a bare newline.**
        `dedent("   \\n  a\\n")` is `"\\na\\n"`. CPython REPLACES such a line
        rather than trimming it, so the blank line's own bytes are dropped too.

      * **Tabs and spaces are not equal, so the margin stops mid-run.**
        `dedent("  \\ta\\n \\tb\\n")` is `" \\ta\\n\\tb\\n"` — margin 1, because
        at offset 1 the two lines hold `\\t` and ` `. CPython's own docstring
        says so, and the min/max pair is what gets it without a special case.

      * **A non-blank line shorter than the margin is emptied too**, because
        `l[margin:]` of it is the empty string — which is why "is it
        whitespace" and "is it at least `margin` long" are different tests and
        both are here.

    Returns a fresh buffer the caller owns, like every function in this tree.
    """
    n = str_len(text)
    sp = _space_set()
    ind = _indent_set()

    # Pass 1: the lexicographic minimum and maximum over the NON-BLANK lines,
    # each held as a NUL-terminated copy so `strcmp` can order them. No list of
    # lines is materialised: there is no list on this path, and the lines are
    # found by walking `text` twice instead.
    l1 = ""
    l2 = ""
    seen = 0
    var i = 0
    while i <= n:
        j = _line_end(text, i, n)
        ln = j - i
        if _is_blank(text + i, ln, sp) == 0:
            var cand = str_prefix(text + i, ln)
            if seen == 0:
                l1 = cand
                l2 = cand
                seen = 1
            else:
                if strcmp(cand, l1) < 0:
                    l1 = cand
                if strcmp(cand, l2) > 0:
                    l2 = cand
        if j >= n:
            break
        i = j + 1

    # The margin: `l1` and `l2` in step, stopping at the first byte that
    # differs or is not a space/tab.
    var m1 = str_len(l1)
    var margin = 0
    while margin < m1:
        var a1: Pointer[UInt8] = l1 + margin
        var a2: Pointer[UInt8] = l2 + margin
        if a1.value() != a2.value():
            break
        if strspn(l1 + margin, ind) == 0:
            break
        margin = margin + 1

    # Pass 2: the answer. A whitespace line contributes NOTHING (CPython
    # replaces it with the empty string, so not even a newline); any other line
    # keeps its bytes from `margin` on, and a line shorter than `margin` is
    # emptied by the slice. Lines are joined with a single `\\n` BETWEEN them,
    # which is what `'\n'.join(...)` over `split('\n')` is: a trailing newline
    # in `text` is an empty final line and so contributes a final separator.
    out = str_alloc(n + 2)
    var used = 0
    var first = 1
    var i = 0
    while i <= n:
        j = _line_end(text, i, n)
        ln = j - i
        if first == 0:
            used = str_put(out, used, "\n", 1)
        first = 0
        if _is_blank(text + i, ln, sp) == 0 and margin < ln:
            used = str_put(out, used, text + i + margin, ln - margin)
        if j >= n:
            break
        i = j + 1
    memset(out + used, 0, 1)
    return out


# ── `indent` ────────────────────────────────────────────────────────────────

def indent(text, prefix) -> str:
    """`textwrap.indent(text, prefix)`: `prefix` before every non-blank line.

    CPython's `predicate=None` arm:

        for line in text.splitlines(True):
            if not line.isspace():
                prefixed_lines.append(prefix)
            prefixed_lines.append(line)
        return ''.join(prefixed_lines)

    Two details are the whole function and both are pinned by the test:

      * **`splitlines(True)`, and it is NOT `split('\\n')`.** `str.splitlines`
        breaks on `\\r`, `\\v`, `\\f`, `\\x1c`, `\\x1d` and `\\x1e` as well, and on
        a `\\r\\n` pair it breaks ONCE. So `indent("a\\rb", ">")` is `">a\\r>b"`
        in CPython, where a `\\n`-only walk gives one `>`; the test has a `\\r`
        case for exactly that.

      * **The line keeps its terminator and the prefix goes BEFORE it.**
        `indent("a\\r\\nb", ">")` is `">a\\r\\n>b"`: the prefix is not after the
        `\\r\\n` pair. A walk that consumed the terminator and re-emitted it
        would put the second `>` after the pair, which is the same bug in the
        other direction.

    The blank test is `str.isspace()` and not a truth test, because
    `splitlines` does not produce the empty string — CPython says so in a
    comment of its own, and `indent("  \\n", ">")` is `"  \\n"`: a whitespace
    line keeps its bytes and gets no prefix.

    Returns a fresh buffer the caller owns.
    """
    n = str_len(text)
    sp = _space_set()
    bs = _splitlines_set()
    var pn = str_len(prefix)
    out = str_alloc(n + 16)
    var used = 0
    var i = 0
    while i < n:
        # The end of this line, INCLUDING its terminator; `\\r\\n` is one.
        var j = i
        while j < n:
            if strspn(text + j, bs) > 0:
                break
            j = j + 1
        if j < n:
            var c: Pointer[UInt8] = text + j
            if c.value() == 13 and j + 1 < n:
                var d: Pointer[UInt8] = text + j + 1
                if d.value() == 10:
                    j = j + 2
                else:
                    j = j + 1
            else:
                j = j + 1
        var ln = j - i
        if _is_blank(text + i, ln, sp) == 0:
            used = str_put(out, used, prefix, pn)
        used = str_put(out, used, text + i, ln)
        i = j
    memset(out + used, 0, 1)
    return out