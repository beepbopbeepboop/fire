# Specification Audit Report

**See PLAN.md for authoritative next steps and priorities.**

This document summarizes the audit of markdown specification files and consolidation of implementation-specific extensions into GNU-EXTENSIONS.md.

**Key Finding**: All implementation-specific content (module system, GIMPLE lowering, code generation) consolidated into **GNU-EXTENSIONS.md**. Upstream .md files (mojo-*.md) are read-only reference documentation from official Mojo.

## New Extension File Created

### GNU-EXTENSIONS.md

**Purpose**: Comprehensive documentation of implementation-specific extensions and GIMPLE lowering rules.

**Contents**:
- **Module System Implementation**
  - Official module/package semantics from upstream
  - Module resolution algorithm (implementation-specific)
  - Symbol extraction rules
  - C backend lowering (GIMPLE extern declarations)
  - Current limitations and TODOs
  
- **GIMPLE Code Generation Specification**
  - General principles (temps, block labels, type promotion, GIMPLE constraints)
  - Operator lowering rules
    - Binary: arithmetic, comparison, logical, bitwise, matrix multiply
    - Unary: arithmetic, logical
    - Augmented assignment
  - Expression lowering (literals, subscripts, member access, calls, ternary, walrus)
  - Statement lowering (declarations, assignments, control flow, returns, try/except, raises)
  - Type resolution and TypeLattice rules
  - Preamble helpers (containers, pointers, exceptions)
  - Known limitations and future enhancements
  
- **Code Generation Pipeline**
  - Current architecture
  - Component descriptions
  - Future: Code generation from specs (TODO items)
  
- **Integration with Official Mojo**
  - References to upstream documentation
  - Conflicts and extensions
  - Documentation strategy

**Scope**: Covers all implementation-specific features, lowering rules, and code generation details.

**TODOs Identified**:
- Module system:
  - Parameter information lost (using `(void)` signature)
  - Struct method calls on imported types not supported
  - Generic types not supported
  - Private/public distinction not enforced
  - Module initialization not implemented
  
- GIMPLE codegen:
  - SSA form output (`__GIMPLE (ssa)` with phi nodes)
  - GPU kernel launch
  - Python interop (CPython embedding)
  - Custom iterators beyond standard protocol
  - Complex function signatures with parameters
  - Generic type instantiation (monomorphization)
  - Async/await coroutine transformation

---

## Audit of Existing Specification Files

### mojo-simple-statements.md

**Current State**: Mentions imports but lacks detail.

**Issues Found**:
- Import semantics not fully specified
- Module resolution algorithm not described
- Aliasing and scoping rules not documented

**Recommendation**: Reference new `mojo-modules.md` for import details; enhance with scope rules.

**Enhancement Priority**: Medium (impacts module system documentation)

---

### mojo-operators.md

**Current State**: Lists operator precedence; brief descriptions.

**Issues Found**:
- Matrix multiply operator `@` listed but not detailed
- No information on operator overloading (dunder methods)
- Augmented assignment with `@=` not mentioned
- Comparison chaining semantics not explained

**Recommendation**: 
- Add matrix multiply details (precedence level 4, delegates to `__matmul__` method)
- Document operator overloading requirements
- Reference gimple-codegen-spec.md for lowering details

**Enhancement Priority**: Medium (impacts operator implementation)

---

### mojo-expressions.md

**Current State**: Lists expression types; lacks detail on operators and overloading.

**Issues Found**:
- Operator expressions not comprehensively listed
- Comparison chaining not documented
- Operator precedence reference needed

**Recommendation**: 
- Cross-reference with mojo-operators.md
- Document comparison chaining semantics
- Add examples of operator results and type inference

**Enhancement Priority**: Low (basic information present)

---

### Missing Specification Files (Identified in Audit)

The following specification files are referenced in gimple-codegen-spec.md but do not exist:

