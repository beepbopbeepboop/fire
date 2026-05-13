# Stage2 Compilation Progress Report

## Summary
- **Starting errors**: ~75
- **Current errors**: 64  
- **Errors fixed**: ~11
- **Commits made**: 3

## Fixed Issues

### 1. Parameter Type Inference (e5126f9)
- **Problem**: Unannotated parameters like `interpreter` in `MojoFunction.__call__` were defaulting to `int` instead of their actual struct types
- **Solution**: Implemented `_infer_param_types()` method that:
  - Analyzes method bodies for member accesses on parameters
  - Infers parameter types based on field access patterns (e.g., `interpreter.scope` → `Interpreter *`)
  - Caches inferred types for use in function signature generation
- **Impact**: Fixed "request for member 'scope' in something not a structure or union" errors

### 2. Exception Object Support (ac7ff41)
- **Problem**: Try/except blocks were typed as `char *` (message strings) but code expected structs with fields like `.value`
- **Solution**: 
  - Added `_mojo_exc_obj` slot in runtime for storing typed exception objects
  - Implemented `mojo_exc_obj_set/get` functions
  - Updated exception handler code generation to use exception type annotations
  - Exception handlers now properly typed as `ReturnValue *` instead of `char *`
- **Impact**: Fixed `ret->value` dereferencing errors in exception handlers

### 3. Builtin Function Pointer Handling (3261b28)
- **Problem**: Explicit `(void *)` casts in builtin function pointer assignments caused GIMPLE parsing errors
- **Solution**: Simplified code generation to avoid problematic casting syntax
- **Impact**: Reduced GIMPLE parser conflicts

## Remaining Issues (64 errors)

### Architecture & Type System
1. **GIMPLE Strict Type Checking** (29 errors)
   - GIMPLE doesn't support implicit conversions between function pointer types
   - Function pointers need proper type annotations in GIMPLE IR
   - Affects builtin function storage in `_setup_builtins`

2. **Dynamic Method Dispatch** (3-11 errors)
   - Code tries to call `method(node)` where method is int64_t from getattr
   - Need to either:
     - Cast int64_t to function pointer before calling
     - Implement a dispatch table mechanism
     - Create wrapper functions for dynamic calls

3. **For Loop Codegen** (2 errors)
   - Undeclared loop variables ('e', etc.) in generated code
   - Issues with for loops in tuple comprehensions
   - Missing variable declarations in loop bodies

### Type Mismatches
- Function signatures don't match for dynamically called methods
- Return type mismatches from getattr-based dispatch
- Parameter count mismatches in dynamic function calls

## Architectural Issues Requiring Larger Refactoring

1. **Unified Type System**: The system treats everything as `int` but then tries to use those ints as function pointers, structs, and callable objects. This requires either:
   - A proper type representation system
   - Discriminated unions for different value types
   - Or a complete redesign of how dispatch works

2. **Exception System**: Current string-based exception system doesn't support typed exceptions well. Proper fix would require:
   - Exception object storage with type information
   - Type checking on exception handlers
   - Proper exception type hierarchy

3. **Dynamic Dispatch**: The getattr-based dispatch needs rethinking for GIMPLE compatibility:
   - Static dispatch tables where possible
   - Wrapper functions for dynamic calls
   - Or a different calling convention

## Files Modified
- `gimple_codegen.py` - Type inference, exception handling, function pointer codegen
- `runtime/mojo_runtime.h` - Exception object declarations
- `runtime/mojo_runtime.c` - Exception object implementation

## Next Steps (Priority Order)
1. Implement proper dispatch table for method calls
2. Fix loop variable declaration issues
3. Add type wrapper functions for dynamic dispatch
4. Improve GIMPLE code generation for function pointers
5. Refactor type system to be more GIMPLE-friendly
