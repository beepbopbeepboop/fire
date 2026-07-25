# PARSE_FAIL: `var`/other convention keywords as a for-loop tuple-target element misparse

## Status
**Fixed** (2026-07-25)

## Fix
`mojo_compiler.py`'s `_parse_for` (~line 2025-2028): added a `peek(1).kind
!= "COMMA"` exclusion alongside the existing `KW('in')`/`COLON` exclusions
in the convention-keyword carve-out, so `for var, other_var in pairs:`
(where `var` is just the first plain tuple-unpack target, not a genuine
convention prefix) no longer swallows `var` as a bogus prefix.

`_parse_comptime_for` (~line 2604-2617) had no guard at all — it
unconditionally consumed any leading `_CONV_KWS` token. Gave it the exact
same three-way exclusion (`in`/`:`/`,`) used by `_parse_for`, bringing it in
line with its already-fixed sibling.

Reviewed the other `_CONV_KWS` call sites (`_parse_funcdef`'s two param-list
loops at ~2095/~2125, and `_parse_primary`'s `LPAREN` binding-target carve-out
at ~3176): the funcdef sites already break on `COLON`/`ASSIGN`/`COMMA`/`RPAREN`
following, and the `LPAREN` site already requires `peek(2) == RPAREN` (fixed
by commit `7537794`) — none of them have this missing-exclusion gap.

### Verification
- Minimal repro (`for var, other_var in pairs: print(var, other_var)`) now
  runs clean via `python3 mojo.py run`, printing the unpacked pairs.
- `Tools/cases_generator/stack.py` (the real-stdlib trigger, line 606): the
  `Expected KW got NAME('other_var')` error is gone; the file now parses
  and runs to completion cleanly (`python3 mojo.py run`, exit 0, no further
  errors surfaced).
- Added `test_gimple.py` cases 167-169: `var_as_for_loop_target_comma`,
  `var_as_comptime_for_loop_target_comma` (the two fixed misparses), and
  `conv_kw_prefix_for_loop_target_still_works` (confirms the legitimate
  convention-prefixed for-loop target, `for ref x in items:`, still parses
  — its `peek(1)` is a plain NAME, matching none of the exclusions).
  `python3 test_gimple.py`: 171 passed, 0 failed (up from 168).
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: 1 passed, 0 failed.
- From-scratch stdlib dylib build skip-count: `0` before (via `git stash`)
  and `0` after — no regression (already at the "every stdlib file
  compiles" ceiling from the prior boxing-stub regression fix).

_(original report below)_

## Repro

```python
def f(pairs):
    for var, other_var in pairs:
        print(var, other_var)
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:2:9: Expected KW got NAME('other_var')
```

Real stdlib trigger: `Tools/cases_generator/stack.py:606`:
```python
for var, other_var in zip(self.inputs, other.inputs):
    if var.in_local != other_var.in_local:
```
This is the file's THIRD `var`-as-identifier bug found this session — the
first two (`assert(var not in self.variables)` at line 286, and
`var.in_local`/`var.memory_offset = var_offset` at line 321) were fixed by
commits `7537794` and `ebe8546` respectively; that second fix's own report
noted this remaining line-606 failure as a separate, different call site.

## Root cause

`mojo_compiler.py`'s `_parse_for` (~line 2011-2028) has a convention-keyword
carve-out with a comment explaining it was *already* tightened once before
to exclude the `for var in (...):` case (checking that `peek(1)` isn't
`KW('in')` and isn't `COLON`):

```python
if (self._peek().kind == "KW" and self._peek().value in self._CONV_KWS
        and not (self._peek(1).kind == "KW" and self._peek(1).value == "in")
        and self._peek(1).kind != "COLON"):
    self._advance()
```

But it doesn't exclude `COMMA`. So `for var, other_var in pairs:` — where
`var` is just the first element of a plain tuple-unpacking target, not a
convention prefix — still wrongly swallows `var` as a bogus prefix (since
`peek(1)` is `COMMA`, matching neither of the two exclusions), then
`_parse_unpack_target()` starts from the comma itself and everything after
misparses.

`_parse_comptime_for` (~line 2604-2608) has the exact same bug in a more
severe form — it has NO guard at all:

```python
def _parse_comptime_for(self):
    self._expect("KW","for")
    # Optional convention keyword (var, ref, ...) before the target
    if self._peek().kind == "KW" and self._peek().value in self._CONV_KWS:
        self._advance()
    # Support tuple targets: comptime for i, j in product(...)
    target = self._ident()
```
This always swallows a leading `_CONV_KWS` token unconditionally, so
`comptime for var in ...` or `comptime for var, j in ...` (either shape)
misparses whenever the loop variable happens to be named `var`/`ref`/etc.
(A previous session's fix report — `bugs/PARSE_FAIL_conv_kw_prefix_misfires_on_var_not_in.md`
— already flagged this specific site as "a separate, pre-existing potential
gap out of scope" for that earlier fix.)

## Suggested fix

For `_parse_for`: add `COMMA` to the existing exclusion list (`not (peek(1)
== KW('in')) and peek(1) != COLON and peek(1) != COMMA`), following the
same reasoning already in the comment there — a real convention-prefixed
for-loop target is `for CONV_KW name in ...`, so if `name` is immediately
followed by `,` it must actually be a plain identifier appearing as one of
several unpacking targets, not a name preceded by a discardable prefix.

For `_parse_comptime_for`: apply the same disambiguation used in
`_parse_for` (excluding `in`/`:`/`,` following) rather than leaving it
unconditional — bring it in line with the already-fixed sibling.

Also worth a final consistency sweep across ALL remaining `_CONV_KWS` call
sites (`mojo_compiler.py` — grep `_CONV_KWS` for the full list, several were
already fixed/verified this session for the `LPAREN`/statement-level/`for`
cases) to confirm none of the others have the same missing-exclusion
pattern, since this collision (`var` as an everyday identifier) keeps
recurring across independently-written call sites.
