# DIAGNOSTICS step 3, part 1: refuse inferred parameter depending on a non-inferred parameter (struct-signature elaboration)

Part of the split of `bugs/hard/DIAGNOSTICS_inferred_param_dependency.md`; the
original doc is part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §3.

## Why this part

An inferred parameter (`_`) whose type depends on a non-inferred parameter must
be refused; otherwise a generic like

```mojo
struct RepeatedDep[c: Int, X: Pair[c, c]]
```

compiles silently even though `X`'s inferred type `Pair[c, c]` references `c`,
which is not inferred. The modular compiler rejects this with:

    inferred parameter of type 'Pair[c, c]' cannot depend on non-inferred parameter 'c'

The fire_compiler.py struct-signature elaboration path does not emit this
diagnostic, so the invalid code passes.

## Scope

1. **Detect the dependency.** In `fire_compiler.py` struct-signature
   elaboration, when processing an inferred parameter whose type expression
   references a non-inferred parameter, flag it.
2. **Emit the diagnostic.** Raise/refuse with the message
   `inferred parameter of type '<type>' cannot depend on non-inferred parameter '<param>'`.
3. **Acceptance.** The modular file's error line for `struct RepeatedDep[c: Int, X: Pair[c, c]]` is
   reproduced.

## Status

- **Open.**
