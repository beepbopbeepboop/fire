# DIAGNOSTICS_binding_deferrals part 2: modular-parity diagnostics and regression test

Part of `bugs/hard/DIAGNOSTICS_binding_deferrals.md` (SPLIT). Plan: `docs/diagnostics-missing-validation-plan.md` §4. Depends on part 1 for deferral suppression behavior.

## Goal
Make failed struct binding diagnostics match the modular expectations for `failed_binding_deferrals.mojo` and add the regression test.

## Scope
- `mojo/backend_gimple/emit_resolve.py` generic-binding path (message selection/wording for the failing binding cases covered by the modular test).
- New test `test_binding_deferral_diagnostic.py`.

## Acceptance
- `NeedsCopyablePos[CondCopyable[U], 0]` fails with `violated constraint`; `NeedsCopyablePos[..., 1]` compiles.
- The modular `failed_binding_deferrals.mojo` error lines are reproduced: only the error that failed the binding is reported (including the `invalid bindings in signature: lacking evidence` case as applicable), with no deferred-constraint noise.
- `test_binding_deferral_diagnostic.py` added and passing (narrow run of that test file only).

## Test
- `python3 -m pytest <path>/test_binding_deferral_diagnostic.py` (or the narrowest command covering it).
