# DispatchSolver Phase B Implementation

**Status**: ✓ Complete  
**Date**: 2026-05-12  
**Files Modified**: `gimple_codegen.py`  
**Tests Added**: `test_dispatch_phase_b.py`

---

## Overview

Phase B implements dispatch table planning and C code generation. It takes the dynamic dispatch patterns identified in Phase A and generates complete C struct typedefs, initializations, and dispatch call sequences.

**Key Accomplishment**: Can now emit production-quality C code for vtables that replace dynamic Python patterns.

---

## What Was Implemented

### 1. DispatchTable Class (lines 365–488)

A complete representation of a planned virtual method table with methods to generate C code.

**Fields**:
- `name`: C identifier for the dispatch table (e.g., "interpreter_execute_dispatch")
- `pattern_id`: Links back to the original dispatch pattern
- `dispatch_type`: How dispatch works ('FUNC_POINTER', 'ARRAY_INDEX', 'TYPE_SWITCH')
- `methods`: List of (method_name, c_signature, full_c_name) tuples
- `struct_fields`: For FUNC_POINTER, maps field names to signatures
- `dispatch_index_map`: For ARRAY_INDEX, maps method names to indices

**Key Methods**:

#### `add_method(method_name, c_signature, full_c_name)`
Registers a method in the dispatch table.

```python
table.add_method(
    'execute_Module',
    'int (*execute_Module)(void *self, void *node)',
    'Interpreter_execute_Module'
)
```

#### `emit_typedef() -> str`
Generates C struct typedef for the dispatch table.

**FUNC_POINTER style output**:
```c
typedef struct {
  int (*execute_Module)(void *self, void *node);
  int (*execute_FunctionDef)(void *self, void *node);
  ...
} interpreter_execute_dispatch_t;
```

**ARRAY_INDEX style output**:
```c
typedef int (*interpreter_execute_dispatch_fn)(void *, void *);
```

#### `emit_table_init() -> str`
Generates C initialization code for the dispatch table.

**FUNC_POINTER style output**:
```c
static const interpreter_execute_dispatch_t interpreter_execute_dispatch = {
  .execute_Module = Interpreter_execute_Module,
  .execute_FunctionDef = Interpreter_execute_FunctionDef,
  ...
};
```

**ARRAY_INDEX style output**:
```c
static const interpreter_execute_dispatch_fn interpreter_execute_dispatch[] = {
  Interpreter_execute_Module,
  Interpreter_execute_FunctionDef,
  ...
};
```

#### `emit_dispatch_call(obj, method_idx, args) -> str`
Generates C code to invoke a dispatched function.

**FUNC_POINTER style**:
```c
interpreter_execute_dispatch.execute_Module(self, node)
```

**ARRAY_INDEX style**:
```c
interpreter_execute_dispatch[0](self, node)
```

**Helper Methods**:

- `get_method_index(method_name)`: Returns position in dispatch table
- `get_method_count()`: Returns number of methods
- `get_c_function_pointer_type()`: Returns C function pointer type signature

---

### 2. Enhanced DispatchSolver (Phase B features)

#### `_plan_dispatch_tables()`
This method replaces the Phase A placeholder. Now it:

1. **Deduplicates patterns**: Groups patterns with identical callees
2. **Creates DispatchTable objects**: One per unique set of callees
3. **Populates methods**: Adds all possible callees as dispatch table methods
4. **Infers signatures**: Extracts return types from function_return_types
5. **Stores results**: Populates `self.dispatch_tables` dict

**Process**:
```
For each dispatch pattern:
  1. Get its possible_callees set
  2. Create frozenset(callees) as dedup key
  3. If not seen before:
     - Create new DispatchTable
     - For each callee:
       * Extract method name
       * Infer return type
       * Create C signature
       * Add to table
  4. Store keyed by callees frozenset
```

#### `_generate_table_name(pattern_id, pattern) -> str`
Creates C-safe identifiers from pattern IDs.

```
"Interpreter_execute:getattr_self:12345" → "interpreter_execute_dispatch"
```

#### `_extract_method_name(full_name) -> str`
Extracts short method name from mangled C name.

```
"Interpreter_execute_Module" → "execute_Module"
"Scope_set" → "set"
```

#### `get_dispatch_tables() -> dict`
Returns all planned dispatch tables keyed by callee set.

---

## Two Dispatch Strategies

### Strategy 1: FUNC_POINTER (Primary for Phase B)

