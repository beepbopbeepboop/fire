# enum-runtime-class — step 3: EnumType.__new__ end-to-end

Parent plan: docs/enum-runtime-class-plan.md (or none-held-plan.md etc.)

## Scope
class Color(Enum): RED=1 creates class at runtime via metaclass.

## Files
mojo/backend_gimple/*

## Acceptance
Step completes per plan; no regression in existing tests.
