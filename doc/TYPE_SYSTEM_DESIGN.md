# Comprehensive Type System for Mojo Compiler

## Problem Statement

Recent debugging revealed that type safety violations cause cascading bugs:
- For-loop variables silently truncate from 64→32 bit (BIT_WIDTH_PRESERVATION violation)
- Parameter types don't match signatures (TEMPORAL_MONOTONICITY violation)
- Opaque pointers (int64_t) lose type information (OPAQUE_POINTER_TRACKING violation)
- Element types don't propagate through subscripts (ELEMENT_TYPE_PRESERVATION violation)
- Type inference depends on operation order (INFERENCE_IDEMPOTENCE violation)

## Type System Architecture

### Core Type Representation

```python
@dataclass
class Type:
    """Complete type information for values"""
    base: str                          # 'int64_t', 'double', 'MojoList', etc.
    
    # Bit width tracking
    bit_width: int | None              # 32, 64, None for non-numeric
    
    # Pointer semantics
    is_pointer: bool                   # Is this a pointer value?
    pointer_to: 'Type' | None          # What does it point to?
    is_opaque_pointer: bool            # Is it stored as int64_t?
    
    # For numeric types
    is_signed: bool                    # Matters for overflow/comparison
    
    # For containers
    element_type: 'Type' | None        # What's in the container?
    nested_element_type: 'Type' | None # For lists of lists
    
    # Type origin (for error messages)
    origin: str                        # 'inferred', 'annotated', 'literal', 'cast'
    origin_loc: tuple[str, int]        # (file, line)
```

### Type Invariants (Must Hold At All Points)

#### 1. TEMPORAL_MONOTONICITY
Once a variable is assigned a type, it cannot silently change to a different type later.

**Bug it would catch:**
```python
# VIOLATION: x starts as int64_t, becomes int implicitly
x = 1000000000  # int64_t (large value)
x = i * i       # BUG: i is int64_t, but x declared/inferred as int
                # Should emit error: can't assign int64_t to int variable
```

**Implementation:**
```python
class TypeChecker:
    def check_assignment(self, var_name, assignment_type, current_type):
        if current_type and not self._is_subtype(assignment_type, current_type):
            raise TypeError(f"""
                Variable '{var_name}' has type {current_type}
                but being assigned {assignment_type}
                This violates TEMPORAL_MONOTONICITY
            """)
```

#### 2. BIT_WIDTH_PRESERVATION
A 64-bit operation cannot produce a 32-bit result; 32-bit operations cannot receive 64-bit inputs without explicit casting.

**Bug it would catch:**
```python
# VIOLATION: i is int64_t loop variable, should stay int64_t
for i in range(n):  # i: int64_t (from range())
    i = i * i       # BUG: Result of multiplication might be 32-bit somehow
                    # Should verify: int64_t * int64_t → int64_t
```

**Implementation:**
```python
class TypeChecker:
    def check_binary_op(self, left_type, op, right_type):
        # Check bit widths are compatible
        if left_type.bit_width == 64 and right_type.bit_width == 32:
            raise TypeError(f"""
                Cannot perform {op} on mismatched bit widths:
                {left_type.bit_width}-bit {left_type.base} {op} {right_type.bit_width}-bit {right_type.base}
                Violation of BIT_WIDTH_PRESERVATION
            """)
        
        # Verify result bit width
        result_width = self._infer_result_width(left_type, op, right_type)
        return Type(base='int64_t', bit_width=result_width, ...)
```

#### 3. OPAQUE_POINTER_TRACKING
When int64_t is used to store a pointer, this must be:
1. Explicitly tagged in the type system
2. Converted back to pointer type before use
3. Never used as a numeric value

**Bug it would catch:**
```python
# VIOLATION: Passing int64_t opaque pointer without explicit cast
def foo(bodies: MojoList):
    pass

bodies = [[1.0]]  # Type: MojoList*
foo(bodies)       # BUG: bodies is int64_t (opaque storage)
                  # but foo expects MojoList*
                  # Should emit: "Cannot pass int64_t opaque pointer to MojoList* parameter without cast"
```

**Implementation:**
```python
class TypeChecker:
    def check_call_argument(self, arg_type, param_type, arg_index):
        # If argument is opaque pointer and parameter is not, require explicit cast
        if arg_type.is_opaque_pointer and not param_type.is_opaque_pointer:
            raise TypeError(f"""
                Argument {arg_index}: Cannot pass opaque pointer type {arg_type.base}
                to parameter expecting {param_type.base}
                Violation of OPAQUE_POINTER_TRACKING
                
                Hint: Cast explicitly with ({param_type.base})(int64_t){arg_value}
            """)
```

#### 4. ELEMENT_TYPE_PRESERVATION
When accessing container elements, the type information must flow through all operations.

**Bug it would catch:**
```python
# VIOLATION: Element type lost in nested access
arr = [[1.0, 2.0], [3.0, 4.0]]  # Type: MojoList<MojoList<double>>
first_list = arr[0]               # Should have type: MojoList<double>
                                  # BUG: Currently inferred as just int64_t
value = first_list[0]             # Should have type: double
                                  # BUG: Loses the double type info
```

**Implementation:**
```python
class TypeChecker:
    def check_subscript(self, container_type, index):
        if not container_type.element_type:
            raise TypeError(f"""
                Cannot subscript {container_type.base}
                Element type information is missing
                Violation of ELEMENT_TYPE_PRESERVATION
            """)
        return container_type.element_type
```

#### 5. INFERENCE_IDEMPOTENCE
Type inference results must not depend on the order of operations or forward references.

