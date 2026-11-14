# Plan: DIAGNOSTICS (formatting + missing validation)

## Goal
Improve diagnostic formatting and add missing validations (modular comparison).

## Steps

### Step 1: Compare formatting
- Scope: Compare our diagnostic output to modular's for the 10 formatting cases
- Files: mojo/backend_gimple/*.py
- Test: manual comparison
- Acceptance: document which are worse

### Step 2: Fix worse formatting
- Scope: Improve our formatting where worse
- Files: mojo/backend_gimple/*.py
- Test: build
- Acceptance: matches or better

### Step 3: Missing validations (25 real)
- Scope: Add validation for the 25 real missing-validation cases
- Files: mojo/backend_gimple/*.py
- Test: build
- Acceptance: validations present

### Step 4: Regression test
- Scope: Add tests
- Files: test_*.py
- Test: run
- Acceptance: passes