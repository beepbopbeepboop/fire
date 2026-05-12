# GIMPLE Bootstrap Compilation Fix - Implementation Plan

**Status**: 16 GIMPLE errors remaining (from initial 30+)  
**Validation**: `make bootstrap` must complete without errors  
**Priority**: HIGHEST - Fix make bootstrap compilation

---

## CRITICAL PATH: Make Bootstrap Work

### Problem Summary
When `make bootstrap` runs, the mojo compiler generates C code that fails GIMPLE validation. The root cause: gimple_codegen.py is imported by mojo.mojo, and when transpiled to C, it produces invalid GIMPLE code.

**Current Error Count**: 16 errors in stage1/mojo.ci after GCC -fgimple compilation

### Error Categories (All Must Be Fixed)

#### Category 1: Invalid Casts in Function Arguments (8+ errors)
**Pattern**: `(char *)varname` or `(int64_t)varname` as function arguments
**Lines**: 4817, 6589, 6638, 6911, 7165, 7886 in stage1/mojo.ci
**Root Cause**: Variables assigned from `TypeLattice.join()` results don't have clear types in transpiled C

**Examples**:
```c
mojo_list_append_str (_t67, (char *)res_type);  // INVALID - res_type is int
_t625 = mojo_list_contains_str (_t623, (char *)arith_type);  // INVALID
```

**Fix Strategy**:
1. **Approach A (Recommended)**: Rewrite gimple_codegen.py to avoid storing TypeLattice.join() results in variables
   - Inline the join calls where used instead of assigning to `res_type`, `arith_type`, `td`
   - This prevents type loss during transpilation
   
2. **Approach B (Fallback)**: Create explicit type declarations in generated code
   - Force variables to be typed as strings before use
   - Requires ensuring Python->C transpilation preserves types

**Affected Methods**:
- `_lower_binary` (line 1487): `res_type = '_Bool' if ... else TypeLattice.join(lt, rt)`
- `_lower_TernaryExpr` (line 1234): `res_type = TypeLattice.join(tt, et)`
- `_lower_floordiv`, `_lower_pow` (similar pattern with `td`)

#### Category 2: Global Dictionary Cast Errors (2+ errors)
**Pattern**: `(int64_t) _BIN_OPS` or similar global variable casts
**Line**: 6709 (error message shows `_t593 = (int64_t) _BIN_OPS;`)
**Root Cause**: Module-level dict `_BIN_OPS` being incorrectly cast during transpilation

**Fix Strategy**:
1. Pre-compute needed values from `_BIN_OPS` instead of accessing at call site
2. Store lookups in local variables with proper types
3. Example: Instead of `c_op = _BIN_OPS.get(node.op, node.op)` in complex context, pre-compute

**Affected Line**: gimple_codegen.py line 1486

#### Category 3: Type Conversion Errors (4+ errors)
**Pattern**: `non-trivial conversion in 'var_decl'` - type mismatches in variable initialization
**Line**: 2462, 2620, 2621, 7886
**Root Cause**: Variables declared with wrong types in transpiled code

**Fix Strategy**:
- Ensure variable types are explicit in transpiled C
- Add type hints or force Python code to be unambiguous for transpiler

---

## Implementation Steps (In Priority Order)

### STEP 1: Fix TypeLattice.join() Variable Storage (Highest Priority)
**Goal**: Eliminate 8+ cast-in-function-argument errors

**Changes to gimple_codegen.py**:

1. **Line 1234-1254 (_lower_TernaryExpr)**:
   - Replace: `res_type = TypeLattice.join(tt, et)` stored in variable
   - Inline the type computation at the point of use
   - Create temp only with explicit type name string

2. **Line 1487 (_lower_binary)**:
   - Replace: `res_type = '_Bool' if ... else TypeLattice.join(lt, rt)`
   - Move the entire computation inline into the _new_temp call
   - Example: `t = self._new_temp('_Bool' if node.op in _CMP_OPS else TypeLattice.join(lt, rt))`

