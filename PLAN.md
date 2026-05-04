# Language Implementation Plan

## Current Session (2026-05-04) - FINAL UPDATE

**Final Status:** Major stdlib support improvements via generator modifications. **168/277 files passing (60.6%).**

**Progress: 107 → 168 files (+61 = 22.0% improvement)**

**Changes Made to Generator (compiler_gen.py):**
- ✅ Support comptime if/elif statements with elif clause support
- ✅ Support postfix caret operator `^` for ownership transfer
- ✅ Improved empty subscript handling `[]` with dummy index
- ✅ Fixed subscript parser indentation and control flow
- ✅ Balanced paren tracking in struct/trait trait lists
- ✅ Variadic parameter support `*args: *Ts`
- ✅ Type unpacking syntax `*Type` in type annotations
- ✅ Unpacking in function calls `func(*args)`
- ✅ Unpacking in subscripts `Type[*Ts]`
- ✅ Tuple unpacking in var declarations `var a, b = ...`

**Test Coverage:**
- All 142 existing tests still passing (0 regressions)
- Generator-based approach ensures code consistency

**Remaining Top Blocking Issues (117 failing files - 42.2%):**
1. Expected RBRACKET got ASSIGN (15 files) - Complex subscript edge cases
2. Unexpected COMMA (15 files) - Tuple unpacking in expressions (non-var)
3. Unexpected COLON (9 files) - Type annotation context issues
4. Expected NAME got LBRACKET (9 files) - Generic syntax
5. Expected RBRACE got ASSIGN (6 files) - Dictionary/set literal syntax

**Architecture Insight:**
- Generator-based approach continues to prove effective
- Systematic error analysis drives targeted fixes
- Each improvement cascades to fix multiple related issues

---

## Session Summary (2026-04-28)

**Accomplishments**:
- ✅ **Priority 4 Complete**: All 7 GIMPLE specifications created (700+ lines)
  - gimple-type-system.md, gimple-runtime.md, gimple-exceptions.md, gimple-closures.md, gimple-iterators.md, gimple-memory.md, gimple-generics.md
- ✅ **Priority 3 Enhanced**: gimple_spec_gen.py now extracts and generates code
  - 23 operators, 9 statements, 7 expressions, 13 types extracted and generatable
  - ~250 lines of Python auto-generated from specs
- ✅ **Documentation Consolidated**: CODEGEN-IMPL.md merged into IMPL.md (unified 586-line file)
- ✅ **Moved to IMPL.md**: Complete GIMPLE specifications, code generation framework, and codegen implementation details documented

**Current Status**: 
- Priority 4: ✅ 100% Complete
- Priority 3: 🔄 50% Complete (dispatch tables generated, awaiting integration)
- All tests passing (7/7 execution tests)
- Repo fully consolidated with single source of truth for implementation docs

---

## Overview

The Mojo reference implementation consists of:

1. **mojo_compiler.py** — Lexer, parser, and AST (generated from `.md` specs via `compiler_gen.py`)
2. **gimple_codegen.py** — Lowers AST to C with `__GIMPLE` annotations (hand-written, should be generated)
3. **module_loader.py** — Resolves and loads `.mojo` modules (hand-written, should be generated)
4. **test_*.py** — Test runners and validators

Specification files (`.md`) define language semantics. Currently, specs cover:
- `mojo-operators.md` — Operator precedence and definitions
- `mojo-simple-statements.md` — Statement types (partial: imports listed but not detailed)
- `mojo-expressions.md` — Expression types and operations
- `mojo-function-declarations.md` — Function definition syntax
- `mojo-manual-*.md` — Language features and idioms

See `IMPL.md` for everything that is already working.

---

## Prioritized TODO List

> **Note**: Completed priorities (1, 2, 4) are documented in IMPL.md. This section focuses on active and future work.

**Priority 3** 🔄 **IN PROGRESS** (50% complete): Generate gimple_codegen.py from Specs

**Completed**:
- ✅ Enhanced gimple_spec_gen.py extracts from specifications
- ✅ Extracts: 23 operators, 9 statements, 7 expressions, 13 types
- ✅ Generates: Dispatch tables, type ranks, handler mappings (~250 lines)

