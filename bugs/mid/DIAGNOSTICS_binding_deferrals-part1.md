# DIAGNOSTICS_binding_deferrals part 1: suppress deferred binding diagnostics

Part of `bugs/hard/DIAGNOSTICS_binding_deferrals.md` (SPLIT). Plan: `docs/diagnostics-missing-validation-plan.md` §4.

## Goal
In the generic-binding path, when a struct binding fails, report only the error that actually failed the binding and suppress diagnostics from constraints that were merely deferred before the failure.

## Scope
- `mojo/backend_gimple/emit_resolve.py` generic-binding path (track deferred vs failing constraints and filter reporting accordingly).

## Acceptance
- A binding that fails because a concrete constraint is violated does not also emit diagnostics for constraints that were deferred earlier in the same binding attempt.
- A case like `NeedsCopyablePos[CondCopyable[U], 0]` reports the failing constraint (`violated constraint`) without extra deferred-constraint noise.
- Existing satisfied bindings still compile without new diagnostics.

## Test
- Add or extend a narrow regression check as part of this change (e.g. inline in a new/updated test) demonstrating deferred diagnostics are suppressed for a failed binding. Full modular-parity coverage is part 2.
