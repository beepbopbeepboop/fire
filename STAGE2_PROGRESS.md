# Stage2 Compilation Progress Report

## Summary
- **Starting errors**: ~75
- **Current errors**: 18
- **Errors fixed**: ~57
- **Commits made**: 4

## Fixed Issues

### 4. Exception Handling Cast Issues (ef53539)
- **Problem**: Casting function call results in GIMPLE was invalid: `ret = (ReturnValue *) mojo_exc_obj_get();`
- **Solution**: Split into two operations with temporary variable:
  ```c
  temp = mojo_exc_obj_get();  // Get void*
  ret = (ReturnValue *) temp;  // Then cast
  ```
- **Impact**: Fixed "invalid operand in unary operation" errors in exception handlers

### 5. Struct Typedef Generation (ef53539)
- **Problem**: Struct definitions for imported classes (Interpreter, Scope, MojoFunction, etc.) weren't being emitted
- **Solution**: 
  - Added early struct typedef emission right after preamble
  - Implemented dependency-ordered emission (structs without dependencies first)
  - Added support for self-referential structs (e.g., Scope.parent is Scope*)
  - Structs now properly appear before functions that use them
- **Impact**: Fixed "unknown type name" errors for 7 structs, reduced errors from 64 to 18

### 6. Builtin Function Pointer Handling (ef53539)
- **Problem**: Bare function names like `mojo_len` couldn't be passed as arguments to GIMPLE functions
- **Solution**: Store function pointers in temporary variables with explicit address-of:
  ```c
  t = (void *)&mojo_len;
  Scope_define(scope, name, t);  // Pass temp instead of bare name
  ```
- **Impact**: Fixed "invalid argument to gimple call" errors for ~20 builtin function registrations

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

## Remaining Issues (18 errors)

### Type Conversion Issues (7-8 errors)
1. **String/Integer Type Mismatches** (6 errors)
   - `mojo_open_file` expects `char*` but receives `int`
   - `mojo_repr` expects `int` but receives `void*`
   - Assignment from `char*` to `int` type variables
   - Likely due to incorrect type inference in method calls

2. **Undeclared Variables** (1 error)
   - 'os' undeclared - import handling issue
   - Module references not being recognized

### Function Signature Mismatches (5 errors)
1. **Variable Argument Count** (3 errors)
   - `int64_t_basename` called with 2 args, expects 1
   - `int64_t_splitext` called with 2 args, expects 1  
   - `int_compile_to_gimple` called with 3 args, expects 1

2. **Pointer Type Incompatibilities** (2 errors)
   - `mojo_set_argv` second argument type mismatch
   - `int_compile_to_gimple` called with function pointer instead of char*

### Remaining Struct Issues (1 error)
- One lingering "unknown type name 'Scope'" - ordering or forward reference issue

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
- `gimple_codegen.py` - Type inference, exception handling, function pointer codegen, struct typedef generation with dependency ordering
- `runtime/mojo_runtime.h` - Exception object declarations
- `runtime/mojo_runtime.c` - Exception object implementation
- `STAGE2_PROGRESS.md` - Progress tracking (this file)

## Next Steps (Priority Order)
1. Implement proper dispatch table for method calls
2. Fix loop variable declaration issues
3. Add type wrapper functions for dynamic dispatch
4. Improve GIMPLE code generation for function pointers
5. Refactor type system to be more GIMPLE-friendly
