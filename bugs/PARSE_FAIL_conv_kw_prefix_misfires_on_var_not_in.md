# PARSE_FAIL: `var`/`ref`/other convention keywords used as an identifier inside `(... not in ...)` misparse

## Status
**Fixed** (2026-07-25)

## Fix
`mojo_compiler.py`'s `_parse_primary` `LPAREN` branch (~line 3135-3155):
tightened the ownership/convention-prefix carve-out's lookahead. It
previously fired whenever the token after a `_CONV_KWS` keyword was merely
NAME-or-KW-shaped, which a keyword-shaped operator like `not` also
satisfies. A genuine parenthesized binding target is always exactly
`(CONV_KW name)` — the keyword, one name-like token, then the closing
`RPAREN` — so the check now also requires `self._peek(2).kind == "RPAREN"`
before advancing past the keyword. This disambiguates `(var x)` (a real
binding target, still consumed) from `(var not in lst)` (`var` used as an
ordinary identifier, now left alone so `_parse_primary`'s existing
KW-as-identifier fallback picks it up). The fix is uniform across all of
`_CONV_KWS` (`ref`, `out`, `mut`, `var`, `deinit`, `read`, `inout`,
`borrowed`, `owned`) since it only changes the shared lookahead, not any
per-keyword logic — verified each one individually still works as a plain
identifier in an `assert(KW not in ...)`-shaped call.

The other 4 `_CONV_KWS` call sites (`_parse_for` ~1999, `_parse_funcdef`
~2069/~2099, `_parse_comptime_for` ~2581) already have their own
(non-identical) disambiguation guards and were not touched — they were
read to confirm this fix doesn't change their behavior, not because they
share this exact bug. (`_parse_comptime_for`'s guard at ~2581 looks
narrower than the others — no check against `in`/`:` following — but that
is a separate, pre-existing potential gap out of scope for this fix.)

### Verification
- Exact repro (`def f(var, lst): assert(var not in lst)`) now runs clean,
  no SyntaxError, for `python3 mojo.py run`.
- Confirmed for all 9 `_CONV_KWS` members via a parametrized manual check
  (`assert(KW not in seen)` for each of `ref out mut deinit read inout
  borrowed owned` in addition to `var`) — all parse and run correctly.
- Legitimate binding-target case still works: `(var x), (var y) =
  get_pair()` runs and prints the unpacked values correctly (both via
  `mojo.py run` and as a new `test_gimple.py` compiled-path case).
- `Tools/cases_generator/stack.py` (the original real-stdlib trigger, see
  `bugs/PARSE_FAIL_Tools_cases_generator_stack.md`): the `var not in`
  SyntaxError at line 286 is gone. Parsing now proceeds much further and
  fails at line 321 (`Expected NAME or KW got DOT('.')`, inside an
  unrelated `struct`/`def` parse) — a separate, pre-existing issue in this
  large real file, out of scope for this bug.
- Added two `test_gimple.py` cases: `conv_kw_as_plain_ident_not_in` (the
  fixed misparse, for `var` and `read`) and
  `conv_kw_prefix_tuple_unpack_still_works` (the legitimate binding-target
  case). `python3 test_gimple.py`: 165 passed, 0 failed (up from 163).
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: 1 passed, 0 failed.
- From-scratch stdlib dylib build skip-count: `0` skips before (baseline
  via `git stash`) and `0` after — no regression.

_(original report below)_

## Repro

```python
def f(var, lst):
    assert(var not in lst)
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:2:18: Expected RPAREN got NAME('lst')
```

Also reproduces in real stdlib source, e.g. `Tools/cases_generator/stack.py:286`:
```python
def push(self, var: Local) -> None:
    assert(var not in self.variables), var
```
(`bugs/PARSE_FAIL_Tools_cases_generator_stack.md`)

## Root cause

`mojo_compiler.py:3135-3161` (`_parse_primary`'s `LPAREN` branch) has a
carve-out for an ownership/convention prefix inside a parenthesized binding
target — e.g. `(var x), (ref y) = ...`:

```python
if (self._peek().kind == "KW" and self._peek().value in self._CONV_KWS
        and self._peek(1).kind in ("NAME", "KW")):
    self._advance()
```

`_CONV_KWS = {'ref', 'out', 'mut', 'var', 'deinit', 'read', 'inout',
'borrowed', 'owned'}` (`mojo_compiler.py:2035`).

This only checks that the token *after* the convention keyword is
NAME-or-KW-shaped — it doesn't check that what follows actually looks like
a bound identifier in a binding-target position (i.e., that the parenthesized
group is exactly `(CONV_KW name)`, or that an `=`/`,` binding follows later).
So for `(var not in lst)`:

- `self._peek()` is `KW('var')` → in `_CONV_KWS`.
- `self._peek(1)` is `KW('not')` → its `.kind` is `"KW"`, satisfying the
  `("NAME", "KW")` check.

...so the branch wrongly fires, silently consuming/discarding `var` as if it
were a convention-prefix keyword. Parsing then continues from `not`, which
`_parse_expr` treats as its (unrelated) unary-`not` prefix operator; the
operand parse falls into `_parse_primary`'s generic `KW`-as-identifier
fallback and treats `in` itself as a bare identifier (since nothing there
recognizes `in` specially outside the comparison-operator loop), leaving
`lst` dangling and un-consumed when the enclosing `(...)` in `_parse_assert`
expects its closing `RPAREN`.

## Suggested fix

Match the disambiguation style already used for the `fn`/`struct`/`enum`
keyword-vs-identifier collisions (see commits `bd2227c`, `4179ac7`,
`7e4a397`): require a tighter, positive shape before committing to the
convention-prefix reading. A parenthesized binding target of this form is
always exactly `(CONV_KW name)` — i.e. the convention keyword, then a single
name-like token, then the closing `RPAREN` — so also checking
`self._peek(2).kind == "RPAREN"` before advancing should disambiguate
`(var x)` (a real binding target) from `(var not in lst)` (`var` used as a
plain identifier that happens to be followed by another keyword-token
operator). Verify this doesn't regress the legitimate multi-target case
`(var x), (ref y) = ...` mentioned in the surrounding comment, and check
whether any of `_CONV_KWS`'s other members (`ref`, `mut`, `out`, `deinit`,
`read`, `inout`, `borrowed`, `owned`) have the same collision with real
Python code using them as plain identifiers (e.g. `assert(read not in
seen)`), and add regression coverage for those too if so.
