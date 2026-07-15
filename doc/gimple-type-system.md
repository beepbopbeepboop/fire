# GIMPLE Type System Specification

Specification for type resolution, type lattice, and type promotion rules in GIMPLE code generation.

Source: Extracted from gimple_codegen.py TypeLattice implementation and GNU-EXTENSIONS.md Type Resolution section.

---

## Type Categories

### Numeric Types

#### Signed Integers
- `int8_t` — 8-bit signed integer, rank 1
- `int16_t` — 16-bit signed integer, rank 2
- `int32_t` — 32-bit signed integer, rank 3
- `int` — 32-bit signed integer (C default), rank 3
- `int64_t` — 64-bit signed integer, rank 4

#### Unsigned Integers
- `uint8_t` — 8-bit unsigned integer, rank 1
- `uint16_t` — 16-bit unsigned integer, rank 2
- `uint32_t` — 32-bit unsigned integer, rank 3
- `unsigned int` — 32-bit unsigned integer (C default), rank 3
- `uint64_t` — 64-bit unsigned integer, rank 4

#### Floating Point
- `__fp16` — IEEE 754 half-precision, rank 1
- `float` — IEEE 754 single-precision, rank 2
- `double` — IEEE 754 double-precision, rank 3

### Boolean Type

- `_Bool` — C99 boolean type (1-byte, values 0 or 1)

### Pointer Types

- `T *` — Pointer to type T (any type)
- `const T *` — Const pointer to type T

### Container Types

- `MojoList *` — Dynamic list container
- `MojoDict *` — Hash map container
- `MojoSet *` — Hash set container
- `MojoStr *` — String container

### User-Defined Types

- `StructName *` — Pointer to user-defined struct (heap allocated)

### Unknown/Default Type

- `int` — Default type when inference fails

---

## Mojo-to-C Type Mapping

Complete mapping of Mojo types to C types for code generation.

### Mojo Integral Types → C Types

| Mojo Type | C Type | Rank |
|-----------|--------|------|
| Int8 | int8_t | 1 |
| Int16 | int16_t | 2 |
| Int32 | int32_t | 3 |
| Int | int | 3 |
| Int64 | int64_t | 4 |
| UInt8 | uint8_t | 1 |
| UInt16 | uint16_t | 2 |
| UInt32 | uint32_t | 3 |
| UInt | unsigned int | 3 |
| UInt64 | uint64_t | 4 |

### Mojo Floating Point Types → C Types

| Mojo Type | C Type | Rank |
|-----------|--------|------|
| Float16 | __fp16 | 1 |
| Float32 | float | 2 |
| Float | float | 2 |
| Float64 | double | 3 |

### Mojo Other Types → C Types

| Mojo Type | C Type |
|-----------|--------|
| Bool | _Bool |
| String | char * |
| MojoList | MojoList * |
| MojoDict | MojoDict * |
| MojoSet | MojoSet * |
| MojoStr | MojoStr * |

### Mojo Pointer Types → C Types

| Mojo Type | C Type |
|-----------|--------|
| UnsafePointer[T] | T * |
| Pointer[T] | T * |
| ArcPointer[T] | T * |
| OwnedPointer[T] | T * |

---

## Type Lattice and Promotion Rules

The **TypeLattice** implements C11 usual arithmetic conversion rules for determining the result type of binary operations.

### TypeLattice.join(t1, t2) → result_type

**Algorithm**:

1. If `t1 == t2`, return `t1`
2. Apply type promotion rules:
   - `_Bool` promotes to `int` before further analysis
   - Float types dominate integer types
   - Wider types dominate narrower types
   - Unsigned types dominate signed types (if rank >= signed rank)
3. Return promoted type

### Detailed Promotion Rules

#### Rule 1: Boolean Promotion

```
_Bool + any_type  →  int + any_type  (apply remaining rules)
```

**Example**: `_Bool + int32_t` → `int + int32_t` → `int32_t`

#### Rule 2: Float Dominance

```
float_type + int_type  →  float_type
```

Float always wins. Wider float wins.

**Examples**:
- `int + float` → `float`
- `float + double` → `double`
- `float + int64_t` → `float`

#### Rule 3: Integral Type Promotion

When both operands are integral (neither is floating point):

**Same signedness**: Wider type wins
```
int32_t + int64_t  →  int64_t
uint16_t + uint64_t  →  uint64_t
```

**Mixed signedness**: 
```
If unsigned_rank >= signed_rank:
  use unsigned type
Else:
  use signed type
```

**Examples**:
- `uint32_t + int32_t` → `uint32_t` (equal rank, unsigned wins)
- `uint64_t + int32_t` → `uint64_t` (uint rank > int rank)
- `uint16_t + int32_t` → `int32_t` (int rank > uint rank)

#### Rule 4: Pointer Types

```
pointer_type + int_type  →  pointer_type
pointer_type + other_pointer  →  void *
```

Preserve pointer type. For mixed pointers, use `void *`.

### Type Hierarchy

```
_Bool (smallest)
  ↓
int8_t < int16_t < int32_t < int64_t (signed)
uint8_t < uint16_t < uint32_t < uint64_t (unsigned)
  ↓
__fp16 < float < double (largest)
  ↓
T * (any pointer type)
```

---

## Rank System

Used in TypeLattice for determining promotion winners:

### Signed Integer Ranks
```python
_SIGNED = {
  'int8_t': 1,
  'int16_t': 2,
  'int32_t': 3,
  'int': 3,           # Same as int32_t
  'int64_t': 4,
}
```

### Unsigned Integer Ranks
```python
_UNSIGNED = {
  'uint8_t': 1,
  'uint16_t': 2,
  'uint32_t': 3,
  'unsigned int': 3,  # Same as uint32_t
  'uint64_t': 4,
}
```

### Float Ranks
```python
_FLOAT = {
  '__fp16': 1,
  'float': 2,
  'double': 3,
}
```

**Comparison Across Categories**:
- Highest rank in category wins
- Float category > Int category
- Pointer types are treated separately

---

## Type Inference

### Function Return Type Inference

Function return types are inferred when not explicitly annotated:

1. **Annotated functions**: Use declared return type
   ```mojo
   fn add(x: Int, y: Int) -> Int:  # return type is Int
   ```

2. **Unannotated functions**: Infer from return statements
   ```mojo
   fn compute(x: Int):  # no return type annotation
       if x > 0:
           return x + 1      # return type Int
       else:
           return 0          # return type Int
   ```
   - Collect all return statement types
   - Use `TypeLattice.join_all(types)` to find LUB

3. **Special case: main() function**
   - Always returns `int` (even if inferred type is `void`)
   - Implicit `return 0;` added if no explicit return

### Variable Type Inference

Variable types are determined from:

1. **Explicit annotation**:
   ```mojo
   var x: Int = 42        # type is Int
   ```

2. **Assignment RHS**:
   ```mojo
   var x = 42             # type inferred from 42 → Int
   var y = x + 1.5        # type inferred from Int + Double → Double
   ```

3. **Container element types**:
   - First element of list determines element type
   - Key-value pair of dict determines types
   - Set elements determine element type

---

## Type Coercion

Type coercion converts values from one type to another:

### Implicit Coercion (Allowed)

Occurs automatically in binary operations:
```c
int x = 10;
double y = x + 3.14;  // x implicitly coerced to double
```

### Explicit Coercion (Required in GIMPLE)

```c
int x = (int) 3.14;    // Explicit cast required
double y = (double) 10;
```

**GIMPLE Restriction**: Cast cannot appear in:
- Function call arguments
- Comparison operands
- Return statements
- Member access
- Subscript operations

**Workaround**: Use intermediate temp:
```c
// ❌ Invalid in GIMPLE
return (int) sqrt(9.0);

// ✅ Valid in GIMPLE
int _t1 = sqrt(9.0);
return _t1;
```

---

## Type Resolution Algorithm

Used during code generation to map Mojo types to C types:

```python
def _resolve_type(mojo_type: str) -> str:
    """Convert Mojo type annotation to C type for codegen."""

    # Remove whitespace
    t = mojo_type.strip()

    # Direct mapping
    if t in MOJO_TO_C_MAP:
        return MOJO_TO_C_MAP[t]

    # Generic types: MojoList, MojoDict, etc.
    if t.startswith('MojoList'):
        return 'MojoList *'
    if t.startswith('UnsafePointer'):
        return 'int64_t *'

    # User-defined struct: use pointer type
    if is_user_struct(t):
        return f"{t} *"

    # Default: unknown type as int
    return 'int'
```

---

## Type System in Action

### Example 1: Binary Operation Type Promotion

```mojo
var a: Int32 = 10
var b: Int64 = 20
var c: _ = a + b
```

**Type inference for `c`**:
1. Get operand types: `int32_t` and `int64_t`
2. Call `TypeLattice.join('int32_t', 'int64_t')`
3. Both signed, `int64_t` has higher rank
4. Result type: `int64_t`
5. Generated C: `int64_t c = (int64_t)a + b;`

### Example 2: Comparison Result Type

```mojo
var result: Bool = x < y
```

**Type inference**:
1. `<` operator always returns `_Bool`
2. Result type: `_Bool` (not `int`)
3. Generated C: `_Bool result = (x < y);`

### Example 3: Container Element Types

```mojo
var numbers = [1, 2, 3]
var values = [1.5, 2.5, 3.5]
```

**Type inference**:
- First element of `numbers`: `Int` → element type is `int`
- First element of `values`: `Float` → element type is `double`

---

## Implementation: TypeLattice Class

```python
class TypeLattice:
    """C11 usual arithmetic conversion rules for binary operations."""

    # Type rank systems (see Rank System section above)
    _SIGNED = {...}
    _UNSIGNED = {...}
    _FLOAT = {...}

    @classmethod
    def join(cls, t1: str, t2: str) -> str:
        """Compute LUB (least upper bound) of two types."""
        # Implementation per algorithm in Promotion Rules section

    @classmethod
    def join_all(cls, types: list) -> str:
        """Compute LUB of multiple types."""
        # Fold join operation over list of types
```

---

## Future Enhancements

### Generic Type Parameters

Currently not supported. Future work:
- Template type variables: `T where T: Numeric`
- Generic instantiation: `List[Int]` → `ListInt`
- Monomorphization: Specialize generic code for concrete types

### Custom Type Operations

Currently not supported. Future work:
- Operator overloading: `__add__`, `__mul__`, etc.
- Custom type coercion: `__to_int__`, `__to_float__`
- Trait-based numeric: `Numeric` trait for generic constraints

---

**Specification Date**: 2026-04-28  
**Status**: Complete type system specification ready for code generation  
**Integration**: Used by gimple_spec_gen.py to generate type promotion logic
