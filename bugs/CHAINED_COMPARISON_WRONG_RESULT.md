# INTERP: chained comparisons (`a < b < c`) evaluate incorrectly — silent wrong result, no error

## Status
**FIXED (2026-07-20).** Root cause confirmed as suspected: `mojo_compiler.py`'s
parser folded a chain of comparison operators into nested `BinaryOp` nodes
(`(0 < y) < 10`), so a comparison's boolean result got fed back in as an
operand to the next comparison. Fixed with a dedicated `CompareChain` AST
node plus short-circuit, evaluate-once-per-operand lowering in both the
interpreter and the compiled (gimple) path. See "Fix" section below.
(Originally found 2026-07-20 by the case-guard-clause fix's own test sweep,
re-tested and confirmed directly against `mojo.py run`.)
**Severity was high — silent wrong output, not a crash.**

## Reproduction
```mojo
def f():
    var x = 5
    if 0 < x < 10:
        print("in range")
    else:
        print("out of range")
    var y = 15
    if 0 < y < 10:
        print("in range")
    else:
        print("out of range")
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
in range
in range
```
(both print "in range", even though `y = 15` is NOT between 0 and 10.)

## Expected Behavior
```
in range
out of range
```

## Root Cause (suspected)
Python's chained comparison `a < b < c` means `(a < b) and (b < c)` — each
operand is evaluated once, and the expression short-circuits to `False` as
soon as one link fails, WITHOUT re-evaluating the middle operand. This is
NOT the same as normal left-associative binary-operator chaining. The
symptom (`0 < 15 < 10` evaluating true) matches exactly what you'd get if
the chain were instead evaluated as ONE describable-in-terms-of-simple-binops
tree — e.g. `(0 < y) < 10` → `True < 10` → `1 < 10` → `True` — i.e. the
comparison chain is being parsed/evaluated as ordinary nested binary
operators (each comparison producing a boolean that then participates in the
NEXT comparison as if it were a plain value) instead of Python's special
`and`-chained multi-comparison semantics.

## Files Likely Affected
- `mojo_compiler.py` — how a chain of comparison operators is parsed (does
  it build a single `Compare` node with a list of (op, operand) pairs, like
  real Python's AST, or does it fold into nested `BinaryOp` nodes left-to-
  right? If the latter, that's the structural cause — comparisons need
  their own AST representation distinct from arithmetic binops, OR the
  evaluator needs to detect a chain and special-case it.)
