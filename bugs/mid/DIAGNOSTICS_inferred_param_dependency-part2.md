# DIAGNOSTICS step 3, part 2: report non-inferred element-type parameter (module-gen path)

Part of the split of `bugs/hard/DIAGNOSTICS_inferred_param_dependency.md`; the
original doc is part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §3.

## Why this part

A non-inferred element-type parameter must be reported. The module-gen path
(`mojo/backend_gimple/module_gen.py`) currently does not produce this diagnostic,
allowing invalid generic signatures to pass silently.

## Scope

1. **Detect the condition.** In `mojo/backend_gimple/module_gen.py`, when
   processing a generic struct's parameters, identify any element-type parameter
   that is not inferred but should be reported.
2. **Emit the diagnostic.** Produce a diagnostic for the non-inferred
   element-type parameter.
3. **Acceptance.** The modular file's error line for the element-type parameter
   case is reproduced.

## Status

- **Open.**
