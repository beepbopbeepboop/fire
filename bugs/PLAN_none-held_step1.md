# none-held — step 1: Flow-sensitive None tracking at if/while/try join points

Parent plan: docs/none-held-plan.md (or none-held-plan.md etc.)

## Scope
Add dataflow tracking of which locals hold None on each path. Measurable: probe prints True.

## Files
mojo/backend_gimple/emit_exprs.py

## Acceptance
Step completes per plan; no regression in existing tests.
