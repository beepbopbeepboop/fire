# GIMPLE Memory and Pointer Specification

Specification for lowering Mojo pointer types and unsafe memory operations to GIMPLE.

Source: Extracted from gimple_codegen.py pointer lowering (lines 1100-1155) and subscript operations (lines 1291-1334).

---

## Overview

Mojo provides several pointer types that lower to raw C pointers in GIMPLE:

- **`UnsafePointer[T]`** → `T *` (raw C pointer, untracked)
- **`Pointer[T]`** → `T *` (safe pointer, no lifetime checking in GIMPLE)
- **`ArcPointer[T]`** → `T *` (atomic reference counting, simplified to raw pointer)
- **`OwnedPointer[T]`** → `T *` (owned pointer, manual cleanup)

All lower to raw `T *` in C. Type safety and lifetime tracking are compile-time Mojo features, not runtime semantics in GIMPLE.

---

## Pointer Type Resolution

### Mojo Type → C Type Mapping

```python
def _resolve_type(mojo_type: str) -> str:
    # Pointer types
    if mojo_type.startswith('UnsafePointer['):
        inner = extract_inner_type(mojo_type)  # e.g., "Int"
        return _resolve_type(inner) + ' *'
    if mojo_type.startswith('Pointer['):
        # Same as UnsafePointer for GIMPLE
        inner = extract_inner_type(mojo_type)
        return _resolve_type(inner) + ' *'
    if mojo_type.startswith('ArcPointer['):
        inner = extract_inner_type(mojo_type)
        return _resolve_type(inner) + ' *'
    if mojo_type.startswith('OwnedPointer['):
        inner = extract_inner_type(mojo_type)
        return _resolve_type(inner) + ' *'
```

### Examples

| Mojo Type | C Type |
|-----------|--------|
| `UnsafePointer[Int]` | `int *` |
| `UnsafePointer[Float64]` | `double *` |
| `Pointer[MyStruct]` | `MyStruct *` |
| `ArcPointer[List]` | `MojoList * *` |
| `OnsafePointer[Int64]` | `int64_t *` |

---

## Pointer Arithmetic

### Constraint: No Pointer Arithmetic in __GIMPLE

GIMPLE forbids pointer arithmetic:
```c
// ❌ Invalid in GIMPLE
int *p = ...;
int *q = p + 10;  // Error: arithmetic not allowed
```

### Solution: _mojo_at_ Helper Functions

For each pointer element type, generate a helper function that performs pointer arithmetic:

```c
// ✅ Valid: use helper function
int *q = _mojo_at_int(p, 10);
```

### Helper Function Generation

For element type `T`, generate:

```c
static inline T * _mojo_at_T (T * p, int64_t n) {
    return p + n;
}
```

**Examples**:
```c
static inline int * _mojo_at_int (int * p, int64_t n) {
    return p + n;
}

static inline double * _mojo_at_double (double * p, int64_t n) {
    return p + n;
}

static inline int64_t * _mojo_at_int64_t (int64_t * p, int64_t n) {
    return p + n;
}
```

**Generated**: One helper per unique element type used with pointer subscripting.

---

## Pointer Operations (Method Calls)

Pointers support operations via method syntax:

```mojo
ptr.load()           # Dereference pointer
ptr.store(value)     # Store to pointer
ptr.offset(n)        # Pointer arithmetic
ptr.free()           # Free heap memory
ptr.bitcast[T]()     # Type cast (unsupported)
ptr.strided_load()   # Vector load (unsupported)
ptr.strided_store()  # Vector store (unsupported)
ptr.gather()         # Gather from offsets (unsupported)
ptr.scatter()        # Scatter to offsets (unsupported)
ptr.destroy_pointee()    # Call destructor (unsupported)
ptr.take_pointee()       # Move value out (unsupported)
ptr.initialize_pointee() # Initialize to value (unsupported)
ptr.address_of()     # Take address (unsupported)
```

### Implemented Operations

#### `ptr.load() → T`

Dereference pointer to get value.

```mojo
ptr: UnsafePointer[Int] = ...
value = ptr.load()
```

**Generates**:
```c
int *_ptr = ...;
int _value = *_ptr;
```

#### `ptr.store(value) → void`

Write value through pointer.

```mojo
ptr.store(42)
```

**Generates**:
```c
*_ptr = (int)42;
```

#### `ptr.offset(n) → UnsafePointer[T]`

Compute pointer to nth element ahead.

```mojo
ptr: UnsafePointer[Int] = ...
ptr_10 = ptr.offset(10)
```

**Generates** (using `_mojo_at_` helper):
```c
int *_ptr_10 = _mojo_at_int(_ptr, (int64_t)10);
```

#### `ptr.free() → void`

Free heap-allocated memory.

```mojo
ptr.free()
```

**Generates**:
```c
free(_ptr);
```

### Unimplemented Operations (Stubs)

Following operations are complex/unsupported in GIMPLE; stubs emit comments:

- `bitcast[T]()` — Type casting between pointer types
- `strided_load(stride)` — SIMD-like load with stride
- `strided_store(v, stride)` — SIMD-like store with stride
- `gather(offsets)` — Load from multiple offsets
- `scatter(v, offsets)` — Store to multiple offsets
- `destroy_pointee()` — Call destructor on pointed value
- `take_pointee()` — Move value out (consume)
- `initialize_pointee(value)` — Partially implemented; only stores value
- `address_of()` — Take address of value (partially implemented; returns pointer as-is)

**Example stub**:
```c
int _t = 0;  /* TODO: bitcast */
```

---

## Pointer Subscripting

### Syntax

```mojo
ptr: UnsafePointer[Int] = ...
value = ptr[i]
```

### GIMPLE Lowering

Pointer subscript `ptr[i]` is lowered using `_mojo_at_` helper + dereference:

```c
int *_addr = _mojo_at_int(_ptr, (int64_t)_i);
int _value = *_addr;
```

**Steps**:
1. Determine element type `T` from pointer type `T *`
2. Generate C identifier for element type (e.g., `int` → `int`)
3. Mark type as needing `_mojo_at_` helper
4. Cast index to `int64_t`
5. Call `_mojo_at_T` helper with pointer and index
6. Dereference result with `*`

### Equivalent Semantics

```
ptr[i]  ≡  *_mojo_at_T(ptr, i)  ≡  *(ptr + i)
```

---

## Unsafe Pointer Lifting

### Converting Values to Pointers

```mojo
x: Int = 42
ptr: UnsafePointer[Int] = address_of(x)
value = ptr.load()
```

**Note**: `address_of()` in GIMPLE is simplified; returns pointer to value as-is. Safe pointer analysis (lifetime, origin tracking) is not represented.

### Allocating Heap Memory

```mojo
fn alloc[T](count: Int) -> UnsafePointer[T]:
    # Returns pointer to heap-allocated array
```

**Generates** (simplified):
```c
// alloc[Int](10)
void *_vp = malloc(10 * sizeof(int));
int *_ptr = (int *)_vp;
```

**Simplified in GIMPLE**: No bounds tracking or GC integration. Caller responsible for deallocation.

---

## Pointer Types in Structs

### Struct with Pointer Field

```mojo
struct Buffer:
    data: UnsafePointer[Int]
    len: Int
```

**Generates**:
```c
typedef struct {
    int *data;
    int len;
} Buffer;
```

### Field Access through Pointer

```mojo
buf: Buffer * = ...
value = buf.data[i]
```

**Generates**:
```c
int _value = buf->data[i];  // Direct subscript (C semantics)
```

---

## Origin Tracking (Not in GIMPLE)

### Mojo Origin System

Mojo has a sophisticated origin tracking system to ensure safe pointer usage:

```mojo
fn process[T](origin: Origin) -> T:
    ptr: UnsafePointer[T] where origin::T
```

**In GIMPLE**: Origins are dropped entirely. No runtime checking of pointer validity or lifetime.

### Implications

1. **No lifetime verification**: Pointer to stack variable valid indefinitely in GIMPLE
2. **Use-after-free undetected**: Freeing memory then accessing is allowed in GIMPLE
3. **Dangling pointers unchecked**: No runtime origin validation

**Design choice**: GIMPLE is low-level C. Pointer safety is checked at Mojo compile-time, not enforced at runtime.

---

## Pointer Helpers Tracking

### Dynamic Helper Generation

During codegen, pointers helper functions are tracked:

```python
self._ptr_helpers_needed: set[str] = set()  # element C types needing _mojo_at_
```

Whenever a pointer subscript or `.offset()` is encountered:

1. Extract element type `T`
2. Add `T` to `_ptr_helpers_needed`

### Preamble Generation

Before function definitions, emit all needed helpers:

```c
// If int and double pointers used:
static inline int * _mojo_at_int (int * p, int64_t n) {
    return p + n;
}

static inline double * _mojo_at_double (double * p, int64_t n) {
    return p + n;
}
```

### Deduplication

Helpers are generated once per unique element type, even if used in multiple functions.

---

## Memory Allocation Helpers

### Struct Allocation

For user-defined structs `StructName`, generate allocator helper:

```c
StructName * __GIMPLE _alloc_StructName (void)
{
  StructName *_p;
  void *_vp;

bb_2:
  _vp = malloc(sizeof(StructName));
  _p = (StructName *)_vp;
  return _p;
}
```

**Usage** (in gimple_codegen.py):
```python
# When struct field is initialized
t = self._new_temp('MyStruct *')
self._emit(f"  {t} = _alloc_MyStruct();")
```

**Generated on-demand**: One allocator per struct type that needs heap allocation.

---

## Limitations and Future Work

### Current Implementation

1. **No garbage collection**: Manual memory management only
2. **No reference counting**: ArcPointer simplified to raw pointer
3. **No pointer validity checking**: Use-after-free not detected
4. **No SIMD operations**: strided_load/gather/scatter are stubs
5. **No bitcasting**: bitcast[T]() is stub
6. **No destructor calls**: destroy_pointee() not called

### Future Enhancements

1. **Reference counting**: Track allocations with atomic counters
   ```c
   struct RefCounted {
       void *data;
       int *refcount;
   };
   ```

2. **RAII-style cleanup**: Automatic free() on scope exit
   ```c
   // Implicit cleanup when variable goes out of scope
   free(_ptr);
   ```

3. **Bounds tracking**: Store allocation size, check subscript bounds
   ```c
   struct BoundedPtr {
       T *data;
       int64_t len;
   };
   ```

4. **SIMD operations**: Actual strided load/store for vector types

5. **Type-safe bitcasting**: Preserve type information for runtime dispatch

---

## Integration with GIMPLE Codegen

### Pointer Detection

When lowering expressions, detect pointer types:

```python
if ot.endswith(' *') and ot not in self._RUNTIME_PTRS:
    # Handle as raw C pointer (UnsafePointer-like)
    # _RUNTIME_PTRS contains MojoList *, MojoDict *, etc.
```

### Method Dispatch

For pointer method calls:

```python
if method == 'load':
    return elem, f"*{ov}"
elif method == 'store':
    emit(f"*{ov} = {value};")
elif method == 'offset':
    self._ptr_helpers_needed.add(elem)
    return pointer_type, f"_mojo_at_{c_id(elem)}({ov}, {idx})"
```

### Subscript Handling

For pointer subscripts:

```python
if ot.endswith(' *'):  # It's a pointer
    elem = _elem_type(ot)
    self._ptr_helpers_needed.add(elem)
    addr = f"_mojo_at_{c_id(elem)}({ov}, {idx})"
    return elem, f"*{addr}"
```

---

## Safety Notes

### Unsafe Semantics

GIMPLE pointer operations have no safety guarantees:

- **No bounds checking**: Subscript out of bounds is undefined behavior
- **No type safety**: Can cast any pointer to any type via bitcast
- **No aliasing safety**: Concurrent writes through different pointers are allowed
- **No lifetime safety**: Pointers to stack variables remain valid

### Safe Mojo → Unsafe GIMPLE

Mojo's type system enforces safe pointer usage. Unsafe code is marked with `unsafe` blocks:

```mojo
unsafe {
    ptr = address_of(x)
    value = ptr.load()
}
```

GIMPLE receives already-validated code. The C output is low-level and trusts the programmer.

---

**Specification Date**: 2026-04-28  
**Status**: Complete memory and pointer specification for GIMPLE lowering  
**Integration**: Referenced by gimple_codegen.py for pointer operations and memory management
