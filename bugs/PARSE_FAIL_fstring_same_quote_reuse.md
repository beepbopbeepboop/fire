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
