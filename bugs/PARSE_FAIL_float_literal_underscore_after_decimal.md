# PARSE_FAIL: underscore digit-separators unsupported after the decimal point in a float literal

## Status
**Fixed 2026-07-20.**

## Fix
`mojo_compiler.py`'s `_TOKEN_RE`, the `FLOAT` group: the fractional-digits
alternative was `\d[\d_]*\.\d*(?:[eE][+-]?\d+)?` — the `\d*` right after the
decimal point had no `_` in its character class (unlike the integer part's
`[\d_]*` just before it), so matching stopped at the decimal digits and left
an underscore-prefixed remainder to be re-tokenized as a bogus `NAME`.
Changed to `\d[\d_]*\.[\d_]*(?:[eE][+-]?\d[\d_]*)?|\.\d[\d_]*(?:[eE][+-]?\d[\d_]*)?|\d[\d_]*[eE][+-]?\d[\d_]*`
— underscores now allowed in the fractional digits and (as a side effect of
also fixing the shared exponent-digit subpattern) the exponent digits too.
No downstream change needed: `float(t.value)` already strips underscores
natively (PEP 515).

Verified: `2.50908_09287` → `2.5090809287`; the real `statistics.py`
constant `2.50908_09287_30122_6727e+3` → `2509.0809287301227`; `3.14`,
`1_000`, `1_000e+3`, `2.5e+3` (pre-existing working cases) unaffected;
`1.5e1_0` (underscore in the exponent) also now works. Full quality gate:
`test_gimple.py` 161/161, `test_module_cache.py` 64/64, `make check-selfhost`
clean, from-scratch stdlib dylib build: 0 skipped modules (unchanged).

_(original report below)_

## Status (original)
Open (found 2026-07-20, re-testing the backlog for still-live parser/tokenizer bugs)

## Reproduction
```mojo
def f():
    var x = 2.50908_09287
    print(x)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
NameError: test.mojo:2:15: name '_09287' is not defined
```
The tokenizer reads `2.50908` as a complete float literal, then treats the
literal underscore-prefixed remainder `_09287` as a SEPARATE identifier
token (implicitly multiplied/juxtaposed, or just a syntax quirk that happens
to parse as two separate expression tokens rather than erroring immediately)
— it is never included in the numeric literal.

## Narrowed root cause (confirmed via isolation)
- Underscore separators in the INTEGER part of a literal work fine:
  `1_000` parses correctly, and even `1_000e+3` (underscore in the integer
  part + a scientific-notation exponent, no decimal point at all) parses and
  evaluates correctly to `1000000.0`.
- A plain scientific-notation float with no underscores works fine:
  `2.5e+3` → `2500.0`.
- The bug is specifically: an underscore appearing AFTER the decimal point
  (in the fractional digits) breaks tokenization, regardless of whether a
  scientific-notation exponent is also present. `2.50908_09287` (no
  exponent) fails exactly like `2.50908_09287_30122_6727e+3` (with one)
  fails — the exponent is not what triggers it.

## Expected Behavior
`2.50908_09287` should tokenize as a single float literal equal to
`2.5090809287`, matching Python's number-literal grammar (underscores are
legal between any two digits in the integer part, the fractional part, and
the exponent part of a numeric literal, purely for readability — they carry
no semantic meaning and are stripped before parsing the digits).

## Relationship to prior work
Found via `bugs/PARSE_FAIL_statistics.md` in this same directory (the
original stdlib-scan report for this exact literal shape, from
`Lib/statistics.py`'s `2.50908_09287_30122_6727e+3` — a real constant in
that file's Wichura AS 241 algorithm implementation). That report only
recorded the raw parser traceback, not a root-caused diagnosis; this report
supersedes it with the narrowed reproduction above.

## Files Likely Affected
- `mojo_compiler.py` (or wherever tokenization/lexing lives, if separate —
  check `py_tokenize`) — the numeric-literal scanning logic. Search for
  wherever it currently strips/allows underscores in a number (since integer
  and exponent-adjacent-to-integer cases already work, there is presumably
  an underscore-stripping step somewhere before/around the decimal point
  that doesn't continue past it) and extend it to also consume underscores
  in the fractional part.
