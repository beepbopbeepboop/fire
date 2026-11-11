# Plan: COMPILE_FAIL_Tools_cases_generator_analyzer

## Goal
Fix cases_generator_analyzer compilation (positional-capture binding in _gen_stmt_MatchStmt).

## Steps

### Step 1: Reproduce
- Scope: Build cases_generator_analyzer
- Files: .tmp/ca/cases_generator_analyzer
- Test: build
- Acceptance: errors documented

### Step 2: Fix positional-capture binding
- Scope: Fix _gen_stmt_MatchStmt
- Files: mojo/backend_gimple/*.py
- Test: build
- Acceptance: compiles

### Step 3: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes