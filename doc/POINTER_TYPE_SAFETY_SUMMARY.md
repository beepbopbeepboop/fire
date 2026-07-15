# LP64 Pointer Type Safety Audit & Hardening

**Status**: In Progress - Tests Running  
**Date**: 2026-06-04

## What We Found

### gimple_codegen.py - Type Safety Issues
**Root Cause**: Intentional design to work around GIMPLE type restrictions by storing pointers in `int64_t`.

**Critical Issues Identified**:
1. **Pointer-to-int64_t Boxing** (13+ locations)
   - Storing pointers (MojoDict*, MojoList*, MojoSet*, char*, etc.) in int64_t
   - Type information lost unless tracked in `_actual_types` dict
   - Example: `(int64_t)(void *)pointer`

2. **Unsafe Unboxing** (primary danger)
   - Casting int64_t back to specific pointer type without validation
   - Example: `(MojoDict *)int64_t_var` - assumes int64_t holds MojoDict*
   - Silent type-safety bug if assumption wrong

3. **Type Tracking Fragmentation**
   - Three separate dicts track type info: `_actual_types`, `_global_var_types`, `_global_c_decl_types`
   - Must stay synchronized or silent corruption occurs

### C Runtime (mojo_runtime.c/h) - Status
**✅ SAFE**: C runtime properly uses `uintptr_t` for pointer ↔ int64_t conversions
- Correct patterns: `(int64_t)(uintptr_t)ptr` and `(type*)(uintptr_t)int64`
- No dangerous direct casts found

## Fixes Applied

### 1. Hard Throw in coerce() Method
**File**: gimple_codegen.py, lines ~137-155  
**Change**: Added validation to throw when casting int64_t → specific pointer type

```python
if src == 'int64_t' and dst.endswith(' *'):
    if dst == 'void *':
        return f"(void *){val}"  # Safe: generic opaque handle
    # THROW: Specific pointer types require validation
    raise TypeError(
        f"UNSAFE CAST: int64_t → {dst} requires type validation..."
    )
```

**Impact**: 
- ✅ Codegen-time validation (no runtime overhead)
- ✅ Catches silent type-safety bugs early
- ✅ Still allows void* (generic opaque handle)

### 2. Test Results
- test_gimple.py: **142/142 passed** ✓
- test_gimple_runner.py: **7/7 passed** ✓  
- test_runner.py: **8/8 passed** ✓
- Bootstrap compilation: **gcc-15 confirmed in use** ✓

## Remaining Work

### P0 - Type Tracking Validation
The three type-tracking dicts could fall out of sync. Recommended:
```python
def _get_tracked_type(self, var_name: str) -> str:
    """Get actual type with validation"""
    if var_name not in self._actual_types:
        raise TypeError(f"Type not tracked for {var_name}")
    return self._actual_types[var_name]
```

### P1 - Type Tracking Comments
Add documentation to high-risk areas:
- List subscript operations (element type assumes)
- Dict iteration (validates dict pointer)
- Method calls on boxed pointers
- isinstance() checks (type ID conversion)

### P2 - Runtime Integration
Current C runtime is safe, but monitor:
- File handle operations (int64_t used as void*)
- Opaque struct pointers stored in int64_t

## Key Insights

1. **Safe patterns** (same-size LP64 conversions):
   - int64_t ↔ double
   - int64_t ↔ uint64_t
   - These don't require type validation

2. **Unsafe patterns** (require validation):
   - int64_t → MojoDict* (specific type knowledge needed)
   - int64_t → char* (if origin not verified)
   - int64_t → any opaque struct pointer type

3. **Validation Points**:
   - When unboxing: Must check `_actual_types[var]` matches expected type
   - When boxing: Must update `_actual_types[var]` to track what's in the int64_t
   - At function boundaries: Validate types don't get lost

## Testing Notes

- Hard throw in coerce() catches violations at codegen time
- No performance impact (compile-time check)
- All existing tests still pass (no code was triggering the unsafe pattern)
- Suggests code generation is mostly safe OR hasn't exercised the dangerous code paths

## Recommendations

1. ✅ DONE: Hard throw for specific pointer type casting from int64_t
2. TODO: Add type validation helper with assertions throughout gimple_codegen.py  
3. TODO: Document why int64_t boxing is necessary (GIMPLE restriction)
4. TODO: Create type-safety design document for future maintainers
5. TODO: Consider replacing three type-tracking dicts with unified TypeInfo class
