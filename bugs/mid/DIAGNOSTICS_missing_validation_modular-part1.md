# DIAGNOSTICS missing-validation part 1: enforce the paren form `constrained(cond, msg)` in statement position

Class: **mid** (this doc lives in `bugs/mid/`). Two paths change (the gimple
statement lowering and the interpreter), and both must share the same
condition/message evaluation.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`. Plan:
`docs/diagnostics-missing-validation-plan.md` (the `constrained` family).

## Goal

`constrained(cond, msg)` is the paren spelling of Mojo's compile-time
`constrained[cond, msg]()` builtin. A provably-false condition must fail
compilation with `constraint failed: <msg>` in the compiled path, and must
make `python3 fire.py run` exit nonzero with the same prefix in the
interpreter. Today the paren form is checked only when its value is used and
not when it is a bare statement (compiled path), and not at all in the
interpreter.

## Current state (measured 2026-11-12)

- Value position already works:
  `var x = constrained(False, "nope")` raises
  `constraint failed: nope` through `_lower_call` →
  `mojo/backend_gimple/emit_calls.py::_try_lower_constrained` (the paren
  branch is at ~1827).
- Statement position is silently accepted:
  `def f():\n    constrained(False, "nope")` and the same with a following
  `f()` both compile with no diagnostic. `_gen_stmt_ExprStmt`
  (`mojo/backend_gimple/emit_stmts.py`, ~5213) has a fast path for a bare
  `IdentExpr`-callee call that emits the call directly and never reaches
  `_lower_call`, so `_try_lower_constrained` is bypassed.
- Interpreter: `python3 fire.py run` on the same statement fails with
  `name 'constrained' is not defined`. `myinterpreter.py`'s
  `_eval_constrained_bracket` (~7885) is only wired to a `CallExpr` whose
  callee is a `SubscriptExpr` (~7914); the paren `IdentExpr` callee is not
  intercepted.
- The bracket form `constrained[False, "nope"]()` already fails in both
  paths; this part must not change it.

## Scope

1. **gimple.** In `_gen_stmt_ExprStmt`'s bare-call fast path, call
   `_try_lower_constrained(gen, node.value)` before the normal statement
   lowering and return when it reports handled — the same guard the other
   fast-path builtins there use. Do not duplicate the condition/message
   evaluation; `_try_lower_constrained` already owns it and already honours
   `_locally_binds_name` (a user-defined `constrained` must still win) and
   the struct-method poison-pill suppression.
2. **interpreter.** Extend the `_eval_constrained_bracket` interception in
   `myinterpreter.py` to a `CallExpr` whose callee is a plain
   `IdentExpr('constrained')` with at least one argument, reusing the same
   helper for the condition/message. Keep the `not self.scope.has(...)`
   shadowing guard that the subscript form already uses. A true/unknown
   condition is a no-op returning `None`.
3. Message text is exactly the bracket form's: `constraint failed: <msg>`,
   defaulting to `constraint failed` when no message is given.

## Acceptance

- `compile_to_gimple` rejects `constrained(False, "nope")` as a bare
  statement, and `fire.py build` exits nonzero with
  `constraint failed: nope`.
- `constrained(True, "ok")` and `constrained(<unknown>, "ok")` are no-ops in
  both paths.
- A module that defines its own `def constrained(...)` keeps its own
  function (no interception).
- The interpreter rejects the false paren form with
  `constraint failed: <msg>` and treats the true one as a no-op.
- `constrained[False, "nope"]()`, `comptime assert`, and the value-position
  paren form keep their current behaviour.

## Done when

Add `test_constrained_paren_diagnostic.py` beside the other
`test_*_diagnostic.py` files (do NOT register it in `tools/suite.py`) and run
exactly:

    python3 tools/memslot.py --gb 8 --label constrained-paren -- python3 test_constrained_paren_diagnostic.py

The test compiles the statement forms with `compile_to_gimple`, runs the
interpreter cases through `fire.py run`, and asserts the messages above plus
the shadowing and true/unknown controls.

## Not in this part

The bracket form, the gimple call-site constraint checks, and `where`-clause
evaluation are unchanged. No test registration.

## Status

- **Open.**