**Next Steps**:
- 📋 Generate full operator lowering method bodies
- 📋 Integrate generated dispatch code back into gimple_codegen.py
- 📋 Reduce gimple_codegen.py from 2900 to ~2650 lines (hand-written only)

**Priority 5**: Create missing Mojo specification files
- mojo-type-system.md — Type system for Mojo language
- mojo-runtime-api.md — Runtime library documentation

**Priority 6 (Hard/Deferred)**: GPU Codegen & Mojo-from-Python Extensions
- Full GPU kernel compilation (deferred: GPU semantics not emulatable in Python)
- PythonModuleBuilder API (deferred: design pending)

---

## TODO: Code Generation from Specs

These items require generating Python code from markdown specification files instead of hand-writing.

### Generate module_loader.py from Spec

**Status**: module_loader.py currently hand-written; module system documented in GNU-EXTENSIONS.md.

**Task**:
- Create `module_spec_gen.py` to generate `module_loader.py` from GNU-EXTENSIONS.md (Module System Implementation section)
- Extract module path resolution rules from spec
- Generate symbol extraction logic
- Generate module caching code

**Impact**: Module loading behavior defined declaratively in spec; changes to module system require only spec updates.

---

### Generate gimple_codegen.py from Specs

**Status**: gimple_codegen.py currently hand-written (2900+ lines); GIMPLE lowering rules documented in GNU-EXTENSIONS.md.

**Subtasks**:

#### Generate Operator Lowering Rules
- Parse `mojo-operators.md` for operator definitions
- Extract from GNU-EXTENSIONS.md (Operators section) for GIMPLE lowering rules
- Generate `_lower_binop()`, `_lower_unary()` dispatch tables
- Generate type promotion rules from `TypeLattice` specification

#### Generate Statement Lowering Rules
- Parse `mojo-simple-statements.md` for statement types
- Extract GIMPLE lowering from GNU-EXTENSIONS.md (Statements section)
- Generate `lower_stmt()` method bodies
- Generate basic block sequencing for control flow

#### Generate Expression Lowering Rules
- Parse `mojo-expressions.md` for expression types
- Extract GIMPLE lowering rules from GNU-EXTENSIONS.md (Expressions section)
- Generate `lower_expr()` method bodies
- Generate subexpression temp allocation

**Impact**: GIMPLE backend becomes maintainable and extensible via specs. Reducing hand-written code from 2900+ lines to generated + preamble.

---

### Extend GNU-EXTENSIONS.md Module System Section

**Status**: Module system documented with limitations identified; TODO items listed.

**Missing Details** (to be added to GNU-EXTENSIONS.md):
- Parameter type information in module signatures (currently `(void)`)
- Struct method mangling rules for imported types
- Generic type parameters and instantiation
- Private/public symbol visibility enforcement
- Module initialization and top-level code execution
- Circular import detection and error handling
- Re-export semantics (`from X import *` then re-export)
- Multiple search path handling (MOJO_PATH, stdlib, current dir)

**Action**: Enhance GNU-EXTENSIONS.md module system section with parameter signatures and advanced features.

---

### Create Specs for Unspecified Features

**Status**: Several features implemented but not specced.

**Missing Specs**:
- `gimple-runtime.md` — Runtime helper functions (mojo_list_*, mojo_dict_*, etc.)
- `gimple-type-system.md` — Type lattice rules and type resolution
- `gimple-exceptions.md` — Exception handling lowering (try/except/finally)
- `gimple-closures.md` — Nested function capture and lifting
- `gimple-iterators.md` — Iterator protocol lowering
- `gimple-generics.md` — Generic type parameter handling
- `gimple-memory.md` — Pointer types and unsafe operations

---

## TODO: Hard

### Full GPU Codegen

**Status**: stub classes emitted (`DeviceContext`, `DeviceBuffer`, `HostBuffer`).

