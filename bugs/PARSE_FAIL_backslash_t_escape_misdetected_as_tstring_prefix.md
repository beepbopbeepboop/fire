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

## Status
**Fixed**

`mojo_compiler.py`:

- Added a new module-level helper `_string_prefix_start(source, quote_pos)`
  (~line 618, right before `_find_tstring_closing_quote`) that scans
  *backward* from a quote character for up to 2 legitimate string-prefix
  letters (`f`/`F`/`r`/`R`/`b`/`B`/`u`/`U`/`t`/`T`), returning the prefix's
  true start position, or `quote_pos` itself if there's no real prefix
  (correctly distinguishing a standalone prefix like `r"` from the tail of
  a longer identifier, e.g. the `r` in `self.attr"`). This consolidates the
  backward-scan logic that used to be duplicated inline inside
  `replace_multiline_strings` (~line 847 previously) — that function now
  just calls `_string_prefix_start(src, i)` instead of reimplementing the
  scan (per CLAUDE.md's "consolidate duplicates" rule). The helper uses
  explicit `==` character comparisons rather than `c in 'fFrRbBuUtT'`,
  matching the pattern `replace_multiline_strings` already used deliberately
  to avoid this codegen's compiled `in`-for-`char*` stub (documented inline
  at the call site) — an `in`-on-string check here would silently break
  under `make check-selfhost` even though ordinary Python tests wouldn't
  catch it.

- Rewrote `_process_nested_tstrings` (~line 697) to key its ordinary-string
  vs. t/f-string dispatch off the QUOTE character (via
  `_string_prefix_start`, scanning backward) instead of the old two-part
  scheme: an ordinary-string guard that only skipped a string as one unit
  when the character immediately before its quote was non-alphanumeric
  (so `r"..."`'s `r` defeated it), plus a separate forward-looking
  prefix-letter regex with no notion of "already inside a string" (so a
  `t`/`T` letter that was actually part of another string's own escape
  sequence, e.g. the `t` in `r"\t"`, could be misdetected as a bare
  t-string's opening prefix). The new version determines, right at the
  quote, whether any real prefix before it contains `t`/`T`: if so, it uses
  the existing brace-depth-aware `_find_tstring_closing_quote` scan (for
  real t/f-string interpolation); otherwise it does a simple
  backslash-escape-aware scan to that string's own closing quote and
  treats the whole thing (prefix + quoted content) as one opaque unit.
  Prefix letters already appended to `result` character-by-character by
  the loop's fallback (before the dispatch recognizes them as part of a
  string) are removed via `del result[-len(prefix):]` and folded back in
  as part of the placeholder/ordinary-string unit.

Both prefix-detection implementations are now unified behind the one
shared `_string_prefix_start` helper — no duplicate heuristic remains.

### Quality gate results

- `python3 test_gimple.py`: 173 passed, 0 failed (added tests 170
  `raw_string_backslash_t_escape_then_another_string` and 171
  `tstring_nested_braces_still_works`, confirming both the fix and that
  legitimate nested-brace t/f-strings still work).
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes (`mojo.py` compiling its own source, 1/1).
- From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(jobs=8)`): 0 `skip <module>:` lines
  both before (stashed baseline) and after the fix — no regression, stdlib
  still compiles 100% clean.

### Manual verification

- Minimal repro (`ESCAPES = {r"\t": (1, ord("\t"))}`) via `python3 mojo.py
  run`: now runs and prints `{'\t': (1, 9)}` instead of raising
  `SyntaxError: ... Expected COLON got RPAREN`.
- `python3 mojo.py run /Users/mrs/net/Python-3.14.6/Lib/re/_parser.py`: the
  original `SyntaxError` from this bug is gone (confirmed directly via
  `mojo_compiler.py_tokenize` on the full file: tokenizes cleanly, 7638
  tokens, no exception). Running the file end-to-end now proceeds past
  parsing/tokenizing into interpretation and hits a distinct, unrelated,
  pre-existing interpreter bug (`UnboundLocalError: cannot access local
  variable 'mod' where it is not associated with a value` in
  `myinterpreter.py`'s `execute_FromImportStmt`, ~line 2638) — out of scope
  for this fix.