**Characteristics**:
- Uses struct with function pointer fields
- Each method is a field in the struct
- Fast lookup (struct field access ≈ 0 cycles)
- Better for small number of methods (~2-10)

**Generated Code**:
```c
typedef struct {
  int (*method_a)(void *self, void *node);
  int (*method_b)(void *self, void *node);
} dispatch_t;

static const dispatch_t dispatch = {
  .method_a = actual_method_a,
  .method_b = actual_method_b,
};

// Call:
dispatch.method_a(self, node)
```

**Pros**: Type-safe, clear, efficient  
**Cons**: Slightly larger struct memory (8 bytes per method on 64-bit)

### Strategy 2: ARRAY_INDEX

**Characteristics**:
- Uses array of function pointers
- Index computed from node type or key
- Very compact (just pointer per entry)
- Better for larger dispatch tables (10+ methods)

**Generated Code**:
```c
typedef int (*dispatch_fn)(void *, void *);

static const dispatch_fn dispatch[] = {
  actual_method_a,
  actual_method_b,
};

// Call:
dispatch[index](self, node)
```

**Pros**: Compact, cache-friendly for sequential access  
**Cons**: Requires index computation, all methods must have same signature

---

## Test Coverage

### Unit Tests (`test_dispatch_phase_b.py`)

1. **test_dispatch_table_creation()**
   - Create DispatchTable, add methods
   - Verify method indexing works
   - Result: ✓ Pass

2. **test_dispatch_table_typedef_generation()**
   - Generate C typedef for FUNC_POINTER dispatch
   - Verify struct definition is syntactically correct
   - Result: ✓ Pass

3. **test_dispatch_table_init_generation()**
   - Generate C initialization code
   - Verify static const initialization matches methods
   - Result: ✓ Pass

4. **test_dispatch_call_generation()**
   - Generate dispatch call code (by index and by name)
   - Verify correct method invocation
   - Result: ✓ Pass

5. **test_array_dispatch_table()**
   - Test ARRAY_INDEX dispatch strategy
   - Verify array initialization and indexing
   - Result: ✓ Pass

6. **test_dispatch_solver_phase_b()**
   - Integration: Run full DispatchSolver.analyze() on myinterpreter pattern
   - Verify dispatch tables are planned
   - Verify all 8 execute_* methods are in the table
   - Result: ✓ Pass

7. **test_full_c_code_generation()**
   - Generate complete, real C code for interpreter pattern
   - Verify typedef and initialization are valid C
   - Show example dispatch function
   - Result: ✓ Pass

### All Tests Pass

✓ 7 Phase B tests: All pass  
✓ 4 Phase A tests: All pass (no regressions)  
✓ 142 gimple_codegen tests: All pass (no regressions)

---

## Example: From Pattern to C Code

### Input: myinterpreter.mojo Pattern

```python
class Interpreter:
    def execute(self, node):
        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)
        return method(node)
    
    def execute_Module(self, node): return 1
    def execute_FunctionDef(self, node): return 2
    # ... 6 more execute_* methods
```

### Phase A Output

```
Pattern detected: getattr(self, f'execute_{type}', None)
Possible callees:
  - Interpreter_execute_Module
  - Interpreter_execute_FunctionDef
  - Interpreter_execute_StructDef
  - Interpreter_execute_IfStmt
  - Interpreter_execute_ForStmt
  - Interpreter_execute_WhileStmt
  - Interpreter_execute_AssignStmt
  - Interpreter_execute_ExprStmt
```

### Phase B Output: Generated C Code

