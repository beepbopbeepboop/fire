# SUITE_gimplerunner: part 2 - Runtime crashes

## Problem
Some compiled GIMPLE programs crash at runtime (exit codes other than 0, segfaults, etc.).

## Investigation
1. Identify which tests are failing with runtime errors (not just compilation).
2. Check if the failures are due to:
   - Memory corruption or use-after-free in generated C code
   - Unhandled exceptions in the generated code
   - Resource exhaustion (OOM, stack overflow)
3. For each failing test, determine if the crash is reproducible and what the exact error is.

## Acceptance Criteria
- List all failing tests with their runtime error messages
- Identify root cause for each failure
- Provide a plan to fix or work around the issue

## NOT DONE
- [ ] Identify specific failing tests with runtime errors
- [ ] Analyze error messages (segfault, OOM, etc.)
- [ ] Determine root cause
- [ ] Create fix plan
