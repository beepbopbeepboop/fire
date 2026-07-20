# INTERP: `f(*args)` call-site star-unpacking is silently ignored — wrong results, no error

## Status
**Fixed 2026-07-20.**
**Severity: high — silent wrong output, not a crash.**

## Reproduction
```mojo
def g(a, b, c):
    print(a, b, c)
def f():
    var args = [1, 2, 3]
    g(*args)
f()
```
Run: `python3 mojo.py run test.mojo`

Before the fix this printed `[1, 2, 3] None None` (the whole list bound to
`a`, `b`/`c` left unbound); after the fix it prints `1 2 3`.

## Root Cause (confirmed)
Two bugs stacked:

1. **Parser dropped the star marker entirely.** In `mojo_compiler.py`'s
   `LPAREN` call-argument-list parser (the `elif t.kind == "LPAREN":` branch
   around line 2585), the loop that builds a call's `args` list explicitly
   special-cased `*`/`**` tokens: it consumed the star token itself and then
   called `self._parse_expr(0)` on the remainder, appending the bare operand
   expression with no record that it had been starred. Elsewhere in the same
   file, `_parse_unary` *already* handles a leading `*`/`**` by wrapping the
   operand in `UnaryOp(op='*'|'**', operand=...)` — but the call-arg loop's
   manual token-consumption bypassed that path, so the AST for `g(*args)`
   was indistinguishable from `g(args)`.
2. **Interpreter had no splice logic even if the marker had survived.**
   `myinterpreter.py`'s `eval_CallExpr` built `args` via a flat
   `[self.eval_expr(arg) for arg in expr.args]` — one Python value per AST
   node, unconditionally — so even a correctly-marked starred argument would
   still have collapsed to a single positional value.

## Fix
- `mojo_compiler.py` (~line 2589, the `LPAREN` call-arg loop): removed the
  two `**`/`*` special cases that manually skipped the star token and
  discarded the marker. Now `*expr`/`**expr` call arguments fall through to
  the same `self._parse_expr(0)` used for every other argument, which lets
  `_parse_unary` wrap them in `UnaryOp(op='*'|'**', operand=...)` as it
  already does elsewhere — the marker now survives into the `CallExpr.args`
  AST.
- `myinterpreter.py`'s `eval_CallExpr` (~line 3534): replaced the flat
  list-comprehension with a loop over `expr.args` that detects
  `UnaryOp(op='*', ...)` and splices `eval_expr(operand)`'s elements into
  the flat `args` list via `args.extend(...)`, and detects
  `UnaryOp(op='**', ...)` and merges `eval_expr(operand)`'s items into
  `kwargs` via `kwargs.update(...)`, instead of appending the whole
  iterable/mapping as one ordinary argument value.

## Verification
All run via `python3 mojo.py run <file>.mojo`, checking exact printed output:

- **`*args`-only-position** (original repro, `g(*args)` with `args = [1,2,3]`
  and `def g(a, b, c)`): now prints `1 2 3` (was `[1, 2, 3] None None`). Fixed.
- **`*args`-mixed-position, leading**: `g(1, *rest)` with `rest = [2, 3]`,
  `def g(a, b, c)` → prints `1 2 3`. Fixed.
- **`*args`-mixed-position, middle** (`g(a_val, *rest, tail)`): `g(1, *rest, 4)`
  with `rest = [2, 3]`, `def g(a, b, c, d)` → prints `1 2 3 4`. The parser
  does allow a star in the middle of a call's argument list (no separate
  pre-existing limitation here); confirmed working.
- **`**kwargs` call-site unpacking** (`g(**opts)` with
  `opts = {"a": 1, "b": 2, "c": 3}`, `def g(a, b, c)`): prints `1 2 3`.
  Verified working — same detection mechanism (`UnaryOp(op='**', ...)`)
  reused in both the parser and `eval_CallExpr`; no separate kwarg-binding
  infrastructure was needed since `MojoFunction._invoke` already accepted
  a `kwargs` dict (it was just never populated by this call site before).
  Not a follow-up — fixed in the same change.
- **Arity mismatch, too many unpacked** (`g(*args)` with 4-element `args`,
  3-param `g`): prints `1 2 3`, extra element silently dropped. This matches
  pre-existing interpreter behavior for a plain (non-overloaded) function
  called with too many *ordinary* positional args (`g(1, 2, 3, 4)` also
  silently drops the 4th and prints `1 2 3`) — `MojoFunction._invoke` has no
  arity check at all for non-overloaded functions, so the starred path
  intentionally matches that existing (lenient, no-error) style rather than
  inventing a new diagnostic. `MojoOverloadSet` (used when a name has
  multiple `def` overloads) does raise `_NoOverloadMatch` on no-arity-match,
  and that path is unaffected/unchanged by this fix.
- **Arity mismatch, too few unpacked** (`g(*args)` with 2-element `args`,
  3-param `g`): prints `1 2 None`, matching the pre-existing behavior of
  `g(1, 2)` (also `1 2 None`) — missing params default to `None`, same as
  before.
- **Ordinary non-starred call unchanged** (`g(1, 2, 3)`): prints `1 2 3`,
  byte-identical to pre-fix behavior.

## Test suites
- `python3 test_gimple.py`: 160 passed, 0 failed (unchanged from baseline).
- `test_myinterpreter*.py` / `test_phase2_parser*.py`: fail before *and*
  after this change with unrelated pre-existing errors (`ModuleNotFoundError:
  parser`, `ModuleNotFoundError: ast_nodes`, missing `mojo/ast_nodes.mojo`
  fixture file) — confirmed via `git stash` that these failures pre-date this
  fix and are not caused by it.
- `test_kwargs_stmt.py`, `test_dispatch_myinterpreter.py`: run clean.

## Related
`INTERP_dict_double_star_unpack_runtime.md` in this directory covers
`**`-unpacking INSIDE a dict/set/list literal display — a different code
path (`eval_ListLiteral`/`eval_DictLiteral`/`eval_SetLiteral`, none of which
currently splice a `UnaryOp('*'|'**', ...)` element) than this call-argument
fix. Not addressed here — still open if unresolved separately.
