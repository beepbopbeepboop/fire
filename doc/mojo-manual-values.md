# Mojo Manual — Value Semantics, Ownership, Lifetimes, and Lifecycle

Source: https://docs.modular.com/mojo/manual/values/
        https://docs.modular.com/mojo/manual/lifecycle/

---

## Value Semantics

Source: https://docs.modular.com/mojo/manual/values/value-semantics/

The fundamental principle: each variable has unique access to a value, and code outside its scope cannot modify it.

```mojo
def main():
    var x = 1
    var y = x   # copy
    y += 1
    print("x:", x)  # x: 1
    print("y:", y)  # y: 2
```

Function arguments are immutable references by default ("look but don't touch"). Every value has an "exclusive owner"; values are destroyed when their owner's lifetime ends.

---

## Ownership and Argument Conventions

Source: https://docs.modular.com/mojo/manual/values/ownership/

Mojo's ownership rules:
1. Every value has only one owner at a time.
2. When the owner's lifetime ends, Mojo destroys the value.
3. If there are existing references to a value, Mojo extends the owner's lifetime.

### Argument Conventions

| Keyword | Behavior |
|---------|----------|
| `read` | Immutable reference (default). Function can read but not mutate. |
| `mut` | Mutable reference. Changes inside are visible outside. |
| `var` | Ownership transfer. Function gets exclusive ownership. |
| `ref` | Parametric mutability reference (mutable or immutable). |
| `out` | For `self` in constructors and named results; uninitialized at entry. |
| `deinit` | For destructors; initialized at entry, uninitialized when returning. |

```mojo
def add(mut x: Int, read y: Int):
    x += y

def main():
    var a = 1
    var b = 2
    add(a, b)
    print(a)  # 3
```

### Immutable Arguments (`read`)

Default convention. Callee gets an immutable reference — no copy made.

```mojo
def print_list(list: List[Int]):
    print(list.__str__())
```

Small values (`Int`, `Float`, `SIMD`) are always passed in machine registers for performance.

### Mutable Arguments (`mut`)

```mojo
def mutate(mut l: List[Int]):
    l.append(5)

def main():
    var values = [1, 2, 3, 4]
    mutate(values)
    print_list(values)  # [1, 2, 3, 4, 5]
```

**Argument exclusivity**: Mojo forbids passing the same value as both `mut` and another reference simultaneously.

```mojo
def append_twice(mut s: String, other: String):
    s += other
    s += other

def invalid_access():
    var my_string = "o"
    # error: passing `my_string` mut is invalid since it's also passed read
    append_twice(my_string, my_string)

# Fix: make a copy
def valid_access():
    var my_string = "o"
    var other_string = my_string
    append_twice(my_string, other_string)
    print(my_string)  # "ooo"
```

### Transfer Arguments (`var` and `^`)

```mojo
def take_text(var text: String):
    text += "!"
    print(text)

def main():
    var message = "Hello"
    take_text(message)     # copies (no transfer sigil)
    print(message)         # Hello
    # take_text(message^)  # transfer: message becomes uninitialized after
```

The `^` sigil ends the variable's lifetime:
```mojo
def main():
    var message = "Hello"
    take_text(message^)
    # print(message)  # error: use of uninitialized value
```

Ownership transfer happens via:
1. Caller uses `^` sigil (move constructor called if available)
2. Caller doesn't use `^` (Mojo copies if type is copyable)
3. Newly-created value passed directly (no variable owns it)

---

## Lifetimes, Origins, and References

Source: https://docs.modular.com/mojo/manual/values/lifetimes/

The **lifetime checker** analyzes dataflow to identify when variables are valid and inserts destructor calls. An **origin** tracks variable lifetimes and reference validity.

Origins answer:
- What variable owns this value?
- Can the value be mutated through this reference?

### Origin Types

- `ImmutOrigin` — immutable origin
- `MutOrigin` — mutable origin
- `Origin[mut=is_mutable]` — parametric mutability

### Origin Values

```mojo
origin_of(self)
origin_of(x.y)
origin_of(foo())
```

- **Static origins**: `StaticConstantOrigin` for values lasting the program's duration
- **Derived origins**: `origin_of()` operator
- **Union origins**: combine multiple origins (mutable only if all are mutable)
- **External origins**: `MutExternalOrigin`, `ImmutExternalOrigin` for untracked memory
- **Wildcard origins**: `ImmutAnyOrigin`, `MutAnyOrigin` (disables ASAP destruction — avoid)

### `ref` Arguments

```mojo
ref arg_name: arg_type
ref[origin_specifier(s)] arg_name: arg_type
```

Benefits:
- Accept parametric mutability arguments
- Tie argument lifetimes together
- Guarantee arguments passed in memory