- `myinterpreter.py` — wherever comparison operators are evaluated (if the
  AST already correctly represents a chain, the bug is here: each pair must
  be evaluated left-to-right with short-circuiting, sharing the middle
  operand's already-computed value rather than re-deriving it from a
  previous comparison's boolean result).
- Check `gimple_codegen.py` (compiled path) for the same gap once the root
  cause is understood — note as a follow-up rather than expanding scope if
  it needs separate work.

## Fix

**`mojo_compiler.py`**: added a `CompareChain(operands: list, ops: list)`
dataclass (next to `BinaryOp`, ~line 177) representing a full Python-style
chained comparison — `len(operands) == len(ops) + 1`. `Parser._parse_expr`'s
operator loop (~line 2279) now special-cases every comparison-family
operator (`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `is`, `not in`, `is not`,
all sharing one precedence level, `_COMPARE_CHAIN_PREC = 5`) via two new
helpers, `Parser._at_compare_op`/`_consume_compare_op`: a single link still
produces the exact same `BinaryOp` node as before (byte-identical AST for
the overwhelmingly common 2-term case — `a < b` is untouched), and only a
genuine 2+-link chain builds/extends a `CompareChain`. `emit()` (the
AST-to-source pretty-printer, ~line 3272) got a matching case.

**`myinterpreter.py`**: added `Interpreter._apply_compare_op` (~line 3260),
factored out of `eval_BinaryOp`'s comparison-operator cases so both a plain
`BinaryOp` and the new `eval_CompareChain` (~line 3280) share one operator
table — `eval_CompareChain` evaluates `operands[0]` once, then for each
`(op, operand)` pair evaluates that operand exactly once, applies `op`, and
returns `False` immediately (without evaluating any later operand) the
moment one link fails; only returns `True` once every link has held. (As a
side effect this also fixed `not in` being entirely unimplemented in
`eval_BinaryOp` — it had no case at all before, only `in`/`is`/`is not`.)

**`gimple_codegen.py`** (compiled path — real stdlib files use chains,
e.g. `` `A` <= c <= `Z` `` in `base64.mojo`, `0 <= idx <= 1` in
`counter.mojo`, `0 <= self.index < len(...)` in `dict.mojo`, so this had to
be handled, not just noted as a follow-up):
- `_lower_binary` was split at the point both operands are already lowered
  into a new `_lower_binary_tail(op, left_node, lt, lv, right_node, rt, rv)`
  containing everything after that point (string/pointer/`is`-`is not`/
  numeric comparison dispatch), so a chain link can reuse the identical
  per-operator logic without re-evaluating a shared operand.
- `_lower_in_impl` similarly split into `_lower_in_impl_values` (still owns
  the `x in range(...)` fast path, which needs the raw AST) and
  `_lower_in_dispatch` (the list/dict/set/str container dispatch, given
  already-lowered operands) for the same reason.
- New `_lower_compare_chain` builds real branching basic blocks (like the
  existing `and`/`or` lowering) that evaluate each operand once,
  short-circuiting to a `_Bool` `False` the instant one link fails.
  (Hit and fixed one real GIMPLE-strictness bug along the way: `-fgimple`
  rejects a bare integer_cst assigned straight into a `_Bool` lvalue
  — "non-trivial conversion in 'integer_cst'" — once a function is large
  enough to take the strict low-level GIMPLE path; fixed by casting the
  literal, `(_Bool)1` / `(_Bool)0`, matching how `BoolLiteral` is coerced
  elsewhere.)
- `CompareChain` registered in the self-host struct-field table
  (`struct_field_types['CompareChain']`, mirroring `CallExpr`), the
  `_EXPR_DISPATCH` table (`generated_dispatch.py` + its generator
  `gimple_spec_gen.py`), and every AST-walking helper that previously
  handled `BinaryOp` for identifier-usage/escape-analysis/call-collection
  purposes (`_find_idents`, `_idents`, `_used_idents_node`, `_walk_expr`,
  `_walk_expr_nodes`, `_collect_calls`, the closure param-usage scanner,
  and `_quick_type`), plus the `comptime`-constant folders
  (`_eval_const_int`, `_eval_const`, via a new `_eval_const_compare_op`
  helper — deliberately a plain `if`/`elif` chain, not a dict of lambdas:
  a dict-of-lambdas version broke `make check-selfhost` with an undefined-
  symbol link error, since this codegen's own closure-lowering doesn't
  support several small same-scope lambdas bound into one dict literal).

## Verification (2026-07-20)

- Exact original repro: `y = 5` → `in range`; `y = 15` → `out of range`
  (was `in range`/`in range`). Confirmed via `python3 mojo.py run`.
- Plain 2-term comparison (`a < b`) unaffected — same `BinaryOp` AST node,
  same behavior.
- 4-term chain: `1 < 2 < 3 < 4` → `True`; `1 < 2 < 3 < 2` → `False`.
- Mixed operators: `1 < 5 == 5` → `True`; `1 < 5 == 6` → `False`.
- Short-circuit side effects: `f() < g() < h()` where `f()`/`g()`/`h()`
  each print their own name and `g()` returns a value that fails the
  second link — confirmed `h()` is never called (its print never fires).
- `python3 test_gimple.py`: 159 passed, 0 failed (verified identical to
  this repo's current baseline, i.e. no regression — the task brief's
  expected count of 161 predates this session's baseline).
- `python3 test_module_cache.py`: 58 passed, 0 failed (likewise identical
  to baseline; brief's expected 64 predates this baseline).
- `make check-selfhost`: passes — "self-host compiles + links clean
  (mojo.py compiling mojo.py)", `test_selfhost.py` 1 passed, 0 failed.
- From-scratch stdlib dylib build skip-count check:
  ```
  rm -f build/libmojostdlib.dylib
  python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)" 2>&1 | grep -c '^  skip'
  ```
  → `0`, matching the pre-change baseline (also `0`). This required real
  gimple-codegen support (see above), not just an interpreter-side fix —
  several real stdlib files (`base64.mojo`, `counter.mojo`, `dict.mojo`,
  `list.mojo`, `span.mojo`, `_libc_errno.mojo`, `_utf8.mojo`,
  `string_strategy.mojo`, plus a few more) contain real chained
  comparisons and are compiled through this path.
- A first attempt at the from-scratch build regressed to 12 skips (all
  failing with gcc's "non-trivial conversion in 'integer_cst'" on
  `_Bool` temps) — root-caused to the bare-int-literal-into-`_Bool`
  GIMPLE-strictness issue above and fixed; re-verified back to 0 skips.
- A first attempt at self-hosting regressed `make check-selfhost` (a
  dict-of-lambdas in `_eval_const`/`_eval_const_int`'s new `CompareChain`
  cases produced an undefined-symbol link error once gimple_codegen.py
  compiled itself) — root-caused and fixed by replacing it with a plain
  `if`/`elif` helper method; re-verified `make check-selfhost` passing.
- Post-merge note: the worktree this fix was developed in had fallen behind
  `master` by several other same-day fixes; rebasing it clean surfaced 3
  leftover `node.op` references in `_lower_binary_tail` (stray from before
  `_lower_binary` was split — every other case in that function correctly
  uses the plain `op` parameter) that a 3-way auto-merge didn't flag as
  conflicts but broke `test_gimple.py`/`test_module_cache.py` immediately.
  Fixed as part of the merge; re-verified full quality gate (both suites,
  self-host, 0-skip stdlib build) clean on `master` after merging.
