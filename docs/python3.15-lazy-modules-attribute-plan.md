# Plan: PYTHON3.15_lazy_modules_attribute

## Goal
Support module-level `__lazy_modules__` list making regular imports lazy.

## Steps

### Step 1: Lexer/parser
- Scope: Parse `__lazy_modules__` assignment
- Files: fire_compiler.py
- Test: parse test
- Acceptance: parses

### Step 2: Semantics
- Scope: Make imports in the list lazy
- Files: mojo/middle/*.py
- Test: compile test
- Acceptance: works

### Step 3: Codegen
- Scope: Lower to C
- Files: mojo/backend_gimple/*.py
- Test: compile test
- Acceptance: compiles

### Step 4: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes