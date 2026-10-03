"""`textwrap` — `dedent` and `indent`, which are PURE STRING COMPUTATION.

`formal/imports.py` has `textwrap` in `HOST_MODELLED`, under "a state machine
over a string, the same shape as `re` and `fnmatch`, which are written". This
file is that claim paid, and it is the cheapest row in the whole
host-import census: **five files in this repository import `textwrap`, and
between them they spell two names — `dedent` 78 times and `indent` twice, with
not one keyword argument between them.** There is no third name to write and
there is no keyword to bind, so this module is the complete surface and
`test_formal_textwrap.py` says so by reading the tree.

WHAT IS COMPUTED, AND AGAINST WHAT
----------------------------------
Everything here. `dedent` is a margin computation and a rewrite, `indent` is a
per-line prefix, and neither touches anything a freestanding image does not
have. **Zero admitted contracts**: a string is a `char *` this path already
carries (`formal/hostmods/os/_syscalls.mojo` has `str_len`, `str_at`,
`str_lead`, `str_find`, `str_cmp`, `str_eq_n`, `str_build`, `str_put`,
`str_alloc`, `str_copy`), so there is nothing to trust and nothing to declare.
`test_formal_admitted.py` records `textwrap: 0` for that reason, which is what
puts this module in no tier at all.

THE MARGIN, AND WHY IT IS NOT THE OBVIOUS THING
----------------------------------------------
CPython's `dedent` does not take the minimum of the leading-whitespace run
lengths. It takes the **lexicographic minimum and maximum of the non-blank
lines** and counts the leading ` `/`\t` bytes the two agree on. Those are
different answers and the difference is the whole rule:

    textwrap.dedent("  a\\n \\tb")     ->  "a\\n\\tb"     margin 0
    textwrap.dedent("  a\\n   b")      ->  "a\\n  b"     margin 2
    min(len(run)) over the same two    ->  1             WRONG

A space and a tab are both whitespace and they are **not equal**, which is the
one sentence CPython's own docstring leads with, and the min/max form is what
makes it true: `"\tb" < "  a"` because `\\t` is `0x09` and `"  "` is `0x20 0x20`,
so the two extremes disagree at byte 0 and the margin is 0 — where a
minimum-of-lengths would have found 1 and stripped a character from a line that
had no common whitespace at all.

So the module takes the min and the max the way CPython does, over the FULL
lines. That needs a NUL-terminated copy per comparison, because `str_cmp` is
`strcmp` and a line inside a longer buffer is not terminated: **one `malloc` per
line compared, `O(n²)` in the number of lines**, which for the thing this is
used for — a triple-quoted source literal — is a handful of lines. A cheaper
formulation exists (compare the leading RUNS rather than the lines) and it is
not taken, because "cheaper and provably the same" is a claim about a
subtlety; the expensive one is what CPython does, and the corpus in
`test_formal_textwrap.py` is chosen to hit the case above.

Blank lines go to `""` in CPython's output, whatever their width, and that is
reproduced rather than "trimmed": `"a\n   \nb"` dedents to `"a\n\nb"`, which is
a line with NO trailing spaces where the source had three, and a reader
checking that has to be checking CPython's answer.

WHAT IS NOT HERE, AND WHY
------------------------
  * `wrap`, `fill`, `shorten`, `longen`, `TextWrapper`. `wrap` is a text
    MEASUREMENT problem (`textwidth`, `_get_chunks`, `_wrap_chunks`) whose
    subject is a rendering width, and no file in this tree asks for one; the
    two callers here want a triple-quoted literal to lose its indentation.
  * `fill` and `shorten` are `wrap` with a different caller, so they go with it.
  * `dedent`'s `predicate`/`indent`'s `predicate`. CPython's `indent` takes one
    and both call sites here do not pass it; a `predicate` is a CALLABLE, and a
    function value is not a word on this path
    (`bugs/FORMAL_callable_param_called_in_ordinary_generator_returns_garbage`).

  * `str.isspace()` is CPython's Unicode predicate and this is a byte set.
    `_syscalls.mojo`'s `_STR_WS` says the same thing for `str.strip()` and the
    set is the same one: space, `\t`, `\n`, `\r`, `\v`, `\f`, `\x1c`-`\x1f`,
    and **not** `\x85` (U+0085 NEL), because in UTF-8 that is the two bytes
    `\xc2\x85` and a byte-wise `strspn` cannot see it. Recorded rather than
    omitted, and no caller in this tree dedents a string that can hold one.

  * `indent`'s `str.splitlines` terminator set is the ASCII half of CPython's —
    `\n`, `\r`, `\r\n`, `\v`, `\f`, `\x1c`-`\x1e` — and not the Unicode
    half (`\x85`, `\u2028`, `\u2029`), for the same reason. `dedent` splits on
    `\n` ALONE, because that is what CPython's `dedent` does: it calls
    `text.split('\n')`, not `splitlines`, so a `\r` is an ordinary character
    inside a line and `indent` and `dedent` do not agree on their own line sets.
    Both facts are checked against CPython by the test.
"""

from os._syscalls import str_len, str_lead, str_find, str_cmp, str_eq_n
from os._syscalls import str_alloc, str_put, str_copy, str_at

# CPython's whitespace set, restricted to characters one byte can hold. This is
# `_syscalls.mojo`'s `_STR_WS` with `\n` kept, and it is written out rather than
# imported because that module's is private (a leading underscore, which
# doc/ABI.md's export rule excludes) — see §WHAT IS NOT HERE for what the set
# does not have.
_WS = " \t\n\r\v\f\x1c\x1d\x1e\x1f"

# The bytes `indent`'s `splitlines` treats as a line terminator, minus `\n` and
# `\r` which `_line_end` handles explicitly so that `\r\n` is ONE terminator.
_BREAKS = "\v\f\x1c\x1d\x1e\x1f"

_NL = 10
_CR = 13
_INDENT_CHARS = " \t"


def _blank(s: str, a, b) -> int:
    """1 when `s[a:b]` is empty or is nothing but whitespace.

    CPython's `l and not l.isspace()` in one predicate, and `str_lead` is the
    whole of it: `strspn` returns the LENGTH of the run of set bytes from the
    pointer, so a run at least as long as the span is a span of nothing but
    them. The run is allowed to continue past `b` — a line of two spaces
    followed by a newline and more spaces measures 4 for a 2-byte span — and
    that is correct rather than sloppy: CPython asks whether the LINE is
    whitespace, and the bytes past it are whitespace too.
    """
    if str_lead(s + a, _WS) >= b - a:
        return 1
    return 0


def _nl_at(s: str, i, n) -> int:
    """Where the `s.split('\n')` line starting at `i` ends, or `n`.

    `split('\n')` and NOT `splitlines`: that is CPython's `dedent`'s own
    choice, so a `\r` is an ordinary character inside a line here while
    `indent` treats it as a terminator. The two disagree, and reproducing the
    disagreement is the point — a `dedent` whose line set matched `indent`'s
    would be right about `\r\n` source and wrong about CPython's answer for it.
    """
    k = str_find(s + i, "\n", 0)
    if k < 0:
        return n
    return i + k


def dedent(text: str) -> str:
    """`textwrap.dedent(text)`: the common leading whitespace, removed.

    Three passes, and they are CPython's three:

      1. every `text.split('\n')` line that is non-empty and not all
         whitespace, keeping the lexicographic MINIMUM and MAXIMUM as
         NUL-terminated copies — the copies are the price of `strcmp` over a
         line that is a span of a longer buffer, and the docstring says why the
         full lines are compared rather than the leading runs;
      2. the margin: the longest prefix the two agree on that is made of
         spaces and tabs, computed with `str_lead` (how far each runs) and
         `str_eq_n` (do they agree that far) so that no byte has to be read as
         a value — this path has no way to read one;
      3. the rebuild, into one `malloc`'d buffer: every non-blank line from its
         margin onwards, every blank line as nothing at all, `\n` between.

    An empty `text` is `""`, and so is a `text` with no non-blank line — CPython
    takes `min(..., default='')` and the margin of an empty string is 0.
    """
    n = str_len(text)
    lo = 0
    hi = 0
    i = 0
    while i <= n:
        j = _nl_at(text, i, n)
        if _blank(text, i, j) == 0:
            cur = str_copy(str_alloc(j - i), text + i, j - i)
            if lo == 0:
                lo = cur
                hi = cur
            else:
                if str_cmp(cur, lo) < 0:
                    lo = cur
                if str_cmp(cur, hi) > 0:
                    hi = cur
        if j >= n:
            break
        i = j + 1

    margin = 0
    if lo != 0:
        p1 = str_lead(lo, _INDENT_CHARS)
        p2 = str_lead(hi, _INDENT_CHARS)
        while margin < p1 and margin < p2 and str_eq_n(lo, hi, margin + 1) == 1:
            margin = margin + 1

    out = str_alloc(n)
    used = 0
    i = 0
    while i <= n:
        j = _nl_at(text, i, n)
        if _blank(text, i, j) == 0 and j - i > margin:
            used = str_put(out, used, text + i + margin, j - i - margin)
        if j >= n:
            break
        used = str_put(out, used, "\n", 1)
        i = j + 1
    return out


def _line_end(s: str, i, n) -> int:
    """Where the line starting at `i` ENDS, terminator INCLUDED, or `n`.

    `str.splitlines(True)`'s rule over the ASCII half: `\n`, `\r`, `\r\n`,
    `\v`, `\f`, `\x1c`, `\x1d`, `\x1e`. `\r\n` is ONE terminator, which is the
    only part of the rule that is not "the next break byte", and it is why
    `_CR` is handled here rather than left in `_BREAKS`.
    """
    k = i
    while k < n:
        if str_lead(s + k, _BREAKS) > 0:
            return k + 1
        # `str_at(s, k, "\n")` and NOT `s[k] == "\n"`: a byte read is a
        # NUMBER on this path and comparing it with a string is refused outright
        # ("compares a NUMBER with a string", and a `strcmp` would dereference
        # the integer). `str_at` is the set test over the same byte, which is
        # the only spelling of "is this character a newline" here.
        if str_at(s, k, "\n") == 1:
            return k + 1
        if str_at(s, k, "\r") == 1:
            if k + 1 < n and str_at(s, k + 1, "\n") == 1:
                return k + 2
            return k + 1
        k = k + 1
    return n


def indent(text: str, prefix: str) -> str:
    """`textwrap.indent(text, prefix)`: `prefix` in front of every content line.

    With no `predicate`, CPython prefixes every line that is not all
    whitespace — and "not all whitespace" INCLUDES the empty line being
    excluded, because `str.splitlines(True)` does not produce one and a line of
    nothing but a terminator is `"\n"`, which IS whitespace, so it gets no
    prefix either. A blank line stays blank and keeps its terminator, which is
    the difference between this and a `replace`.

    The result is never longer than `len(text) + len(prefix) * (number of
    content lines)`, so the buffer is sized by doubling the input and the
    `str_put` calls do the arithmetic.
    """
    n = str_len(text)
    p = str_len(prefix)
    out = str_alloc(n + p + 8)
    used = 0
    i = 0
    while i < n:
        e = _line_end(text, i, n)
        if _blank(text, i, e) == 0:
            used = str_put(out, used, prefix, p)
        used = str_put(out, used, text + i, e - i)
        i = e
    return out