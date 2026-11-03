# The AST bridge cannot state a user call of two or more arguments, because the handlers are fixed-arity

**Area:** FORMAL (the AST bridge's call handlers). **Status: OPEN.** Filed
2026-11-03, when the earlier doc on the one-argument `MojoExpr.call` node was
retired: that node defect is fixed (the node is `List MojoExpr`, widened
2026-10-05), and what remains is the handler arity.

## What is true now (measured 2026-11-03)

- **The node carries every argument.** `_expr_ast` renders a one-argument call
  as `MojoExpr.call name [a]`, a two-argument call as `MojoExpr.call2 name a b`,
  and a three-argument call as `MojoExpr.call name [a, b, c]`. Pinned by
  `test_formal_call_proof_gen.py::TestAstBridgeCallLimit`
  (`test_the_ast_node_carries_every_argument_of_a_wider_call`,
  `test_the_two_argument_node_carries_both_arguments_in_order`).
- **A call is stated only when its arity's handler answers its name.**
  `formal/arm64_proof_gen.py::_ast_bridge_gaps` refuses:
  - one argument, unless the name is in `callFunc` (the proved function, a
    callee with a model, or an admitted contract);
  - two arguments, unless the name is an arity-2 admitted contract
    (`resolvable2`, read through `_admitted_arity2_map`, the same table
    `callFunc2` emits);
  - zero arguments, always (`evalArgs` packs an empty list into the product
    `1`, which a parameterless model does not take);
  - three or more, always.

  The two-argument rule was the regression to fix: commit `3d32c0e66` treated
  every two-argument call as answered, so `def main(x): return _scalar_max2(x,
  x)` was emitted with `eval_eq_mojo` false (`callFunc2` answers `0`), which is
  the `⊢ False` this family of docs is about. Seven tests in
  `TestAstBridgeCallLimit` caught it.

## What is still missing

1. **A two-argument call to a user function.** `callFunc2` answers only the
   arity-2 admitted contracts. `_callee_call_table` builds the `callFunc` branch
   for callees of ONE parameter only, so a two-parameter `_go` model
   (`_scalar_max2_go a b`) has no branch, and the call is refused. The fix is
   the arity-2 analogue of step 2 in the retired doc: build a `callFunc2` branch
   `if name = "f" then f_go arg0 arg1` for every two-parameter callee whose
   model is in `go_defs`, pass it to `_call_func2_lean` through an `exports`
   argument, and add those names to `resolvable2`.
2. **A call of three or more arguments.** No handler exists. `evalArgs` and
   `evalExpr`'s `MojoExpr.call` arm would need a handler that takes the list (or
   a `callFunc3`), and the generators would need the matching table. The node
   already carries the list, so this is the handler's type, not the node.

## Exact next step

1. Write the failing positive test first: a program whose `main` returns
   `_scalar_max2(x, x)` builds with `--formal --backend=x86_64` and its proof
   file typechecks with no `⊢ False`. The test already exists in refusal form:
   `test_a_two_argument_callee_is_refused_by_the_bridge`, and it currently
   fails at HEAD for an unrelated reason (its refusal reads "the semantic model
   has no value for something", not an arity refusal). Measure that first; the
   two-argument case may hit the model's own gap before the bridge.
2. Land step 1 above in `formal/arm64_proof_gen.py` (`_callee_call_table`,
   `_call_func2_lean` exports, `resolvable2`), mirrored in
   `formal/x86_64_proof_gen.py`, which already calls the same helpers.
3. Only then, step 2.

## Suspect to check first (not verified)

`formal/arm64_proof_gen.py` builds `_admitted_calls_map2` and then merges every
one-argument admitted spelling into it (the fallback loop after the arity-2
table). `_call_func2_lean` emits an arm for every non-empty entry, so a unary
Lean function would be applied to two arguments in `callFunc2`. Measure whether
that arm typechecks or breaks a program that has a unary admitted contract
before deciding; if it does not typecheck, it is a separate bug and should get
its own doc.

The two generators already disagree here: x86-64 has no such merge (its old
fallback loop was a no-op, removed in this change), so the two `callFunc2`
tables differ for a program with a unary admitted contract. The fix is one table
built once, whichever way the measurement goes.
