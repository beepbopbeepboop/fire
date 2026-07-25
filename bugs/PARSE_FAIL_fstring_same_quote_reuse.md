# PARSE_FAIL/INTERP: f-string with a nested string reusing the outer quote character misparses

## Repro

```python
def g(a, b):
    return a + b

x = f'result: {g('a', 'b')}'
print(x)
```

- `python3 mojo.py run repro.py`: `NameError: name 'a' is not defined` —
  the f-string body is being cut off right at the reused `'` inside the
  `{...}` expression, leaving `a', 'b')}'` as trailing source text that
  gets misparsed as a bare identifier `a`.
- `python3 mojo.py build repro.py -o out`: `warning: f-string interpolation
  '{g(a,}' could not be compiled; emitting it as literal text` — same
  truncation, visible directly in the extracted interpolation text
  (`{g(a,}` is missing `'a', 'b')`).

Using a DIFFERENT quote character for the nested string (the pre-3.12
requirement) works correctly:
```python
x = f"result: {g('a', 'b')}"   # prints "result: ab" — fine
```
Only reusing the SAME quote character as the f-string's own delimiter
(legal since PEP 701 / Python 3.12) breaks.

## Root cause

`mojo_compiler.py`'s `_process_nested_tstrings` decides, per string it
finds, whether to use the brace-depth-aware closing-quote scan
(`_find_tstring_closing_quote`, which correctly walks through nested
`{...}` without being fooled by quote characters inside them) or the
plain simple-scan-to-matching-quote fallback (meant for ordinary,
non-interpolating strings). The decision (~line 731-736, added/adjusted by
this session's earlier `bugs/PARSE_FAIL_backslash_t_escape_misdetected_as_tstring_prefix.md`
fix, commit `6094d37`) is:

```python
has_t = any(c in ('t', 'T') for c in prefix)
if has_t:
    close = _find_tstring_closing_quote(stmt, i, qch)   # brace-aware
    ...
else:
    ... simple scan to the matching quote char ...
```

This checks ONLY for a literal `t`/`T` in the prefix — meant to identify
Mojo's own `t"..."` template-string literals (whose name gives this whole
function its "_process_nested_tstrings" name). But it's also being relied
on as the gate for whether ANY interpolating string (including a plain
`f"..."`) gets the brace-aware scan. An `f`-prefixed string has no `t`/`T`
in its prefix, so `has_t` is `False`, and it falls into the plain
simple-scan branch — which just looks for the next occurrence of the same
quote character, with no awareness of `{...}` at all. For
`f'result: {g('a', 'b')}'`, that means it stops at the very first `'`
inside the braces (the one opening `'a'`), truncating the f-string there.

## Suggested fix

The gate should trigger brace-aware scanning for BOTH `t` and `f` prefixes
(and any prefix containing either), not just `t` — i.e. check for `t`/`T`
OR `f`/`F` in the prefix, since both t-strings and f-strings use the same
`{expr}` interpolation syntax and both need quote-reuse-safe, brace-depth-aware
boundary detection. Double-check this doesn't regress the fix from
`6094d37` (which was specifically about distinguishing a real t/f-string
prefix from an ordinary string's own internal escape sequence, e.g. `r"\t"`'s
`\t`) — that fix's `_string_prefix_start` backward-scan logic for finding
the true prefix start should be unaffected either way, only the `has_t`
condition itself needs widening to `has_t_or_f`. Add coverage for f-strings
with same-quote-reused nested strings (both single- and double-quote
delimiter cases) alongside the existing t-string nested-brace test.

## Status
**Fixed**

`mojo_compiler.py` (~line 731-745, `_process_nested_tstrings`): widened the
brace-depth-aware-scan gate from `has_t = any(c in ('t', 'T') for c in
prefix)` to also check for `f`/`F`, renamed to `needs_brace_aware_scan`:

```python
needs_brace_aware_scan = any(c in ('t', 'T', 'f', 'F') for c in prefix)
if needs_brace_aware_scan:
    close = _find_tstring_closing_quote(stmt, i, qch)   # brace-aware
else:
    ... simple scan (ordinary, non-interpolating strings only) ...
```

