# DIAGNOSTICS step 3: Inferred-parameter dependency errors

SPLIT: all three parts have landed (see Status).

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §3.

## Symptom
An inferred parameter (`_`) whose type depends on a non-inferred parameter must be refused; a non-inferred element-type parameter must be reported.

## Modular tests
autoparam_dependency_errors.mojo

## Files
fire_compiler.py struct-signature elaboration, mojo/backend_gimple/module_gen.py

## Test
`struct RepeatedDep[c: Int, X: Pair[c, c]]` fails with `inferred parameter of type 'Pair[c, c]' cannot depend on non-inferred parameter 'c'`.

## Acceptance
Add `test_inferred_param_dependency_diagnostic.py`.

## Status
- **Landed (2026-11-11):** three checks, in `fire_compiler.py`, run from
  `Parser.parse_module` beside the out-argument check.
  - An inferred bracket parameter (its type has a `_` placeholder) whose
    implicit type, with the callee's parameters replaced by the arguments,
    mentions a non-inferred parameter of the same struct is refused, once per
    name: `inferred parameter of type 'Pair[c, c]' cannot depend on
    non-inferred parameter 'c'`. Only a callee declared in the same module is
    checked.
  - A variadic `*Xs: T` whose element type has a `_` placeholder, or names a
    parameter of the same bracket list, is refused: `element type parameter
    'NeedsPair[a, b, p]' must be an 'inferred' parameter`. The `_` prints as the
    callee's parameter name, and a literal argument prints as `Int(n)`.
  - Supporting parser fixes: a bracket parameter may be named `mut`, and a
    variadic bracket name is recorded (`FunctionDef.variadic_bracket_params`).
    A bare `*,` no longer marks the next parameter variadic.
  - Regression: `test_inferred_param_dependency_diagnostic.py`.
  - Checked by probe, not added as a test: `struct TakesXOrigin[MUT: Int,
    O: XOrigin[MUT, _]]` from modular's parameters_errors.mojo, which refuses
    `'ParametricOnInt[MUT]'` for `'MUT'` under the same rule.
  - Not run: `make gate` (the change touches the parser, which is on the
    compiled path).
