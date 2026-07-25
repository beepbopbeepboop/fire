# PARSE_FAIL: a string containing `\t` (or other escape whose letter is `t`/`T`) right before another quote later in the source corrupts tokenization

## Repro

```python
ESCAPES = {
    r"\t": (1, ord("\t")),
}
print(ESCAPES)
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:2:20: Expected COLON got RPAREN(')')
```

Even simpler, single-entry repro (no second string needed elsewhere on the
line — the *next* quote anywhere later in the statement is enough):
```python
ESCAPES = {
    r"\t": (1, ord("\t")),
}
```
fails identically. Real stdlib trigger: `Lib/re/_parser.py`'s `ESCAPES` dict
(lines 30-39) — `bugs/PARSE_FAIL_re__parser.md`.

## Root cause

`mojo_compiler.py`'s `_process_nested_tstrings` (~line 652-718) is a
preprocessing pass that scans the raw source text (before real tokenizing)
looking for `t"..."`/`f"..."`-style prefixed strings with nested `{}` to
placeholder-protect them. To avoid misapplying this to *plain* strings, it
first tries to skip any ordinary quoted string as one opaque unit
(~line 686-700):

```python
if stmt[i] in ('"', "'") and (i == 0 or stmt[i-1] not in
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'):
    ...skip to this string's own closing quote...
```

This guard only fires when the character *immediately before* the quote is
NOT alphanumeric — the intent (per the comment above it) is "don't treat a
quote as a string-start if it's actually a real string PREFIX letter
sitting right before it" (i.e. defer to the prefix-detecting regex below
instead). But this reasoning is backwards for a prefix like `r"`: `r` IS a
legitimate, ordinary (non-t/f) string prefix that this function should
still treat as a normal string to skip wholesale — the guard just declines
to skip it at all, and the loop falls through to append the `r` character
one-by-one and continue scanning from the quote itself, then from inside
the string's own content.

Once scanning is walking through the escaped content of `r"\t"` character
by character, it reaches the literal `t` in `\t` (a completely ordinary
backslash-escaped char inside a plain string — this function has no idea
it's "inside a string" at all at this point, since it never treated the `r"`
as a string-start). At that `t`, the t-string-prefix regex
(~line 701: `re.match(r'[rRfFbBuU]*[tT]{1}[rRfFbBuU]*', stmt[i:])`) matches
just the bare letter `t`, and the `is_prefix` check (~line 704) — `stmt[i-1]
not in <alnum set>` — is satisfied because `stmt[i-1]` is `\` (backslash),
which isn't alphanumeric either, so it looks like a valid, unattached
prefix-letter boundary. The code then treats the ORIGINAL raw string's own
closing `"` (immediately after this `t`) as if it were the *opening* quote
of a brand-new bare `t"..."` string, and searches forward via
`_find_tstring_closing_quote` for the next `"` anywhere later in the
statement — which in real code is often many characters away (here, the
`"` inside `ord("\t")`) — swallowing everything in between into one bogus
`__MOJO_STR_N__` placeholder and corrupting the token stream.

Confirmed via directly calling `mojo_compiler.py_tokenize` on the repro: the
STRING token for the first `r"\t"` comes out as the literal garbage
`'r"\\__MOJO_STR_0__\\t"'` instead of the correct `'r"\\t"'`.

Any backslash-escape whose letter is `t`/`T` (i.e. `\t` — the only common
one, since no other standard Python escape letter is literally `t`) sitting
inside ANY string (not just raw ones — plain `"...\t...more-source-with-a-
quote-later..."` would hit the identical bug, since the ordinary-string-skip
guard's "don't skip if preceded by an alnum char" reasoning is about the
character before the *string's own opening quote*, unrelated to raw-ness;
it's really about whether a `t"`/`f"` "prefix" is plausible there at all —
worth checking as part of the fix whether the deeper issue is specifically
`r"`-prefixed strings, or the guard is subtly wrong in a way that affects
non-prefixed plain strings containing `\t` too) followed later in the same
statement by another quote character is at risk.

## Suggested fix

Don't rely on the "character before the quote isn't alphanumeric" heuristic
at all for deciding whether to skip an ordinary string — it conflates
"there's a real prefix letter here" with "there's SOME letter here",  and
both cases should result in skipping the whole string as one unit (the
question of whether the letter(s) immediately before the quote form a t/f
*string-interpolation* prefix that needs special `{}`-aware placeholder
treatment is a separate question from "is this quote the start of a
string at all"). `replace_multiline_strings` (same file, ~line 846-861)
already has a correct, robust way to detect 0-2 prefix letters by scanning
*backward* from the quote and checking the character before those letters
isn't itself alphanumeric/underscore (i.e., correctly distinguishing a
real standalone prefix like `r"`/`rb"`/`Rf"` from a prefix-shaped tail of a
longer identifier like `self.attr"`, e.g. mid-word `r` in some name). Reuse
that same backward-scan logic here (or extract it into a shared helper both
functions call) instead of the simpler, buggy `stmt[i-1] not in <alnum>`
forward-looking check, so a `r"..."` (or any prefixed) string is always
recognized and skipped as one opaque unit up front, and the t/f-string
nested-brace detection only ever looks at strings that weren't already
consumed by the ordinary-string fast path.
