# INTERP: dict/set `**`-unpacking parses but crashes at runtime (NotImplementedError)

## Status
**Fixed** (2026-07-20)

## Fix
Two bugs, not one:

1. **Parser misclassification (`mojo_compiler.py`, `_parse_dict_or_set`,
   around line 2861).** `{**a, **b}` was never actually reaching a `DictExpr`
   at runtime — the dict-vs-set disambiguation only recognized `{key: value}`
   (via a `COLON` peek after the first element) as "this is a dict"; a `**`-led
   first element has no `COLON`, so it fell through to the generic
   `elems`-collecting loop and got returned as a `SetExpr` containing two
   `UnaryOp(op='**')` "elements". `PARSE_FAIL_double_star_unpacking.md`'s
   fix only taught `_parse_unary` to tokenize `**expr` into a `UnaryOp` at
   all (fixing "Unexpected OP('**')"); it didn't teach the dict/set literal
   parser to route a `**`-prefixed first entry to `DictExpr` instead of
   `SetExpr`. Fixed by adding an explicit `isinstance(first, UnaryOp) and
   first.op == "**"` branch in `_parse_dict_or_set` that builds a `DictExpr`
   with the spread stored as a `(UnaryOp, None)` pair, plus a new
   `_parse_dict_entry()` helper (parses either a `**expr` spread or an
   ordinary `key: value` pair) reused by both the `COLON`-first and
   `**`-first dict branches — so `{"x": 1, **b}` (spread *after* a regular
   key) also now parses as a dict instead of erroring on a missing `COLON`.

2. **No runtime spread support (`myinterpreter.py`).** Even once correctly
   typed as `DictExpr`/`ListExpr`/`SetExpr`/`TupleExpr`, nothing expanded a
   `UnaryOp(op='*'|'**')` element — `eval_UnaryOp` doesn't (and correctly
   shouldn't) implement `*`/`**` as generic unary operators, since spreading
   isn't a single-value operation. Fixed by adding a `_spread_operand(node,
   op)` helper and rewriting all four collection-literal evaluators —
   `eval_ListLiteral`, `eval_DictLiteral`, `eval_SetLiteral`,
   `eval_TupleLiteral` (~myinterpreter.py:3384-3448) — to recognize a
   spread-marked element/pair and expand/merge it instead of evaluating it
   as one ordinary member. `eval_TupleExpr` was a separate, duplicate,
   non-spread-aware implementation of the same logic as `eval_TupleLiteral`
   (which is the same AST node — `mojo_compiler.py` aliases `TupleLiteral =
   TupleExpr`); consolidated it to just delegate, per this repo's
   no-duplicate-implementations convention.

   Dict-merge semantics match Python: pairs/spreads are applied in source
   order, so a later spread or key wins on collision.

   Also patched `mojo_compiler.py`'s `emit()` pretty-printer (the `DictExpr`
   case) to format a spread pair as just `**expr` instead of the bogus
   `**expr: None` it would have produced now that `DictExpr.pairs` can
   contain `(spread, None)` entries — this path wasn't reachable before fix
   #1 landed (spreads were never in a `DictExpr` to begin with).

**Verified working end-to-end** (`python3 mojo.py run`):
- dict spread: `{**a, **b}` (overlapping keys — later wins), `{**{}, "k": 1}`
  (empty-dict spread), `{"x": 1, **b}` (spread after a regular key), plain
  `{"a": 1, "b": 2}` (no regression)
- list spread: `[*a, *b]`
- set spread: `{*a, *b}`
- tuple spread: `(*a, *b)`

All four collection kinds' spread syntax already parsed structurally before
this fix (list/set/tuple elements are flat lists that already accepted a
`UnaryOp(op='*')` member without special-casing) — only dict needed the
parser-classification fix in addition to the shared runtime fix.

Full suite: `python3 test_gimple.py` — 160 passed, 0 failed (unchanged from
before this fix). `test_myinterpreter.py`, `test_myinterpreter_simple.py`,
`test_myinterpreter_validation.py` all fail to even import/load in this
checkout (`ModuleNotFoundError: No module named 'parser'`,
`FileNotFoundError: mojo/ast_nodes.mojo`) — confirmed pre-existing via `git
stash`, unrelated to this change.

_(original report below)_

## Status (original)
Open (found 2026-07-20, re-testing the backlog for still-live interpreter bugs)

## Reproduction
```mojo
def f():
    var a = {"x": 1}
    var b = {"y": 2}
    var c = {**a, **b}
    print(c["x"])
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
NotImplementedError: test.mojo:0:0: Unary operator * not implemented
```
(raised from `myinterpreter.py`'s `eval_UnaryOp`)

## Expected Behavior
`c` should be `{"x": 1, "y": 2}`.

## Root Cause / Relationship to prior work
`PARSE_FAIL_double_star_unpacking.md` (this same directory) documents `{**a,
**b}` as "Fixed (2026-07-15)" — and the *parsing* genuinely is fixed (`**`
now lexes/parses as a spread inside a dict literal, per that doc's own
description of the fix in `mojo_compiler.py`'s `_parse_unary`). But the
**interpreter never gained a matching runtime implementation** — the AST
node produced by that parse (apparently a `UnaryOp` with `op='*'`/`'**'`
wrapping the spread operand, used inside a dict/set/list display) has no
handler in `myinterpreter.py`'s `eval_UnaryOp`, so any code that actually
*executes* a double-star (or single-star, in a list/tuple/set display)
spread crashes immediately. The parse-fix doc's "Fixed" status is misleading
without a runtime companion fix — this is why direct re-testing (not just
trusting an existing doc) matters.

## Files Likely Affected
- `myinterpreter.py` — `eval_UnaryOp` (needs a case for the spread operator
  inside collection displays; likely needs to be handled at the
  dict/set/list-literal construction site instead of as a generic unary op,
  since "unwrap and merge/extend" isn't a single-value unary operation).
