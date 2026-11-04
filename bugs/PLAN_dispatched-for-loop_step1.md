# dispatched-for-loop — step 1: Decide representation (int64_t vs runtime query)

Parent plan: docs/dispatched-for-loop-plan.md (or none-held-plan.md etc.)

## Scope
Owner decision; document choice.

## Decision
Chose **runtime query** (via `mojo_list_get_kinds` / runtime element-kind inspection) to declare the shared loop variable before branching, rather than guessing `int64_t` or letting the dict arm's type win. Runtime query is correct for both dict and list arms without regressing string-keyed dicts to silent wrong values.

## Files
docs/dispatched-for-loop-plan.md, bugs/PLAN_dispatched-for-loop_step1.md

## Acceptance
Step completes per plan; no regression in existing tests.