GPU execution model has no Python equivalent. Full codegen would require:
- `ctx.enqueue_function(kernel, *args, grid_dim=..., block_dim=...)` → no-op stub.
- `barrier()`, `syncwarp()` → no-op stubs.
- `block_idx`, `thread_idx`, `global_idx` → constants returning 0.
- `shuffle_*`, `prefix_sum` → warp-reduction stubs.
- `LayoutTensor`, `Layout` → stub classes with `__getitem__`/`__setitem__`.
- Tagged **deferred** — GPU semantics cannot be faithfully emulated in Python.

---

### Mojo-from-Python Extension Modules

**Status**: not implemented.

`PythonModuleBuilder`, `def_py_init()`, `def_function()`, `def_method()` etc. are the
Mojo-side API for building Python extension modules. No Formal English mapping defined yet.
Tagged **deferred** pending a design.

---

---

## TODO: Enhance Existing Specs

### Expand mojo-simple-statements.md

**Current state**: Lists import forms but lacks detail on semantics, module resolution, and aliasing.

**Missing content**:
- Detailed import semantics and scope rules
- Module resolution algorithm (search paths, file naming conventions)
- Aliasing and name shadowing rules
- Re-export semantics
- Circular import detection

---

### Expand mojo-operators.md

**Current state**: Lists operator precedence; lacks detail on overloading, lowering, and special forms.

**Missing content**:
- Matrix multiply operator `@` details (precedence: level 4, same as `*`)
- Operator overloading via dunder methods (`__add__`, `__matmul__`, etc.)
- Augmented assignment operators (`@=`, etc.)
- Comparison chaining semantics
- Custom operator definitions on user types

---

### Add Spec: mojo-type-system.md

**Status**: Not created; type rules scattered across multiple files.

**Should define**:
- Type lattice and promotion rules
- Numeric type hierarchy (int8 < int16 < int32 < int64 < float < double)
- Pointer types and `UnsafePointer` semantics
- Generic type parameters and instantiation
- Struct field type resolution
- Function return type inference

---

### Add Spec: mojo-runtime-api.md

**Status**: Not created; runtime functions documented only in code.

**Should define**:
- Runtime type: `MojoList`, `MojoDict`, `MojoSet`, `MojoStr`
- Container operations: `mojo_list_new()`, `mojo_list_append_*()`, etc.
- Pointer operations: `_mojo_at_T()`, malloc/free helpers
- Exception API: `mojo_try_push()`, `mojo_raise()`, etc.
- String operations: `mojo_str_len()`, `mojo_str_char_at()`, etc.

---

## TODO: Medium

### Conditional Trait Conformance (`where` clauses)

**Status**: spec extraction captures `has_where_clause`; `where` is skipped in parser.

- `struct Wrapper[T](Writable where conforms_to(T, Writable))` → emit `class Wrapper` with comment.
- `def __bool__(self) where conforms_to(Self.T, Boolable)` → emit method unconditionally, add comment.
- The `where` clause is informational only in Python output.

---

### Lifetime/Origin Tracking

**Status**: partially dropped; `ref` return type stripped; origin annotations dropped.

Mojo's `ref`, `ImmutOrigin`, `MutOrigin`, origin unions, and `ref` return values have
no Python equivalent:
- `ref x: T` parameter → emit as `x: T` (plain parameter, convention prefix stripped).
- `ref` return type → drop `ref` keyword.
- `Pointer(to=value)`, `UnsafePointer(to=value)` → emit as stub `Pointer(value)`.
- Origin annotations → drop entirely.

---

### `UnsafePointer` Full Memory Semantics

**Status**: stub class only in Python output.

Operations not translatable to Python:
- `ptr.bitcast[T]()` → stub returning `ptr`.
- `ptr.strided_load(stride)` / `ptr.strided_store(v, stride)` → stub.
- `ptr.gather(offsets)` / `ptr.scatter(v, offsets)` → stub.
- `ptr.destroy_pointee()` / `ptr.take_pointee()` → stub.
- `alloc[T](n)` → `[None]*n` stub.
- `ptr.free()` → no-op.

---

## Deferred

- **GPU constructs** — `DeviceContext`, `DeviceBuffer`, kernel launch
- **`PythonModuleBuilder`** — Mojo extension module API