3. **Line 1494 (_lower_binary - arith_type)**:
   - Replace: `arith_type = TypeLattice.join(lt, rt)`
   - Inline at each comparison and cast point
   - Pass TypeLattice.join result directly to string operations

4. **Similar fixes in _lower_floordiv, _lower_pow** (lines 1509-1540):
   - Replace `td = TypeLattice.join(...)` with inline computation
   - Only create named variable if absolutely necessary

**Expected Result**: Eliminates invalid casts like `(char *)res_type`

---

### STEP 2: Fix Global Dictionary Access (Medium Priority)
**Goal**: Fix `(int64_t) _BIN_OPS` errors

**Changes to gimple_codegen.py**:

1. **Line 1486 (_lower_binary)**:
   - Move `c_op = _BIN_OPS.get(node.op, node.op)` earlier or inline it
   - Ensure the lookup result is used directly, not stored in complex expressions

2. **Alternative**: Pre-populate operator mappings
   - Create local operator lookup table in the method
   - Avoid accessing module-level `_BIN_OPS` dict during transpilation

**Expected Result**: No more invalid global dict casts

---

### STEP 3: Verify Type Handling (Lower Priority)
**Goal**: Fix remaining type conversion errors

**Changes**:
1. Check variable declarations in generated code
2. Ensure type hints are present where needed
3. Add explicit type markers in Python code that transpiles poorly

**Expected Result**: Cleans up remaining "non-trivial conversion" errors

---

## Testing Strategy

### Validation Command
```bash
make bootstrap
```

This will:
1. Generate stage1/mojo.ci (Python transpiles to C via mojo.py)
2. Run gcc-mp-15 -fgimple to validate GIMPLE syntax
3. Compile to stage2/mojo binary
4. Verify idempotency with stage3

### Success Criteria
- ✅ All GCC -fgimple errors resolved
- ✅ stage2/mojo binary created successfully
- ✅ stage2 and stage3 outputs match (idempotency)

### Debugging
If errors persist:
1. Check stage1/mojo.ci for the exact error location
2. Trace back to gimple_codegen.py source via function name
3. Verify the variable is properly typed in generated C
4. Consider if TypeLattice.join needs different handling

---

## Key Files to Modify

| File | Lines | Change Type | Priority |
|------|-------|------------|----------|
| gimple_codegen.py | 1234-1254 | _lower_TernaryExpr refactor | CRITICAL |
| gimple_codegen.py | 1486-1505 | _lower_binary refactor | CRITICAL |
| gimple_codegen.py | 1509-1540 | _lower_floordiv/_lower_pow | CRITICAL |
| mojo/gimple_codegen.mojo | Sync with above | Mirror changes | HIGH |

---

## Success Indicators

1. **After Step 1**: 8+ errors eliminated
2. **After Step 2**: 10+ errors eliminated  
3. **After Step 3**: All 16 errors eliminated
4. **Final**: `make bootstrap` completes → stage2/mojo binary created

---

## Notes for Next Developer

- **Do NOT use mojo/gimple_codegen.mojo** - It's a transpiled copy that has the same issues. Focus on gimple_codegen.py.
- **TypeLattice.join()** is the core issue - it returns a string but the transpiler loses type info
- **Test incrementally** - After each method change, run `make clean-bootstrap && make bootstrap 2>&1 | grep "error:" | wc -l` to track progress
- **Commit frequently** - Each fixed method should be a separate commit with clear messaging

---

## Background Context

The mojo compiler (written in Python/Mojo) uses gimple_codegen.py to generate GIMPLE-annotated C code. When mojo.py is itself dumped to C as part of bootstrap, gimple_codegen.py gets transpiled alongside it. The Python patterns in gimple_codegen.py don't map cleanly to GIMPLE-compatible C, causing validation errors.

This is a **transpilation limitation**, not a logic error. The fix is to rewrite problematic patterns in gimple_codegen.py to be more transpiler-friendly.
