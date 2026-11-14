# Plan: PYTHON3.15_disjoint_bases

## Goal
Support disjoint bases in the type system (PEP 800).

## Steps

### Step 1: Research PEP 800
- Scope: Read PEP 800 spec and understand disjoint bases semantics
- Files: /Users/mrs/net/Python-3.15.2/Doc/whatsnew/3.15.rst
- Test: N/A
- Acceptance: document requirements

### Step 2: Lexer/parser support
- Scope: Add syntax for disjoint bases if any
- Files: fire_compiler.py
- Test: parse test
- Acceptance: parses

### Step 3: Type system support
- Scope: Implement disjoint bases in type system
- Files: mojo/middle/types.py
- Test: type check test
- Acceptance: works

### Step 4: Codegen
- Scope: Lower disjoint bases to C
- Files: mojo/backend_gimple/*.py
- Test: compile test
- Acceptance: compiles

### Step 5: Regression test
- Scope: Add test
- Files: test_*.py
- Test: run
- Acceptance: passes