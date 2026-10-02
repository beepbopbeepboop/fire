"""`fnmatch` — CPython's shell-pattern matcher, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this file
is what `import fnmatch` binds to. It is the module
`bugs/FORMAL_platform_reachable_row_measured.md` §5 names as reachable-but-
unwritten, with the `*`-crosses-`/` difference spelled out at `match_core`.

WHAT IS HERE
------------
`fnmatch`, `fnmatchcase` and the matcher both are built on — `match_core`, which
is also what `formal/hostmods/pathlib.mojo`'s `match` calls. Before this file
existed that matcher was `pathlib.mojo`'s own `match_seg`/`match_bracket`, and
`fnmatch` would have been a SECOND implementation of one bracket matcher: the
`[seq]`/`[!seq]` rule, the range rule and the literal-`]`-first rule are the same
code in both. So the code moved here and `pathlib` calls it with the flag that
keeps `*` inside one path component, and there is now one bracket matcher in the
tree rather than two that can disagree.

`fnmatch` and `fnmatchcase` ARE the same function here, and that is CPython's
own structure rather than a shortcut: `fnmatch` is `normcase` applied to both
arguments and then `fnmatchcase`, and `os.path.normcase` is the IDENTITY on a
POSIX target. What CPython's `fnmatchcase` exists to avoid — a case-folding
`normcase` on Windows — cannot happen on this image, so `fnmatch` delegates to
it and the two answers agree by construction. `test_formal_fnmatch.py` asks
CPython both questions for every case and requires the image to agree with both.

THE ONE DIFFERENCE FROM `pathlib.match`, and it is the whole reason there is a
flag: `fnmatch`'s `*` CROSSES a `/` and `PurePath.match`'s does not.

    fnmatch.fnmatch("a/b.py", "*.py")   1     the `*` eats "a/b"
    PurePosixPath("a/b.py").match("*.py") 0    `match` is right-aligned and
                                                 component-wise, so this is a
                                                 comparison of "b.py" against a
                                                 one-component pattern that is
                                                 anchored at the END of the
                                                 path, and CPython answers 0
    fnmatch.fnmatch("b.py", "*.py")     1     which is what `match` compares

`match_core`'s `cross` argument is 1 for `fnmatch` and 0 for `pathlib`, and it
changes exactly two things: whether `*` may consume a `/`, and whether `?` may
match one. Both are unobservable through `pathlib` (it splits the path into
components first, so a `/` never reaches the matcher), which is why the flag
rather than two functions: the difference is a property of the PATTERN LANGUAGE,
and a second copy of the matcher would be two places for it to be wrong.

AN UNTERMINATED `[` IS A LITERAL `[`
--------------------------------------
`pathlib.mojo`'s own copy got this wrong, and it is the one behavioural
difference the move changed: it recursed with a NEGATIVE pattern length, which
its first test (`bn == 0`) did not catch, so the answer was 0 for every pattern
ending in an unterminated `[`. CPython's `fnmatch.translate` emits `\[` and
carries on, so `fnmatch("[", "[")` is 1 and `PurePosixPath("a[").match("a[")`
is True. Measured before the move, on this tree, arm64:

    match("a[", "a[")   0     CPython True
    match("a[b", "a[b") 0     CPython True
    match("[", "[")     0     CPython True

and 306 of 198,000 (component, pattern) pairs differed after it, every one of
them a pattern with an unterminated `[`.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `filter`, `filterfalse` — a SEQUENCE. Both take a list of names and answer a
    list of names, and a list is a blob carved out of the frame that built it, so
    it cannot cross a dylib boundary
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`). The matcher they would
    filter with is `match_core` and is here.
  * `iglob` — a GENERATOR, for the same reason `os.listdir` is a blob and a
    generator is worse: it has to survive between two calls.
  * `translate` — CPython's pattern-to-REGEX function. It is pure and its
    answer is a string, so it is answerable, and it is NOT written because its
    consumer is absent: the string it produces is full of `(?s:`, `(?>...)` and
    `\z`, and `formal/hostmods/re.mojo` supports none of those three, so a
    `translate` here would be a function whose output nothing on this path can
    compile. That is the honest reason and it is a different one from "it is
    hard": the algorithm is CPython's `_translate` plus
    `_join_translated_parts`, and `bugs/FORMAL_fnmatch_translate_absent.md`
    carries the transcription plan and the verification corpus for it.

THE DEPTH OF THE RECURSION IS THE INPUT'S
-----------------------------------------
`match_core` recurses once per pattern byte consumed, so its depth is the
PATTERN's length — and for `fnmatch` that is the whole pattern, where
`pathlib`'s copy was bounded by a COMPONENT's length. There is no depth guard
here for the same reason `pathlib.mojo` has none and `json.mojo`'s scanner has
one: a guard would be a constant somebody chose, and the property that matters
is the input's own size. What that costs is a stack, and a pattern of a few
hundred bytes is a few hundred frames.
"""

# ── byte helpers ───────────────────────────────────────────────────────────
#
# HERE rather than imported, and the reason is `pathlib.mojo`'s: a hostmod is
# its own dylib, so a call into another one is a cross-dylib call for a load and
# a memcpy. These are a few lines with no logic in them beyond "read a byte",
# and the rule about not answering a question twice is about QUESTIONS.

def byte_or(s, i) -> int:
    """The byte at `s + i`, or 256 at or past the NUL. See `pathlib.mojo`."""
    if i >= strlen(s):
        return 256
    var q: Pointer[UInt8] = s + i
    return q.value()


# ── the matcher ────────────────────────────────────────────────────────────

def match_core(a, ai, an, b, bi, bn, cross) -> int:
    """`a[ai:ai+an]` against the pattern `b[bi:bi+bn]`, fnmatch's language.

    `cross` is 1 when `*` may consume a `/` (`fnmatch`) and 0 when it may not
    (one path COMPONENT, which is what `PurePath.match` compares).

    `an` and `bn` are LENGTHS and `ai`/`bi` are indices into the two whole
    strings, because a pattern component rarely starts at 0 and a caller that
    had to pass substrings would have to build them. Keeping those two on
    different scales is the whole subtlety of the bracket step below: `j` and
    `end` are absolute indices into `b`, and the length handed back is
    `end - j - 1`.

    A backtracking walk. Each step consumes at least one byte of the pattern, so
    the depth is the pattern's length.
    """
    if bn <= 0:
        # The pattern is exhausted AND so must the input: this is a WHOLE-SPAN
        # match, anchored at both ends like CPython's `(?s:...)\\z`. Returning 1
        # here with input left over is what made `match("a/b.py", "[!]]")`
        # answer 1 where CPython answers 0 — the set matched the `b` and the
        # `.py` had nowhere to go.
        if an == 0:
            return 1
        return 0
    if an <= 0:
        # Only a pattern of nothing but `*` can still match nothing.
        if byte_or(b, bi) == 42:
            return match_core(a, ai, an, b, bi + 1, bn - 1, cross)
        return 0
    var bc = byte_or(b, bi)
    if bc == 42:
        # `*`: every split of the remaining input, shortest first. The `cross`
        # test is what the flag is FOR — with it off, a split that would have to
        # swallow a `/` ends the walk rather than being tried, because a `*` in
        # `PurePath.match` does not cross a component boundary.
        var k = 0
        while k <= an:
            if cross == 0 and k > 0 and byte_or(a, ai + k - 1) == 47:
                return 0
            if match_core(a, ai + k, an - k, b, bi + 1, bn - 1, cross) == 1:
                return 1
            k = k + 1
        return 0
    if bc == 63:
        # `?`: exactly one byte, and with the flag off not a `/` either.
        if cross == 1 or byte_or(a, ai) != 47:
            return match_core(a, ai + 1, an - 1, b, bi + 1, bn - 1, cross)
        return 0
    if bc == 91:
        # A `[...]` set, and the two rules that make `[]]` and `[!]]` mean what a
        # program means by them: a `]` IMMEDIATELY after the `[` or the `!` is a
        # literal, and `[!...]`/`[^...]` both negate (which is CPython's
        # `fnmatch` spelling).
        #
        # The CLOSING `]` IS FOUND FIRST, in its own scan, and everything else
        # is decided against it. That is not tidiness: the range rule cannot be
        # stated without knowing where the set ends, because a `-` immediately
        # before the `]` is a LITERAL `-` and not half a range. CPython's
        # `translate` does the same thing for the same reason — it searches for
        # the `]` before it looks at anything inside the set. Doing it the other
        # way round (walking the body and hoping a `]` turns up) is what made
        # `fnmatch("-", "[a-]")` answer 0 where CPython answers 1: the walk read
        # the closing bracket as a range's upper bound, ran past the end of the
        # set, and then called the set unterminated.
        var end = bi + bn
        var close = bi + 1
        if close < end and byte_or(b, close) == 33:
            close = close + 1
        if close < end and byte_or(b, close) == 93:
            close = close + 1
        while close < end and byte_or(b, close) != 93:
            close = close + 1
        if close >= end:
            # An unterminated `[` is a LITERAL `[`, and the pattern carries on
            # with the bytes after it as ordinary pattern characters. CPython
            # says the same thing by emitting `\\[` and continuing its loop at
            # the same `i`; the copy this replaced recursed with a negative
            # length instead, which answered 0 for every one of them.
            if byte_or(a, ai) != 91:
                return 0
            return match_core(a, ai + 1, an - 1, b, bi + 1, bn - 1, cross)
        var j = bi + 1
        var neg = 0
        if j < close and byte_or(b, j) == 33:
            neg = 1
            j = j + 1
        var c = byte_or(a, ai)
        var hit = 0
        if j < close and byte_or(b, j) == 93:
            if c == 93:
                hit = 1
            j = j + 1
        while j < close:
            # A `X-Y` span is a RANGE, which is the three-byte step — and the
            # `j + 2 < close` is the literal-`-` rule: a `-` with nothing but
            # the closing bracket after it is a member of the set. CPython's own
            # answers for the two shapes: `translate("[a-c]")` is
            # `(?s:[a-c])\\z` and `translate("[a-]")` is `(?s:[a\\-])\\z`.
            if j + 2 < close and byte_or(b, j + 1) == 45:
                if c >= byte_or(b, j) and c <= byte_or(b, j + 2):
                    hit = 1
                j = j + 3
            else:
                if c == byte_or(b, j):
                    hit = 1
                j = j + 1
        if neg == 1:
            hit = 1 - hit
        if hit == 0:
            return 0
        return match_core(a, ai + 1, an - 1, b, close + 1, end - close - 1,
                          cross)
    if bc != byte_or(a, ai):
        return 0
    return match_core(a, ai + 1, an - 1, b, bi + 1, bn - 1, cross)


def match_any(name, pat) -> int:
    """`fnmatchcase(name, pat)` over whole strings: the `cross = 1` entry.

    Named for what it does rather than exported as `fnmatchcase` alone, because
    `pathlib.mojo` needs a whole-string entry too and this is it. `fnmatch` and
    `fnmatchcase` below are this function under CPython's two names.
    """
    return match_core(name, 0, strlen(name), pat, 0, strlen(pat), 1)


# ── CPython's two names ────────────────────────────────────────────────────

def fnmatchcase(name, pat) -> int:
    """`fnmatch.fnmatchcase(name, pat)`: 1 or 0.

    Whole-string and anchored at BOTH ends, as CPython's is: its
    `translate` wraps the pattern in `(?s:...)\\z`, and `match_core` with
    `cross = 1` exhausts the pattern only where the input is also exhausted.
    """
    return match_any(name, pat)


def fnmatch(name, pat) -> int:
    """`fnmatch.fnmatch(name, pat)`: 1 or 0.

    CPython's is `fnmatchcase(normcase(name), normcase(pat))`, and
    `os.path.normcase` is the IDENTITY on a POSIX target — `test_formal_os.py`
    checks that against CPython's own `posixpath` for `normcase` itself. So
    this is `fnmatchcase` with the case-normalising step elided, which is why it
    delegates rather than repeating the matcher: on this target the two can
    never differ, and a second copy of the walk would be a second thing to be
    wrong about a fact that is a property of the platform.
    """
    return fnmatchcase(name, pat)