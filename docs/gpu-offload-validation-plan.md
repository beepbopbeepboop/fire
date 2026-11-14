# Plan: GPU_offload_validation

## Goal
Add GPU offload validation (we target GPU).

## Steps

### Step 1: Research modular GPU offload validation
- Scope: Understand what modular validates for GPU offload
- Files: modular/mojo/test/
- Test: N/A
- Acceptance: document requirements

### Step 2: Implement validation
- Scope: Add GPU offload validation in compiler
- Files: mojo/backend_gimple/*.py
- Test: build
- Acceptance: validates

### Step 3: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes