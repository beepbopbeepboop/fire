# Type System Integration into Compilation Pipeline

## Overview

The new comprehensive type system (from `type_system.py`) integrates with the existing compilation pipeline to catch type invariant violations before code generation. This document describes integration points and how to enable type checking.

## Compilation Pipeline with Type Checking

```
SOURCE CODE (Mojo Python)
    ↓
PHASE 0: Lexing & Parsing
    → Create AST with no type information
    ↓
PHASE 1: Pre-passes (Type Analysis & Inference)
    ├─ 1.1: Infer return types
    ├─ 1.2: Infer parameter types
    │        └─ [NEW] Lock parameter types with INFERENCE_IDEMPOTENCE
    ├─ 1.3: Infer local variable types
    │        └─ [NEW] Check TEMPORAL_MONOTONICITY on assignments
    ├─ 1.3b: Verify type consistency
    │         └─ [NEW] Check BIT_WIDTH_PRESERVATION on operations
    ├─ 1.3c: Check element type propagation
    │         └─ [NEW] Check ELEMENT_TYPE_PRESERVATION on subscripts
    └─ 1.3d: Report all invariant violations
             └─ STOP if errors found
    ↓
PHASE 2a: Code Generation (with type info guidance)
    ├─ Generate casts from type information
    │  └─ [NEW] Check OPAQUE_POINTER_TRACKING at call sites
    ├─ Pick correct function calls based on types
    │  └─ [NEW] Verify function signatures match
    └─ Generate explicit type conversions
    ↓
PHASE 2b: C Code Assembly
    → Combine all code fragments into final C file
    ↓
PHASE 3: C Compilation
    → gcc -fgimple (verifies GIMPLE semantics)
    ↓
RUNTIME
    → Execute (no type information overhead)
```

## Integration Points in `gimple_codegen.py`

### 1. Phase 1.1-1.3: Type Inference (Before Code Gen)

```python
# At start of gen_module, create checker
checker = InvariantChecker(verbose=True)

# During parameter type inference (Pass 1.2)
for func in all_functions:
    inferred_params = self._infer_param_types(func)
    for param_name, param_type in inferred_params.items():
        try:
            checker.lock_inferred_type(func.name, Type(...), "1.2", (filename, line))
        except TypeSystemError as e:
            checker.report_error(e)

# During local variable type inference (Pass 1.3)
for assignment in func.body:
    var_name = assignment.target.name
    var_type = infer_type(assignment.value)
    try:
        checker.check_temporal_monotonicity(var_name, var_type, (filename, line))
    except TypeSystemError as e:
        checker.report_error(e)

# During binary operations (Pass 1.3b)
for binop in all_binary_ops:
    left_type = get_type(binop.left)
    right_type = get_type(binop.right)
    try:
        result_type = checker.check_bit_width_preservation(
            left_type, binop.op, right_type, (filename, line)
        )
    except TypeSystemError as e:
        checker.report_error(e)

# During subscript operations (Pass 1.3c)
for subscript in all_subscripts:
    container_type = get_type(subscript.obj)
    try:
        element_type = checker.check_element_type_preservation(
            container_type, (filename, line)
        )
    except TypeSystemError as e:
        checker.report_error(e)

# At end of Phase 1: Check for errors
if checker.has_errors():
    print(checker.format_errors())
    return None  # Stop compilation
```

### 2. Phase 2a: Code Generation with Type Checking

```python
# When generating function calls
def _emit_call(self, ret_type, result_var, fname, arg_pairs):
    # Check parameter types match argument types
    param_types = self.func_param_types.get(fname, [])
    
    for i, (arg_type, arg_val) in enumerate(arg_pairs):
        param_type = param_types[i] if i < len(param_types) else arg_type
        
        # NEW: Check OPAQUE_POINTER_TRACKING
        try:
            self.type_checker.check_opaque_pointer_tracking(
                arg_type, param_type, i, fname, (self._current_filename, self._current_line)
            )
        except TypeSystemError as e:
            self.type_checker.report_error(e)
        
        # Generate appropriate cast if needed
        if arg_type != param_type:
            # Use type system information to generate correct cast
            self._emit_type_cast(arg_type, param_type, arg_val)

# When handling subscripts
def _lower_subscript(self, obj, index):
    container_type = self.var_types.get(obj.name)
    
    # NEW: Check ELEMENT_TYPE_PRESERVATION
    try:
        element_type = self.type_checker.check_element_type_preservation(
            container_type, (self._current_filename, self._current_line)
        )
    except TypeSystemError as e:
        self.type_checker.report_error(e)
        # Continue with best guess or return error
        return None
    
    # Use element type to pick correct function
    if element_type.base == 'double':
        return self._emit(f"mojo_list_get_double({obj}, {index})")
    else:
        return self._emit(f"mojo_list_get_int({obj}, {index})")
```

## Usage Example: Compile with Type Checking

