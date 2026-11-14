# Plan: COMPILE_FAIL_Tools_c-analyzer

## Goal
Fix c-analyzer compilation failures (multiple files).

## Steps

### Step 1: Reproduce
- Scope: Build c_analyzer/__main__.py and collect errors
- Files: .tmp/ca/c_analyzer/__main__.py
- Test: build
- Acceptance: errors documented

### Step 2: Fix tuple-target unpacking over callable-local
- Scope: Handle tuple unpacking over mojo_iter_word result
- Files: mojo/backend_gimple/cpp_core.py
- Test: build
- Acceptance: compiles

### Step 3: Fix structural return-type inference for check
- Scope: Infer return type for check function
- Files: mojo/backend_gimple/cpp_core.py
- Test: build
- Acceptance: compiles

### Step 4: Fix nested generator claims
- Scope: Handle traceback_cm, _iter_filenames
- Files: mojo/backend_gimple/cpp_async.py
- Test: build
- Acceptance: compiles

### Step 5: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes