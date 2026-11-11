# Plan: COMPILE_FAIL_Tools_gdb_libpython

## Goal
Fix gdb_libpython compilation (int on struct with __int__ calls struct's own method).

## Steps

### Step 1: Reproduce
- Scope: Build gdb_libpython
- Files: .tmp/ca/gdb_libpython
- Test: build
- Acceptance: errors documented

### Step 2: Fix __int__ method dispatch
- Scope: Handle int(x) on struct with __int__
- Files: mojo/backend_gimple/cpp_core.py
- Test: build
- Acceptance: compiles

### Step 3: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes