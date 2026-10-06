# Type System: Support for Multiple Integer Widths

## Problem Statement

The current audit focuses on int64_t as the primary integer type, but languages legitimately support smaller integer types:

- Int8 / uint8_t (8-bit)
- Int16 / uint16_t (16-bit)
- Int32 / uint32_t (32-bit)
- Int64 / uint64_t (64-bit)

These types are valid for:
- Loop variables (a Int8 loop is legitimate and efficient)
- Struct fields (packing smaller fields)
- Function parameters (matching external ABIs)
- Arithmetic operations (operations respecting type widths)

## Current Limitations

The audit assumes int64_t is the "correct" type everywhere, but this is too restrictive.

**Problem Areas in Audit**:

1. **For-loop assumption**: "Loop variables should be int64_t"
   - Actually: Loop variables should match iterable type or explicit annotation
   - Int8 loop is legitimate: `for i: Int8 in range(100):`

2. **Type coercion rules**: "32-bit to 64-bit widening is OK"
   - Actually: Operations should respect declared types
   - 32-bit op should produce 32-bit result (not widened to 64-bit)

3. **Binary operations**: "All arithmetic → int64_t"
   - Actually: Operations should preserve bit width
   - Int8 + Int8 → Int8, not Int8 + Int8 → Int64

## Refined Type System for Multiple Integer Widths

### BIT_WIDTH_PRESERVATION (Refined)

Operations must preserve the declared bit width of the operands:

```
Rule 1: Homogeneous operations
  - T op T → T (operation respects type)
  - int64_t + int64_t → int64_t
  - int8_t + int8_t → int8_t ✓
  
Rule 2: Mixed-width operations require explicit cast
  - int64_t + int8_t → ERROR (implicit widening)
  - Must write: int64_t + (int64_t)int8_t
  
Rule 3: Widening is explicit
  - int8_t → int64_t requires explicit cast
  - Cannot silently widen in assignment
```

### Type System Rules for Multiple Integer Widths

```python
class BIT_WIDTH_PRESERVATION:
    """Operations must respect declared bit widths."""
    
    def check_arithmetic(left_type, op, right_type):
        # Rule 1: Same type, same width result
        if left_type.base == right_type.base:
            return left_type  # int8_t + int8_t → int8_t ✓
        
        # Rule 2: Different types
        if left_type.bit_width != right_type.bit_width:
            raise TypeSystemError(
                f"Cannot perform {op} on {left_type} and {right_type}. "
                f"Bit widths must match or be explicitly cast."
            )
        
        # Rule 3: Same width, different signedness → result type
        if left_type.is_signed == right_type.is_signed:
            return join(left_type, right_type)
        else:
            raise TypeSystemError(
                f"Cannot mix signed {left_type} with unsigned {right_type}. "
                f"Signedness mismatch requires explicit cast."
            )
```

### Examples of Correct Type Usage

```mojo
# Loop with explicit small type
for i: Int8 in range(100):      # i is int8_t throughout loop
    x = i * 2                   # int8_t * int8_t → int8_t
    
# Mixed sizes require explicit cast
big: Int64 = 1000
small: Int8 = (Int8)20
result = big + (Int64)small    # Explicit cast required

# Assignment respects declared type
x: Int8 = 5                    # x is declared as int8_t
y: Int8 = x + 10               # 5 + 10 = 15, fits in int8_t ✓
z: Int8 = x + 200              # ERROR: 5 + 200 = 205, overflows int8_t

# Function parameters lock types
def process(data: List[Int32]):
    for i: Int32 in range(len(data)):  # i is int32_t
        data[i] += 1                   # int32_t + 1 → int32_t
```

## Changes to Type System

### 1. Type Class Enhancement

```python
class Type:
    base: str                    # 'int8_t', 'int32_t', 'int64_t', etc.
    bit_width: int              # 8, 16, 32, 64
    is_signed: bool             # Distinguish signed vs unsigned
    
    # New method: can values of self_type be assigned to target_type?
    def is_assignable_to(self, target_type: 'Type') -> bool:
        if self == target_type:
            return True
        # Explicit widening is allowed with cast
        if self.is_signed == target_type.is_signed:
            if self.bit_width <= target_type.bit_width:
                return True  # Widening allowed
        return False
```

### 2. BIT_WIDTH_PRESERVATION Refinement

```python
def check_bit_width_preservation(left, op, right) -> Type:
    # Homogeneous operations preserve type
    if left.bit_width == right.bit_width:
        return left
    
    # Heterogeneous operations need explicit casts
    raise TypeSystemError(
        f"Cannot perform {op} on {left.bit_width}-bit and "
        f"{right.bit_width}-bit operands without explicit cast"
    )
```

### 3. Loop Variable Type Handling

```python
def check_for_loop(loop_var_name, iterable_type):
    # Loop variable can be:
    # 1. Explicitly annotated: for i: Int8 in ...
    # 2. Inferred from iterable: for x in iter_of_int32
    
    if loop_var_type_annotation:
        # Use declared type
        loop_var_type = loop_var_type_annotation
    else:
        # Infer from iterable
        loop_var_type = iterable.element_type
    
    # Lock type for TEMPORAL_MONOTONICITY
    lock_type(loop_var_name, loop_var_type)
```

## Audit Corrections

### For-loop variables (CORRECTED)

**Old**: "Loop variables should be int64_t"
**New**: "Loop variable type should match iterable element type or annotation"

```
✗ for i in range(100):           # i inferred as int64_t (could be wrong)
✓ for i in range(100):           # i inferred from iterable type
✓ for i: Int8 in range(100):     # i explicitly int8_t
✓ for x in list_of_int32:        # x inferred as int32_t
```

### Arithmetic operations (CORRECTED)

**Old**: "64-bit operations cannot produce 32-bit results"
**New**: "Operations must preserve the declared bit width of operands"

```
✓ int64_t + int64_t → int64_t
✓ int32_t + int32_t → int32_t
✓ int8_t + int8_t → int8_t
✗ int64_t + int32_t → ERROR (need explicit cast)
✗ int32_t + int32_t → int64_t (wrong: must be int32_t)
```

## Implementation Strategy

### Phase 1: Audit
- [x] Identify all places where type width is checked
- [x] Verify assumptions about which types are valid
- [ ] Document supported integer types (Int8, Int16, Int32, Int64)

### Phase 2: Update Type System
- [ ] Enhance Type class to track all integer widths
- [ ] Update BIT_WIDTH_PRESERVATION to handle all widths
- [ ] Add signedness tracking (signed vs unsigned)

### Phase 3: Update Code Generation
- [ ] For loops: respect annotated loop variable types
- [ ] Arithmetic: verify operand widths match
- [ ] Assignments: check declared types

### Phase 4: Testing
- [ ] Test with Int8, Int16, Int32, Int64 types
- [ ] Test mixed-width error cases
- [ ] Test overflow detection where applicable

## Impact on Type System

The corrected understanding of bit widths makes the type system **more flexible** while still **maintaining invariants**:

✅ Allows legitimate use of small types (Int8 for packed data)
✅ Prevents silent widening/narrowing of types
✅ Respects programmer's type declarations
✅ Catches overflow and type mismatches

The key insight: **BIT_WIDTH_PRESERVATION doesn't mean "everything is 64-bit"**. It means **"operations respect declared bit widths"**.

## Next Steps

1. Review how Mojo actually handles Int8, Int16, Int32 types
2. Update type system to support all integer widths properly
3. Audit for-loop handling to respect loop variable type annotations
4. Update audit document with correct assumptions
