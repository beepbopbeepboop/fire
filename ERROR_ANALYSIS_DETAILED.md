# Detailed Error Analysis - compile_stdlib.py Results

## Overall Statistics
- **Total Files**: 643
- **Passed**: 124 (19.3%)
- **Failed**: 519 (80.7%)
- **Improvement from fixes**: +1 file

## Error Category Breakdown

### 1. IMPLICIT DECLARATIONS (55 failures, 10.6%)
Functions being called without declaration. These should be forward-declared.

**Top offenders**:
- `Int` (4) - Mojo type constructor
- `UInt` (3) - Mojo type constructor  
- `Bool` (3) - Mojo type constructor
- `iter` (3) - Mojo built-in
- `next` (2) - Mojo iterator protocol
- `UInt8`, `UInt32`, `U128`, `Pointer`, `Int64` - Type constructors

**Root cause**: Mojo built-in type constructors and utility functions are being called in generated code but not declared.

**Fix difficulty**: Medium - Need to add forward declarations for all Mojo built-in constructors and utility functions

---

### 2. TOO MANY ARGUMENTS (52 failures, 10.0%)
Functions being called with more arguments than declared.

**Examples**:
- `select`, `Index`, `String`, `Set` (1 each)
- `chain`, `peekable`, `cycle`, `drop`, `take` - Iterator functions
- `exists`, `isdir`, `isfile`, `join`, `listdir`, `stat` - OS path functions

**Root cause**: Function forward declarations don't match the actual call sites. This can happen when:
- Methods are overloaded (multiple signatures for same name)
- Parameters are added/removed but forward declaration not updated
- Codegen creates signature different from source

**Fix difficulty**: Hard - Requires understanding which signature is correct for each overload

---

### 3. CONFLICTING TYPES (33 failures, 6.4%)
Functions declared twice with different types.

**C Standard Library Conflicts (high priority)**:
- `memcmp` (5) - C string function
- `getenv` (5) - C environment function
- `cos` (4) - C math function
- `ceil`, `realpath`, `sqrt` (3 each) - C standard library functions
- `dlclose`, `floor`, `max`, `erf`, `exp`, `remove`, `rand` (2 each)

**Root cause**: We're declaring C standard library functions with different signatures than what the system headers provide. Need to either:
1. Not declare them (let system headers handle it)
2. Use correct signatures that match the system headers

**Fix difficulty**: Medium - Just need to match system library signatures or not declare them

**Other Conflicts**:
- `Bool___init__`, `index` - Overloaded methods causing name collision

---

### 4. INVALID GIMPLE CALL (17 failures, 3.3%)
GIMPLE-specific code generation issues.

**Note**: These are avoided per instructions as GIMPLE is inherently complex.

---

### 5. UNDECLARED 'DType' (7 failures, 1.3%)
The DType type/namespace is not available in generated code.

**Root cause**: DType is a Mojo type system feature that needs to be made available as a global or imported symbol.

**Fix difficulty**: Medium - Need to export DType or provide stubs

---

### 6. SYNTAX ERRORS (6+ failures, 1.0%)
Expected tokens missing or invalid syntax in generated C code.

**Examples**: Missing colons, commas, parentheses in complex expressions

**Fix difficulty**: Variable - Usually indicates issues in expression generation

---

## Priority Ranking for Fixes

### HIGH PRIORITY (Easy wins)
1. **C stdlib conflicts (23 failures)** - Don't declare standard library functions; let system headers handle them
   - Remove declarations for: memcmp, getenv, cos, ceil, sqrt, realpath, dlclose, floor, erf, exp, rand, remove
   - Keep proper ordering of includes

2. **Add Mojo built-in constructors (12 failures)** - Declare Int, UInt, Bool, UInt8, UInt32, etc.
   - Add to mojo_runtime.h or generate declarations in codegen

### MEDIUM PRIORITY (Moderate effort)
3. **Fix function signature mismatches (52 failures)** - Implement method overloading resolution
   - Give each overload a unique mangled C name
   - Generate correct forward declarations for each variant

4. **Add missing Mojo utilities (8 failures)** - iter, next, swap, op, etc.
   - These are iterator protocol and utility functions
   - Need forward declarations or stubs

### LOWER PRIORITY (Complex)
5. **DType availability (7 failures)** - Export DType as a global
6. **Syntax errors (6 failures)** - Debug expression generation

---

## Estimated Impact of Fixes

If we fix:
- ✅ C stdlib conflicts alone: +23 files = 147 passed (22.8%)
- ✅ + Mojo constructors: +35 files = 159 passed (24.7%)
- ✅ + Function overloads: +87 files = 211 passed (32.8%)
- ✅ + All above: ~240-250 passed (37-39% success rate)

---

## Recommended Next Steps

1. **Immediate** (30 min): Don't declare C stdlib functions - let system headers provide them
2. **Short term** (1 hr): Add Mojo type constructor declarations (Int, UInt, Bool, etc.)
3. **Medium term** (2-3 hrs): Implement method overloading with unique C names
4. **Longer term** (4+ hrs): Fix remaining function signature issues and GIMPLE problems