```mojo
from std.collections import List
from std.memory import Span

def to_byte_span[
    is_mutable: Bool,
    //,
    origin: Origin[mut=is_mutable],
](ref[origin] list: List[Byte]) -> Span[Byte, origin]:
    return Span(list)
```

### `ref` Return Values

```mojo
-> ref[origin_specifier(s)] arg_type
```

**Parametric mutability** — mutable if `self` is mutable:
```mojo
def __getitem__(ref self, index: Int) raises -> ref[self] String:
    if (index >= 0 and index < len(self.names)):
        return self.names[index]
    else:
        raise Error("index out of bounds")
```

**Union origins** — extends lifetimes of both:
```mojo
def pick_one(cond: Bool, ref a: String, ref b: String) -> ref[a, b] String:
    return a if cond else b
```

---

## Value Creation (Constructors)

Source: https://docs.modular.com/mojo/manual/lifecycle/life/

Every Mojo struct requires a `__init__()` constructor.

```mojo
struct MyPet:
    var name: String
    var age: Int

    def __init__(out self, name: String, age: Int):
        self.name = name
        self.age = age
```

**`@fieldwise_init`** generates fieldwise constructors automatically.

**Overloading**: Constructors can be overloaded for different argument sets.

**All fields must be initialized** before `__init__()` returns.

**`@implicit` decorator** enables single-argument constructors to act as implicit conversions.

### Copy Constructor

```mojo
struct MyPair(Copyable):
    ...
# auto-generates: def __init__(out self, *, copy: Self)
```

**Deep copy example** (heap-allocated data):
```mojo
def __init__(out self, *, copy: Self):
    self.size = copy.size
    self.data = alloc[Int](copy.size)
    memcpy(self.data, copy.data, copy.size)
```

`ImplicitlyCopyable` allows automatic copying without explicit calls.

### Move Constructor

```mojo
struct MyPair(Movable):
    ...
# auto-generates move constructor using deinit convention + transfer sigil
```

Custom move constructor (rare):
```mojo
def __init__(out self, *, deinit take: Self):
    self.name = take.name^
```

### Move-Only and Immovable Types

- **Move-only**: implements `Movable` but not `Copyable`
- **Immovable**: neither copyable nor movable (e.g., synchronization primitives)
- **Trivial types**: `Int`, `Bool` — register-passable, no ownership semantics

---

## Instance Initialization

Source: https://docs.modular.com/mojo/manual/lifecycle/initialization/

Two concepts:
- **Fieldwise initialization**: all fields have valid values
- **Logical initialization**: `__init__()` has been called and the instance is usable

```mojo
def main():
    var me: Person
    me.age = 25      # fieldwise but NOT logically initialized
    print(me)        # Error: used without calling __init__
```

Within `__init__()`, `self` is logically initialized but fields are uninitialized. All fields must be set before calling any methods.

**Moving from fields** deinitializes them:
```mojo
var me = Person("Connor", 25)
var name_owner = me.name^  # field deinitialized
me.name = "John"           # reinitialize before use
```

**Destructor** (`__del__`):
```mojo
struct Contact:
    def __del__(deinit self):
        print("destroying contact")
```

The `deinit` convention: fields can be safely moved without reinitialization.

**ASAP destruction**: instances destroyed immediately after last use, not at scope end.

---

## Value Destruction

Source: https://docs.modular.com/mojo/manual/lifecycle/death/

Mojo uses **ASAP (As Soon As Possible)** destruction: values are destroyed after every sub-expression at their last use point.

```mojo
def example():
    var x = SomeType()
    use(x)  # x destroyed here
    more_code()
```

Benefits: composes with move optimization, eliminates tail-recursion issues.

### Destructors

```mojo
def __del__(deinit self):
    # cleanup: self is deinitialized on return
```

- Do NOT call destructors explicitly
- Pointers don't own pointed-to values — use `destroy_pointee()` for heap values
- All fields are destroyed even with a no-op custom `__del__`

### Explicitly-Destroyed Types

```mojo
@explicit_destroy("Must call save_and_close() or discard()")
struct FileBuffer:
    var path: String
    var data: String

    def save_and_close(deinit self) raises:
        write_to_disk(self.path, self.data)

    def discard(deinit self):
        pass

var buffer = FileBuffer(path)
buffer.write(message)
buffer^.save_and_close()  # required
```

Use `@explicit_destroy` when:
- Cleanup can fail and needs error handling
- Multiple cleanup paths exist
- Cleanup order matters
- Cleanup is expensive and should be deliberate

### Field Lifetimes

Mojo tracks each field independently. Fields can be temporarily transferred, but the whole object must remain fully initialized (or the compiler rejects the code).

### Explicit Lifetime Extension

```mojo
var t = "xyz"
print(t)
_ = t  # t.__del__() runs after this line
```
