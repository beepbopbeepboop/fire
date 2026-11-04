# enum-runtime-class — step 1: Dynamic instance attributes on dynamic classes (stage 2)

Parent plan: docs/enum-runtime-class-plan.md (or none-held-plan.md etc.)

## Scope
setattr(obj,n,v)/obj.n=v for undeclared names writes dynattr dict.

## Files
runtime/fire_runtime.c, mojo/backend_gimple/emit_stmts.py

## Acceptance
Step completes per plan; no regression in existing tests.
