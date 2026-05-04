# Mojo Manual — Pointers

Source: https://docs.modular.com/mojo/manual/pointers/
        https://docs.modular.com/mojo/manual/pointers/unsafe-pointers/

---

## Intro to Pointers

Source: https://docs.modular.com/mojo/manual/pointers/

A pointer is an indirect reference to values in memory. Mojo provides several pointer types with different safety and ownership characteristics.

### Pointer Types Comparison

| Feature | `Pointer` | `OwnedPointer` | `ArcPointer` | `UnsafePointer` |
|---------|-----------|----------------|--------------|-----------------|
| Safe | Yes | Yes | Yes | No |
| Allocates memory | No | Implicitly | Implicitly | Explicitly |
| Owns pointee(s) | No | Yes | Yes | No |
| Copyable | Yes | Explicitly | Yes | Yes |
| Nullable | No | No | No | No |
| Uninitialized memory | No | No | No | Yes |
| Multiple values | No | No | No | Yes |

### Dereferencing

```mojo
ptr[] += 10
print(ptr[])
```

### `Pointer`

Safe, non-owning reference. Use for storing references, passing memory locations to external code, returning long-lived references.

```mojo
from std.memory import Pointer

ptr = Pointer(to=some_value)
```

Carries an origin for the stored value, enabling lifetime tracking.

### `OwnedPointer`

Smart pointer for single-ownership. Allocates memory and moves/copies values in.

```mojo
from std.memory import OwnedPointer

o_ptr = OwnedPointer(some_big_struct)
```

- Can be moved but not copied (enforces single ownership)
- Stored item must be `Movable` or `Copyable`
- **Cannot** create `Optional[OwnedPointer[T]]` (use `ArcPointer` instead)

### `ArcPointer`

Reference-counted smart pointer for shared ownership.

```mojo
from std.memory import ArcPointer

attributes = ArcPointer(attributesDict)
```

- Freely copyable; all instances share a reference count
- Reference count decremented on destruction; value freed when count reaches zero
- Uses `Atomic` for thread-safe reference counting
- Useful for safe reference-semantic types:

```mojo
struct SharedDict(Copyable):
    var attributes: ArcPointer[Dict[String, String]]

    def __init__(out self):
        attributesDict: Dict[String, String] = {}
        self.attributes = ArcPointer(attributesDict)

    def __init__(out self, *, copy: Self):
        self.attributes = copy.attributes

    def __setitem__(mut self, key: String, value: String):
        self.attributes[][key] = value

    def __getitem__(self, key: String) -> String:
        return self.attributes[].get(key, default="")

def main():
    thing1 = SharedDict()
    thing2 = thing1
    thing1["Flip"] = "Flop"
    print(thing2["Flip"])  # "Flop" — shared reference
```

### `UnsafePointer`

Low-level pointer to contiguous memory (possibly uninitialized). See next section.

---

## Unsafe Pointers

Source: https://docs.modular.com/mojo/manual/pointers/unsafe-pointers/

`UnsafePointer` is analogous to C/C++ raw pointers. You are responsible for correct memory management.

### Basic Usage

```mojo
var ptr = alloc[Int](1)
ptr.init_pointee_copy(100)
ptr[] += 10
print(ptr[])   # 110
```

### Pointer Lifecycle States

1. **Uninitialized**: declared but not assigned
2. **Pointing to allocated memory**: created via `alloc()`, contents uninitialized
3. **Pointing to initialized memory**: valid data accessible via dereference
4. **Dangling**: memory freed; dereferencing causes undefined behavior

### Memory Operations

```mojo
var ptr = alloc[Int](count)             # allocate
ptr.init_pointee_copy(value)            # initialize with copy
ptr.init_pointee_move(value^)           # initialize with move
var p2 = UnsafePointer(to=existing)     # reference existing value
var v = ptr[]                           # dereference
var v = ptr[index]                      # subscript
ptr.destroy_pointee()                   # call destructor
var v = ptr.take_pointee()              # consuming move
ptr.free()                              # deallocate memory
```

### Pointer Arithmetic

```mojo
var third_ptr = first_ptr + 2
ptr += 1
```

### Origins Tracking

The `origin` parameter tracks memory provenance:
- Pointers from `alloc()` have `MutExternalOrigin`
- Pointers from `UnsafePointer(to=value)` inherit the pointee's origin

### Nullability

`UnsafePointer` is non-nullable by design. Model null pointers using `Optional[UnsafePointer[T]]`.

### Foreign Pointers

**From raw addresses**:
```mojo
UnsafePointer[Type, MutExternalOrigin](unsafe_from_address=addr)
```

**From Python**:
```mojo
PythonObject.unsafe_get_as_pointer()
```

**From C/C++**: via return type specification in `external_call()`

**Opaque pointers**: `OpaquePointer` (alias for `UnsafePointer[NoneType]`)

### Data Conversion

**Bitcasting** (reinterpret type without relocating):
```mojo
ptr.bitcast[NewType]()
```

**Byte order** (endianness conversion):
```mojo
ptr.byte_swap()
```

### SIMD Operations

```mojo
ptr.load()                          # scalar aligned load
ptr.store(value)                    # scalar aligned store
ptr.strided_load(stride)            # stride-spaced loads
ptr.strided_store(value, stride)    # stride-spaced stores
ptr.gather(offsets)                 # arbitrary memory locations
ptr.scatter(value, offsets)         # arbitrary memory locations
```

`strided_load`/`strided_store` useful for extracting image channels.

### When to Use `UnsafePointer`

- Building high-performance array structures (`List`, `Tensor`)
- Interacting with external libraries (C++, Python)
- When all safe pointer types are insufficient

### Safety Considerations

- Manual memory management required
- No guarantee of initialized memory before dereference
- No bounds checking on pointer arithmetic
- You must prevent memory leaks and use-after-free

Prefer safe pointer types; reserve `UnsafePointer` for low-level access and foreign language interoperability.