1. **gimple-runtime.md** (NOT CREATED)
   - Runtime helper functions (mojo_list_*, mojo_dict_*, etc.)
   - Container and string operations
   - Exception handling runtime

2. **gimple-type-system.md** (NOT CREATED)
   - Type lattice rules and promotion
   - Numeric type hierarchy
   - Pointer type semantics
   - Generic type handling

3. **gimple-exceptions.md** (NOT CREATED)
   - Exception handling lowering
   - Try/except/finally semantics
   - Exception object structure and API

4. **gimple-closures.md** (NOT CREATED)
   - Nested function capture rules
   - Environment struct generation
   - Closure lifting transformation

5. **gimple-iterators.md** (NOT CREATED)
   - Iterator protocol specification
   - Custom iterator implementation
   - Comprehension lowering

6. **gimple-generics.md** (NOT CREATED)
   - Generic type parameter handling
   - Monomorphization rules
   - Template instantiation

7. **gimple-memory.md** (NOT CREATED)
   - Pointer type semantics
   - UnsafePointer operations
   - Memory allocation and deallocation
   - Pointer arithmetic rules

8. **mojo-type-system.md** (NOT CREATED)
   - Type lattice specification
   - Type inference rules
   - Type promotion and coercion

9. **mojo-runtime-api.md** (NOT CREATED)
   - Runtime data structures (MojoList, MojoDict, etc.)
   - Runtime function signatures
   - Container API specification

---

## Code Generation Gaps

The following Python files are currently hand-written but should be generated from specs:

### module_loader.py

**Current**: Hand-written Python module loader.

**Should Be**: Generated from `mojo-modules.md` via `module_spec_gen.py`.

**Generation Tasks**:
1. Extract module path resolution rules from spec
2. Generate symbol extraction logic based on spec examples
3. Generate module caching code
4. Generate error handling for module not found

**Estimated Complexity**: Medium (straightforward path resolution and caching)

---

### gimple_codegen.py

**Current**: 2900+ lines of hand-written GIMPLE lowering code.

**Should Be**: Generated from `mojo-operators.md`, `mojo-simple-statements.md`, `mojo-expressions.md`, and `gimple-codegen-spec.md` via `gimple_spec_gen.py`.

**Generation Tasks**:
1. Parse operator specs for lowering rules
2. Generate binary operator dispatch tables from rules
3. Generate unary operator dispatch tables
4. Generate statement lowering methods
5. Generate expression lowering methods
6. Generate type promotion logic from TypeLattice specification
7. Generate preamble helper function declarations

**Estimated Complexity**: High (complex code generation; many edge cases)

**Risk**: Current implementation has specialized handling and optimizations that spec-based generation might not capture.

**Recommendation**: Start with operator lowering; incrementally add statement and expression rules.

---

## Summary of Changes

### Files Created
1. `GNU-EXTENSIONS.md` - ~650 lines, consolidated module system and GIMPLE lowering specs
2. `SPEC-AUDIT.md` - This file, audit results

### Files Enhanced
1. `PLAN.md` - Added 150+ lines of TODOs for code generation from specs

### Files Consolidated
- `mojo-modules.md` (temporary, content moved to GNU-EXTENSIONS.md)
- `gimple-codegen-spec.md` (temporary, content moved to GNU-EXTENSIONS.md)

### Files NOT Modified (Upstream, Read-Only)
1. `mojo-simple-statements.md` - Upstream file, references gnu-modules in mojo-manual-language-basics.md
2. `mojo-operators.md` - Upstream file
3. All `mojo-manual-*.md` - Upstream files

### Test Status
- All 142 gimple codegen tests pass ✓
- All 7 GIMPLE execution tests pass ✓
- Module import system tests pass ✓

---

**For implementation priorities and next steps, see PLAN.md (authoritative source).**

**Audit Date**: 2026-04-28  
**Status**: Complete; 9 specification files identified as missing; consolidated to GNU-EXTENSIONS.md
