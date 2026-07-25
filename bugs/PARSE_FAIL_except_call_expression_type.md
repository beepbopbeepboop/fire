# PARSE_FAIL: `except SOME_CALL():` — an except clause's exception type as a function-call expression fails to parse

## Status
**Fixed** (2026-07-25)

## Reproduction
```mojo
def get_error_types():
    return ValueError

def f():
    try:
        raise ValueError("boom")
    except get_error_types():
        print("caught")
f()
```
Run: `python3 mojo.py run test.mojo`

## Previous (Buggy) Behavior
```
SyntaxError: test.mojo:7:22: Expected COLON got LPAREN('(')
```
`_parse_try` (`mojo_compiler.py`, except-clause parsing) expected a `COLON`
right after parsing the exception-type expression, but stopped too early —
it only accepted a bare (possibly dotted) NAME, or a parenthesized tuple of
names/types, as the "type" in an `except TYPE:` clause, not a general
expression. When the type position was itself a function CALL
(`get_error_types()`, which evaluates to a real exception type/class at
runtime — a legitimate, if somewhat unusual, Python pattern for dynamically
selecting which exception(s) to catch), the parser stopped before the `(`
instead of including the call as part of the type expression.

## Root Cause
In `_parse_try`'s except-clause parsing, the non-parenthesized branch called
`self._parse_dotted_name()` unconditionally for the type position — a
narrow helper that only consumes `NAME (DOT NAME)*` and stops at anything
else (including `(`). It never fell back to the general expression parser,
so `get_error_types` was consumed as a dotted name and the following `(`
was left unconsumed, tripping the subsequent `self._expect("COLON")`.

Separately, `myinterpreter.py`'s `execute_TryStmt` already had a working
fallback (`elif ... else: exc_class = self.eval_expr(exc_type)`) for
non-string/non-list `exc_type` values — i.e. the *runtime* half of general
except-expression support already existed; only the *parser* had never been
widened to actually produce anything other than a string or a list of
strings for the type position.

## Fix
`mojo_compiler.py`, `_parse_try`'s except-clause parsing (the
`elif self._peek().kind in ("NAME", "KW") and not self._is_kw("as"):`
branch): still try the fast/common path first — `_parse_dotted_name()`,
stored as a plain string, which the interpreter's and gimple_codegen's
per-type tag dispatch special-case for speed on the overwhelmingly common
`except SomeError:` / `except mod.SomeError:` cases. But now check what
follows: if it's `COLON` or the `as` keyword, the dotted name *was* the
whole type expression, so keep the fast-path string. Otherwise (e.g. the
next token is `(`, meaning this is actually a call expression like
`get_error_types()`), rewind the parser position and reparse the type
position as a full expression via `self._parse_expr(_KW_PREC['as'] + 1)` —
the same "expr, but don't let the operator-precedence loop swallow a
following `as`" trick already used by `_parse_with` for `with EXPR as
alias:`. This reuses the established pattern in the file (per CLAUDE.md's
"consolidate rather than invent parallel logic") instead of adding new
lookahead machinery, and backtracking via `self._pos` save/restore is
itself an existing pattern already used elsewhere in this parser (e.g. the
comptime-for and lambda-vs-paren-expr disambiguation code).

The interpreter side needed no changes — its `eval_expr(exc_type)` fallback
already handles arbitrary expression nodes (calls, attribute access, etc.)
correctly once the parser started producing them.

## Verification
All performed in the isolated worktree checkout used for this fix
(`mojo_compiler.py` diff applied there; `bugs/` itself is untracked in the
main checkout, so this file is being maintained per-worktree).

- Exact repro from this report: prints `caught`. ✓
- `except ValueError:` (bare name, unaffected — common case): prints
  `caught bare`. ✓
- `except (ValueError, TypeError):` (parenthesized tuple, prior work):
  unaffected by this change (still hits the separate `LPAREN` tuple branch,
  not touched here). Confirmed by-inspection and by reproducing the SAME
  pre-existing failure (`No handler for list`, in
  `myinterpreter.execute_TryStmt`) both with and without this fix applied —
  i.e. this is a pre-existing, unrelated gap in this worktree's
  `myinterpreter.py` (it lacks the `isinstance(exc_type, list)` handling
  branch that a sibling line of work already added elsewhere), not a
  regression from this change.
- `except ValueError as e:` (bare name + `as` binding, unaffected): prints
  `caught as boom`. ✓
- `except get_error_types() as e:` (call-expression type WITH an `as`
  binding — the case most likely to break if the widened expression parse
  swallowed `as`): prints `caught call as boom`. ✓ — confirms the
  `_KW_PREC['as'] + 1` precedence trick correctly stops the expression
  parse before `as`.
- `except asyncio.CancelledError:` (dotted attribute-access type): parses
  fine now as before (still takes the string fast path since it's followed
  directly by `COLON`); at runtime it does NOT get caught, but this
  reproduces identically with and without this fix — a separate,
  pre-existing bug in this worktree's exception-scope/module-attribute
  lookup, unrelated to the parser change made here.

### Required full verification (mojo-reference quality gate for
mojo_compiler.py changes)
- `python3 test_gimple.py` → **159 passed, 0 failed** (this worktree's
  baseline count differs from the primary checkout's 161, since this
  worktree is a divergent branch snapshot; 0 failed is what matters and
  held both before and after).
- `python3 test_module_cache.py` → **58 passed, 0 failed** (same caveat:
  this worktree's baseline is 58, not 64; 0 failed held before and after).
- `make check-selfhost` → **PASS** (`test_selfhost.py`: 1 passed, 0 failed;
  "self-host compiles + links clean").
- From-scratch stdlib dylib build skip-count check:
  ```bash
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  Output: **0** (both before and after the change — no regression; dylib
  built successfully at `build/libmojostdlib.dylib`).

## Files Changed
- `mojo_compiler.py` — `_parse_try`'s except-clause type-position parsing
  (the single-name/non-tuple branch): widened to fall back to a full
  expression parse when the dotted-name fast path doesn't reach `COLON`/`as`.