`_find_tstring_closing_quote` itself needed no changes — it's already
generic (no t-specific behavior), so widening its gate is sufficient. As a
side effect, this also fixes the same truncation for `rf"..."`/`fr"..."`
raw-f-strings, which previously had no `t`/`T` in their prefix either and
were equally affected (not part of the original repro, but the same root
cause).

### Regression check (6094d37)

`6094d37`'s own fix and tests are unaffected: `r"\t"` has no `f`/`F`/`t`/`T`
reachable via this gate in a way that changes behavior — `r"\t"`'s prefix
is just `r`, which still correctly takes the simple-scan (ordinary-string)
branch exactly as before. `test_gimple.py`'s tests 170
(`raw_string_backslash_t_escape_then_another_string`) and 171
(`tstring_nested_braces_still_works`) both still pass.

### Tests added

- `test_gimple.py`: `fstring_nested_same_single_quote_reused` and
  `fstring_nested_same_double_quote_reused` (compile-only, both quote
  characters).
- `test_gimple_runner.py`: `gimple_fstring_same_quote_reused` — a real
  behavioral round-trip check (compiles AND runs, checked via
  `expected_return`), using `f'value: {len('ab')}'` then asserting
  `len(x) == len("value: 2")`, deliberately avoiding the interpolated
  value being a string (see "compiled-path caveat" below).

### Quality gate results

- `python3 test_gimple.py`: 183 passed, 0 failed.
- `python3 test_gimple_runner.py`: 11 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes (1/1, `mojo.py` compiling its own source).
- From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(jobs=8)`): 0 `skip <module>:` lines both
  before (stashed baseline) and after the fix — no regression.

### Manual verification

Minimal repro:
```python
def g(a, b):
    return a + b

x = f'result: {g('a', 'b')}'
print(x)
```
- `python3 mojo.py run`: now prints `result: ab` (previously
  `NameError: name 'a' is not defined`).
- `python3 mojo.py build` + run: the "could not be compiled" warning is
  gone and the interpolation compiles for real (previously
  `warning: f-string interpolation '{g(a,}' could not be compiled;
  emitting it as literal text`).

**Compiled-path caveat (pre-existing, unrelated, out of scope):** the
compiled binary for the *exact* minimal repro above prints garbage (e.g.
`result: 8726191384`) instead of `result: ab`, but this is NOT a
regression or a remaining part of this bug — it's a separate, pre-existing
bug in the compiled path's handling of f-string interpolation of a
run-time string value produced by concatenation (`a + b`). Confirmed by
reproducing the identical garbage output with a DIFFERENT nested quote
character (`f"result: {g('a', 'b')}"`, which "already works fine" per this
bug's original scope) and even with no nested call at all
(`y = g("a", "b"); x = f"result: {y}"`) — both hit the exact same garbage
output on `master` before this session's fix was applied at all (verified
via `git stash`). This f-string-quote-reuse fix itself is confirmed
correct: the "could not be compiled" warning it specifically targets is
gone, and a same-quote-reused interpolation whose value is an `Int` (not a
concatenated string), e.g. `f'value: {len('ab')}'`, compiles AND runs
correctly end-to-end (`value: 2`), isolating the two bugs from each other.

Real-world trigger check: `Lib/traceback.py`'s
`f'Ignored error getting __notes__: {_safe_string(e, '__notes__', repr)}'`
(~line 1072) — before this fix, `mojo_compiler.py_tokenize` mis-tokenized
this into three tokens (`STRING` truncated at the reused quote, a stray
`NAME __notes__`, and a second `STRING` for the remainder). After the fix,
it tokenizes as a single correct `STRING` token containing the whole
f-string, confirmed by direct token-stream inspection before/after (via
`git stash`).

### Final commit

`mojo_compiler.py`, `bugs/PARSE_FAIL_fstring_same_quote_reuse.md`,
`test_gimple.py`, `test_gimple_runner.py`.
