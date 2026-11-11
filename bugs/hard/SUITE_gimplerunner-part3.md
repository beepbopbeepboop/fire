# SUITE_gimplerunner: part 3 - Test expectation mismatches

## Problem
Some tests pass compilation and execution but produce incorrect output (wrong return values, wrong stdout).

## Investigation
1. Identify which tests are failing with incorrect output (not just crashes or timeouts).
2. Check if the failures are due to:
   - Incorrect expected output in the test
   - Bug in the generated GIMPLE code that produces wrong results
   - Environment-specific behavior (e.g., different Python versions)
3. For each failing test, determine if the expected output is correct and if the code needs to be fixed.

## Acceptance Criteria
- List all failing tests with their expected vs actual output
- Verify if the expected output is correct
- Provide a plan to fix the code or update the test

## NOT DONE
- [ ] Identify specific failing tests with wrong output
- [ ] Compare expected vs actual output
- [ ] Determine if the bug is in the code or the test
- [ ] Create fix plan