```python
from gimple_codegen import GimpleGen
from type_system import InvariantChecker

def compile_with_type_checking(mojo_source, filename):
    """Compile with comprehensive type system checking"""
    
    gen = GimpleGen()
    gen.type_checker = InvariantChecker(verbose=True)
    
    # Parse
    tokens = tokenize(mojo_source)
    stmts = Parser(tokens).parse_module()
    
    # Generate with type checking
    gimple_code = gen.gen_module(stmts)
    
    # If type errors found, report them
    if gen.type_checker.has_errors():
        print(gen.type_checker.format_errors())
        return None
    
    return gimple_code


# Example compile
code = """
def advance(bodies):
    bodies[0][0] = 1.0

bodies = [[1.0, 2.0]]
advance(bodies)
"""

gimple = compile_with_type_checking(code, "benchmark.py")
if gimple:
    print("✓ Code is type-safe!")
else:
    print("✗ Type safety violations found")
```

## Error Messages Generated

When invariants are violated, the type system generates clear, actionable errors:

### Example 1: TEMPORAL_MONOTONICITY Violation

```
ERROR: TEMPORAL_MONOTONICITY violation
Location: benchmark.py:42

Variable 'i' type changed incompatibly:
  Previous type: int64_t(64-bit) [inferred at benchmark.py:40]
  Assigned type: int(32-bit) [inferred at benchmark.py:42]

Type system requires that variables maintain their bit width and structure
once assigned. This prevents silent truncation (int64_t → int) or type confusion.

Possible fixes:
  1. Use explicit cast: i = (int64_t)expression
  2. Use different variable for different type
  3. Ensure all assignments maintain type consistency
```

### Example 2: OPAQUE_POINTER_TRACKING Violation

```
ERROR: OPAQUE_POINTER_TRACKING violation
Location: benchmark.py:100

Argument 0 of advance():
Cannot pass opaque pointer int64_t<opaque->MojoList*> to parameter 
expecting MojoList* (explicit pointer)

Opaque pointers (int64_t used to store pointer values) must be explicitly
converted back to their proper pointer type before use.

Generated code should include:
  _t_temp = (MojoList *)(_t_bodies);
  advance(_t_temp, ...);
```

### Example 3: BIT_WIDTH_PRESERVATION Violation

```
ERROR: BIT_WIDTH_PRESERVATION violation
Location: benchmark.py:55

Cannot perform + on mismatched bit widths:
  Left:  int64_t(64-bit)
  Right: int(32-bit)

In Mojo's ABI, integers are 64-bit (int64_t) and should maintain that width.
Mixing 32-bit and 64-bit operands requires explicit casting.

Fix: result = (int64_t)x + (int64_t)y
```

## Type Information Flow

```
SOURCE:  def foo(items: List[int]):
               items[0] = 42

PARSE:   FunctionDef(
           name='foo',
           params=[Param(name='items', type_ann='List[int]')],
           body=[AssignStmt(...)]
         )

TYPE INFERENCE:
  1. Annotated type: List[int]
  2. Inferred: items → Type(
       base='MojoList',
       is_pointer=True,
       element_type=Type(base='int64_t', bit_width=64),
       origin=ANNOTATED
     )

CODE GEN:
  - Generate: mojo_list_get_int(items, 0) // Picked based on element type
  - Assign to temp with type int64_t
  - Check: assigning int64_t to parameter expecting int64_t ✓

RUNTIME:
  - No type information needed
  - Just call mojo_list_get_int
  - No overhead
```

## Configuration

```python
# In gimple_codegen.py __init__:
self.type_checker = InvariantChecker(
    verbose=os.environ.get('MOJO_TYPE_VERBOSE', False),
)

# Enable/disable individual invariants:
self.check_temporal_monotonicity = True
self.check_bit_width_preservation = True
self.check_opaque_pointer_tracking = True
self.check_element_type_preservation = True
self.check_inference_idempotence = True
```

## Benefits of Integration

| Stage | Without Type System | With Type System |
|-------|---|---|
| Development | Subtle bugs slip through | Caught at compile time |
| Debugging | Runtime crashes, hard to trace | Clear error messages |
| Code Review | Must manually verify types | Type checker enforces invariants |
| Performance | Types persist at runtime | Types erased, zero overhead |
| Confidence | Medium - runtime surprises | High - verification at compile |

## Next Steps

1. **Phase 1 (Now)**: Type system implementation ✓
2. **Phase 2 (Next)**: Integrate into gimple_codegen.py
   - Add `type_checker` field
   - Hook into Phase 1 type inference
   - Hook into Phase 2a code generation
3. **Phase 3**: Enable by default in CI
4. **Phase 4**: Improve error messages based on feedback
5. **Phase 5**: Extend to cover more invariants if needed

## Testing Verification

All 14 unit tests pass, verifying that the type system catches:
- ✓ Variable type truncation
- ✓ Bit width mismatches
- ✓ Opaque pointer passing
- ✓ Missing element types
- ✓ Type inference conflicts
- ✓ All 5 real bugs from this session

The type system is **ready for integration** into the compilation pipeline.