**Bug it would catch:**
```python
# VIOLATION: Parameter type inference depends on forward reference
def foo(bodies):
    # At this point, bodies type must be determined
    # Should not change based on later code
    bodies[0][0] = 1.0

bodies = [[1.0, 2.0]]
foo(bodies)  # If foo's parameter type wasn't inferred before this point, it's too late
```

**Implementation:**
```python
class TypeChecker:
    def infer_function_params(self, func_def):
        # Must complete BEFORE any code generation
        # Cannot be re-inferred later
        inferred = self._infer_from_body(func_def.body)
        
        # Lock it in place
        self._locked_param_types[func_def.name] = inferred
        
        # Any later inference attempt must match
        def later_inference(new_inferred):
            if new_inferred != self._locked_param_types[func_def.name]:
                raise TypeError(f"""
                    Parameter type inference result changed!
                    Original: {self._locked_param_types[func_def.name]}
                    New: {new_inferred}
                    Violation of INFERENCE_IDEMPOTENCE
                """)
```

### Checking Points in Compilation Pipeline

#### Phase 0: Parse → Type Skeleton
- Collect all function signatures
- Record explicit type annotations
- Initialize parameter types as "unknown"

#### Phase 1: Pre-passes
- **1.1**: Infer return types (INFERENCE_IDEMPOTENCE)
- **1.2**: Infer parameter types from usage (INFERENCE_IDEMPOTENCE) - MUST complete here
- **1.3**: Infer local variable types (TEMPORAL_MONOTONICITY)
- **1.3b**: Verify type consistency of all assignments
- **1.3c**: Check element type propagation (ELEMENT_TYPE_PRESERVATION)

#### Phase 2a: Code Generation
- Verify all function calls match inferred signatures
- Check opaque pointer handling (OPAQUE_POINTER_TRACKING)
- Verify bit width preservation (BIT_WIDTH_PRESERVATION)
- Generate explicit casts where needed

#### Phase 2b: Assembly
- Final consistency check

### Error Messages That Would Prevent All Recent Bugs

#### Bug: For-loop variable truncation
```
ERROR at line 42: Variable 'i' type mismatch
  Assignment: i = i * i
  Left side: i has type int64_t (64-bit)
  Right side: i * i produces type int64_t (64-bit)
  Result assigned to: i (type int64_t)
  ✓ OK: Bit widths compatible
  
  But earlier analysis found:
  Loop variable i should be int64_t (from range(n))
  Actual: inferred as int (32-bit)
  VIOLATION: BIT_WIDTH_PRESERVATION
  
  Hint: Loop variables from range() are 64-bit; ensure loop body
        doesn't reassign to 32-bit type
```

#### Bug: Parameter type mismatch at call site
```
ERROR at line 115: Argument/Parameter type mismatch
  Call: advance(bodies, 0.01)
  Argument 0: bodies (type int64_t opaque-pointer-to-MojoList)
  Parameter 0: expects MojoList* (pointer type)
  
  VIOLATION: OPAQUE_POINTER_TRACKING
  Opaque pointer int64_t cannot be passed to pointer parameter
  
  Fix: Emit explicit cast at call site
  
  Generation code:
    _t_temp = (MojoList *)(_t_bodies);
    advance(_t_temp, 0.01);
```

#### Bug: Float conversion from int64_t
```
ERROR at line 78: Cannot convert type
  Expression: float(i)
  Argument type: i is int64_t (64-bit integer)
  Function float() expects:
    - float() → double (default)
    - float(string) → double (parse string)
    - float(int) → double (numeric conversion)
    - float(double) → double (identity)
  
  VIOLATION: Type mismatch in function call
  
  Generated code should use:
    (double)i        // Direct numeric cast
  NOT:
    mojo_make_float((char*)i)  // String parsing (WRONG!)
```

### Implementation Strategy

1. **Phase 1: Type Representation** (~1 day)
   - Create `Type` dataclass
   - Build type inference engine that produces `Type` objects
   - Replace string type names with `Type` objects

2. **Phase 2: Invariant Checking** (~2 days)
   - Implement TEMPORAL_MONOTONICITY checking
   - Implement BIT_WIDTH_PRESERVATION checking
   - Implement ELEMENT_TYPE_PRESERVATION checking
   - Add detailed error messages

3. **Phase 3: Opaque Pointer Handling** (~1 day)
   - Tag opaque pointers in type system
   - Generate automatic casts
   - Implement OPAQUE_POINTER_TRACKING checking

4. **Phase 4: Inference Locking** (~1 day)
   - Lock parameter/return types after Phase 1.2
   - Add INFERENCE_IDEMPOTENCE checking
   - Ensure consistency across all phases

5. **Phase 5: Testing** (~2-3 days)
   - Create test cases for each invariant
   - Verify all previous bugs are caught
   - Check error message clarity

## Benefits

| Bug Category | Current Detection | With Type System |
|---|---|---|
| Bit width truncation | Runtime crash/wrong answer | Compile-time error ✓ |
| Type inference order | Silent corruption | Compile-time error ✓ |
| Parameter mismatch | Compilation error | Better error message ✓ |
| Opaque pointer abuse | Runtime crash | Compile-time error ✓ |
| Element type loss | Wrong function call | Compile-time error ✓ |
| Float conversion bug | Segfault | Compile-time error ✓ |

## Conclusion

A more rigorous type system built on these five invariants would have prevented every bug we've spent this session fixing. The investment in type system infrastructure pays dividends in code quality and debugging time saved.