```c
// Typedef (from emit_typedef)
typedef struct {
  int (*execute_Module)(void *self, void *node);
  int (*execute_FunctionDef)(void *self, void *node);
  int (*execute_StructDef)(void *self, void *node);
  int (*execute_IfStmt)(void *self, void *node);
  int (*execute_ForStmt)(void *self, void *node);
  int (*execute_WhileStmt)(void *self, void *node);
  int (*execute_AssignStmt)(void *self, void *node);
  int (*execute_ExprStmt)(void *self, void *node);
} interpreter_execute_dispatch_t;

// Initialization (from emit_table_init)
static const interpreter_execute_dispatch_t interpreter_execute_dispatch = {
  .execute_Module = Interpreter_execute_Module,
  .execute_FunctionDef = Interpreter_execute_FunctionDef,
  .execute_StructDef = Interpreter_execute_StructDef,
  .execute_IfStmt = Interpreter_execute_IfStmt,
  .execute_ForStmt = Interpreter_execute_ForStmt,
  .execute_WhileStmt = Interpreter_execute_WhileStmt,
  .execute_AssignStmt = Interpreter_execute_AssignStmt,
  .execute_ExprStmt = Interpreter_execute_ExprStmt,
};

// Usage (from emit_dispatch_call)
int Interpreter_execute(Interpreter *self, int node_type, void *node) {
    switch (node_type) {
    case 0: return interpreter_execute_dispatch.execute_Module(self, node);
    case 1: return interpreter_execute_dispatch.execute_FunctionDef(self, node);
    case 2: return interpreter_execute_dispatch.execute_StructDef(self, node);
    case 3: return interpreter_execute_dispatch.execute_IfStmt(self, node);
    case 4: return interpreter_execute_dispatch.execute_ForStmt(self, node);
    case 5: return interpreter_execute_dispatch.execute_WhileStmt(self, node);
    case 6: return interpreter_execute_dispatch.execute_AssignStmt(self, node);
    case 7: return interpreter_execute_dispatch.execute_ExprStmt(self, node);
    }
    return 0;
}
```

---

## Performance Characteristics

- **Typedef emission**: O(m) where m = number of methods
- **Table init emission**: O(m) 
- **Dispatch call generation**: O(1) for FUNC_POINTER, O(log m) for ARRAY_INDEX index lookup
- **Memory overhead**: 8 bytes per method (64-bit pointers) for FUNC_POINTER
- **Dispatch overhead**: 1 indirect function call (same as virtual methods in C++)

---

## Design Decisions

### Why FUNC_POINTER as Primary?

1. **Type safety**: Each method has explicit signature in typedef
2. **Readability**: Method names appear in generated code
3. **GIMPLE compatible**: Struct field access works in __GIMPLE
4. **Small overhead**: Negligible performance impact vs. dynamic dispatch

### Why Support ARRAY_INDEX?

1. **Scalability**: For very large dispatch tables (100+ methods)
2. **Compactness**: 8 bytes per entry vs. potential struct overhead
3. **Cache friendly**: Sequential access pattern for large tables

### Why Deduplicate Patterns?

Multiple patterns might have identical callees (e.g., different getattr calls dispatching to same methods). Deduplication:
- Reduces generated code size
- Shares vtable across patterns
- Enables future optimization (vtable caching)

---

## Integration Points for Phase C

Phase C will use Phase B output to:

1. **Emit typedef and init** before functions
2. **Replace getattr calls** with dispatch table lookups
3. **Replace dict subscripts** with array indexing
4. **Pass dispatch table** to codegen context
5. **Generate dispatch index** computation from node type

Example Phase C integration:
```python
# In GimpleGen.gen_module()
for table in self.dispatch_solver.get_dispatch_tables().values():
    parts.append(table.emit_typedef())
    parts.append(table.emit_table_init())
```

---

## Limitations & Future Improvements

### Current Limitations (Phase B)

1. **Fixed parameter types**: Currently uses `void *` for all parameters
   - Phase C will specialize based on actual types

2. **Generic return types**: Uses function_return_types, doesn't infer precise signatures
   - Phase C will track actual return types per method

3. **Manual dispatch index**: Table doesn't know how to compute node_type
   - Phase C will generate index computation

4. **No attribute caching**: Each call accesses vtable
   - Phase C could add simple caching strategies

### Planned Improvements (Phase C)

1. **Typed function pointers**: `int (*method)(Interpreter *self, Module *node)`
2. **Automatic index computation**: Generate switch/case from node types
3. **Vtable packing**: Optimize memory layout for hot methods
4. **Dispatch filtering**: Skip methods that are provably unreachable

---

## Code Quality

✓ All 7 Phase B tests pass  
✓ All 4 Phase A tests still pass (no regressions)  
✓ All 142 gimple_codegen tests still pass (no regressions)  
✓ Generated C code is syntactically correct

---

## Summary

Phase B successfully implements:

1. ✓ **DispatchTable class** with full C code generation
2. ✓ **Two dispatch strategies** (FUNC_POINTER and ARRAY_INDEX)
3. ✓ **Typedef generation** for virtual method tables
4. ✓ **Initialization code** for vtable instances
5. ✓ **Dispatch call generation** for method invocation
6. ✓ **Pattern deduplication** to avoid redundant tables
7. ✓ **Integration with Phase A** to plan tables from patterns

The foundation is in place for Phase C (GimpleGen integration and code transformation).

Next: Proceed to Phase C to integrate dispatch tables into the GIMPLE code generation pipeline.
