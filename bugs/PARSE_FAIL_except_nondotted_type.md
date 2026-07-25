# PARSE_FAIL: `except EXPR:` still fails when EXPR isn't NAME/KW-shaped at all (residual gap in today's except-type fix)

## Status
**Fixed** (2026-07-25)

## Reproduction
```mojo
def f():
    try:
        raise ValueError("x")
    except 42:
        print("wrong")
f()
```
Run: `python3 mojo.py run test.mojo`

## Previous (Buggy) Behavior
```
SyntaxError: test.mojo:4:7: Expected COLON got INT('42')
```

## Expected Behavior
Should parse successfully (real Python: this raises `TypeError: catching
classes that do not inherit from BaseException is not allowed` at
**runtime**, when the `except` clause is actually evaluated against a
non-exception-type value — but it's perfectly valid, parseable syntax; the
type position in Python's grammar accepts any `expression`, and Python
defers rejecting a non-exception-type value to runtime, not parse time).

## Root Cause
`bugs/PARSE_FAIL_except_call_expression_type.md`'s fix widened `_parse_try`
to fall back to a general expression parse (`self._parse_expr(...)`) when
the type position's initial `_parse_dotted_name()` fast-path attempt didn't
reach `COLON`/`as` — but that widening only triggered inside the branch
guarded by `elif self._peek().kind in ("NAME", "KW") and not
self._is_kw("as"):`. A bare `INT` token (`42`) never satisfied that guard
at all, so the whole branch was skipped, `exc_type` stayed `None`/unset, and
the very next line unconditionally did `self._expect("COLON")` — which
then failed immediately on the still-unconsumed `42`.

## Real-world impact
Confirmed via real CPython 3.14 stdlib source: `Lib/test/test_exceptions.py:2541`,
a real (intentional) test of Python's own runtime behavior for a
non-exception `except` type:
```python
with self.assertRaises(TypeError):
    try:
        raise ValueError
    except 42:
        pass
```

## Fix
`mojo_compiler.py`, `_parse_try`'s except-clause type-position parsing.
Widened the branch guard from
`elif self._peek().kind in ("NAME", "KW") and not self._is_kw("as"):`
to
`elif self._peek().kind != "COLON" and not self._is_kw("as"):`
— i.e. "attempt a type expression for anything that isn't unambiguously
'no type here'" (bare `except:`, already excluded via the `COLON` check)
and isn't the already-handled parenthesized-tuple-of-types branch (that's
a separate `if self._peek().kind == "LPAREN":` arm above, untouched).

Inside that widened branch, the dotted-name fast path is now only
attempted when the token is actually NAME/KW-shaped (`if self._peek().kind
in ("NAME", "KW"):`) — preserving the existing fast/common-case behavior
for `except ValueError:` and `except get_error_types():` byte-for-byte.
For every other token shape reaching that point (INT/FLOAT/STRING
literals, etc.), there's no dotted-name shape to even attempt, so the code
goes straight to the general expression parse
(`self._parse_expr(_KW_PREC['as'] + 1)`) — reusing the exact same
fallback call the prior fix already introduced, per CLAUDE.md's
"consolidate rather than invent parallel logic."

The interpreter side needed no changes — `execute_TryStmt`'s
`eval_expr(exc_type)` fallback already handles arbitrary expression nodes
(including literals) correctly once the parser started producing them for
this position.

## Verification
- Exact repro from this report: no longer raises `SyntaxError`. Parses
  successfully; at runtime the raised `ValueError` is not caught by
  `except 42:` (it propagates as an uncaught `ValueError: x`) — a sane,
  non-crashing outcome. This worktree's interpreter does not yet implement
  CPython's runtime `TypeError` check for a non-exception `except` type;
  that's a separate, pre-existing runtime-semantics gap outside this fix's
  scope (the fix here is about parsing, not about replicating CPython's
  exact runtime rejection of malformed except types).
- `except ValueError:` (bare name, unaffected — common case): prints
  `caught bare`. ✓
- `except (ValueError, TypeError):` (parenthesized tuple, prior work):
  unaffected — still hits the separate `LPAREN` branch, not touched here.
  Prints `caught tuple`. ✓
- `except ValueError as e:` (bare name + `as` binding, unaffected): prints
  `caught as boom`. ✓
- `except get_error_types() as e:` (call-expression type WITH an `as`
  binding): prints `caught call as boom`. ✓
- `except get_error_types():` (call-expression type, no `as`): prints
  `caught call`. ✓

All five cases above are byte-identical in output to their behavior before
this change (verified by direct re-run).

### Required full verification (mojo-reference quality gate for
mojo_compiler.py changes)
- `python3 test_gimple.py` → **161 passed, 0 failed**.
- `python3 test_module_cache.py` → **64 passed, 0 failed**.
- `make check-selfhost` → **PASS** (`test_selfhost.py`: 1 passed, 0 failed;
  "self-host compiles + links clean").
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Output: **0** (no regression; dylib built successfully at
  `build/libmojostdlib.dylib`).

## Files Changed
- `mojo_compiler.py` — `_parse_try`'s except-clause type-position parsing:
  widened the branch guard to cover any non-`COLON`, non-`as` token shape
  (not just NAME/KW), while still preferring the dotted-name fast path when
  the token actually is NAME/KW-shaped.
