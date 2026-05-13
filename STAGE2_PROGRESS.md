# Stage2 Compilation Progress Report

## Summary
- **Starting errors**: ~75
- **Current errors**: 13
- **Errors fixed**: ~62
- **Commits made**: 7
- **Overall reduction**: 83%

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

### 7. Parameter Type Inference Enhancement (b330ff5)
- **Problem**: Unannotated function parameters were defaulting to int type, even when used as arguments to functions expecting different types
- **Solution**: Enhanced parameter type inference to detect function calls where parameter is used as an argument
  - Added BUILTIN_PARAM_TYPES mapping for common functions (open, mojo_open_file, print, etc.)
  - Improved analyze_param_usage to track function call arguments
  - Infers parameter type from known function parameter types
- **Impact**: Better type inference for function parameters (though not all cases handled due to import complexity)

### 8. Function Signature Definitions (b330ff5)
- **Problem**: Missing function signatures in _KNOWN_SIGS prevented proper type coercion in _emit_call
- **Solution**: Added missing function signatures:
  - mojo_open_file: (int64_t, ['char *'])
  - mojo_close, mojo_write, mojo_read
  - Fixed mojo_repr to expect int instead of void*
- **Impact**: Enabled proper type coercion for file operations and other functions

### 9. Open() Builtin Translation (b330ff5)
- **Problem**: The open() builtin was being translated to mojo_open_file() without proper type coercion
- **Solution**: Changed from direct _emit to using _emit_call for proper parameter coercion
- **Impact**: Automatic casting of string arguments to mojo_open_file

### 10. Self-Referential Struct Definitions (8147454)
- **Problem**: Structs with self-referential pointers (e.g., Scope.parent is Scope*) failed compilation with "unknown type name 'Scope'"
- **Solution**: Use 'struct StructName *' syntax for self-references within typedef structs
  - C requirement: Within a typedef struct body, self-references need explicit 'struct' keyword
- **Impact**: Fixed Scope struct compilation error

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

## Remaining Issues (13 errors)

### Module/Import Issues (7 errors)
1. **Undeclared Module** (1 error)
   - 'os' module not declared/imported
   - `import os` statement not properly handled in gimple_codegen

2. **Attribute Chain Translation** (5+ errors)
   - `os.path.basename()` and `os.path.splitext()` incorrectly translated
   - Called with wrong number of arguments (2 instead of 1)
   - Functions being treated as methods with implicit `self` parameter
   - Root cause: gimple_codegen doesn't properly handle chained attribute access

3. **Module Method Dispatch** (1 error)
   - Functions from modules being called with incorrect signatures
   - `int_compile_to_gimple` called with function pointer instead of expected string

### Type Assignment Mismatches (2 errors)
- Assignment of `char*` return values to `int` variables
- Likely due to incorrect return type inference for module function calls

### Function Call Type Errors (4 errors)
1. **interpret_file Parameter** - receives `char*` but function parameter is `int`
2. **dump_file Parameter** - receives `char*` but function parameter is `int`
3. **int_write Parameter** - type mismatch on second argument
4. **mojo_set_argv Parameter** - incompatible pointer type on second argument

## Issues Requiring Larger Refactoring

### 1. Module/Import System
The current implementation doesn't properly handle:
- Python module imports (import os, import sys, etc.)
- Attribute chains on modules (os.path.basename, sys.argv, etc.)
- Module-level functions vs methods confusion

**Fix Strategy**:
- Implement proper module import handling in gimple_codegen
- Create a symbol table for module attributes
- Properly translate chained attribute access (obj.attr.method) to C function calls
- Handle module function calls with correct signatures

### 2. Function Signature Mismatches
Several issues with how functions are being called:
- Functions like `int_compile_to_gimple` being called with wrong argument count
- Module functions (int64_t_basename, int64_t_splitext) getting implicit self parameter

**Fix Strategy**:
- Track actual function signatures (not just built-in ones)
- Remove implicit self parameter for non-method functions
- Add proper function signature definitions to _KNOWN_SIGS

### 3. Type System Limitations
Current type inference has edge cases:
- Return types from module functions not properly inferred
- Type assignment from function calls to variables with different types

**Fix Strategy**:
- Improve return type inference for all functions
- Track function return types in a global registry
- Better type coercion in assignments

## Architectural Issues Requiring Larger Refactoring (OBSOLETE)

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

### Phase 1: Module/Import System (highest impact - fixes ~7 errors)
1. Implement Python module import tracking in gimple_codegen
2. Create symbol table for module attributes (e.g., os.path.*)
3. Properly translate attribute chains to function calls
4. Handle `import os` and `import sys` statements
5. Map module functions to their C equivalents with correct signatures

### Phase 2: Function Signature Registry (fixes ~3 errors)
1. Create comprehensive function signature registry
2. Track return types for all functions
3. Remove implicit self parameter for non-method functions
4. Add missing function signatures to _KNOWN_SIGS

### Phase 3: Type System Improvements (fixes remaining 3 errors)
1. Improve return type inference for module functions
2. Better type coercion in variable assignments
3. Handle function result type assignment to mismatched variable types

### Low Priority (architectural improvements)
1. Refactor dispatch table mechanism for dynamic method calls
2. Improve GIMPLE code generation for complex type conversions
3. Consider type wrapper functions for safer function pointer handling
