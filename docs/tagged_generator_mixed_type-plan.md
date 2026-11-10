# Plan: CODEGEN_tagged_generator_word_type_conflict

## Goal
Allow a name bound to a tagged generator word (a yield of more than one kind) to also hold a value of another C type (str or float), instead of refusing to compile.

## Background
Currently, `tagged_mixed_name` detects when a name is both a tagged word and bound to non-int values, and `MIXED_NAME_NON_INT64_REFUSAL` refuses compilation. This prevents segfaults (str) or wrong values (float). The fix is to make the box carry the other type.

## Steps

### Step 1: Understand the box representation
- Scope: Read `tagged_next_bind_name`, `tagged_for_target_name`, `_local_bindings` in emit_infra.py.
- Files: mojo/backend_gimple/emit_infra.py
- Test: existing tests pass
- Acceptance: document how the box is stored and read

### Step 2: Add type tag to the box
- Scope: Extend the tagged word box to carry a type discriminator so a str/float value can be stored alongside the int.
- Files: mojo/backend_gimple/emit_infra.py, gimple_codegen.py
- Test: unit test for type tag
- Acceptance: box can represent str/float values

### Step 3: Update read sites
- Scope: Wherever a tagged word is read as int, also handle str/float reads.
- Files: emit_exprs.py, emit_stmts.py
- Test: existing generator tests
- Acceptance: reads produce correct values

### Step 4: Remove the refusal
- Scope: Remove MIXED_NAME_NON_INT64_REFUSAL and the tagged_mixed_name check.
- Files: emit_infra.py, emit_funcs.py
- Test: compile the failing module
- Acceptance: module compiles and runs

### Step 5: Regression test
- Scope: Add test_tagged_generator_mixed_type.py
- Files: test_*.py
- Test: run test
- Acceptance: test passes