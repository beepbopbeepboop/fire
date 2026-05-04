# Mojo Manual — Metaprogramming

Source: https://docs.modular.com/mojo/manual/metaprogramming/
        https://docs.modular.com/mojo/manual/parameters/
        https://docs.modular.com/mojo/manual/traits/
        https://docs.modular.com/mojo/manual/generics/
        https://docs.modular.com/mojo/manual/reflection/

---

## Intro to Metaprogramming

Source: https://docs.modular.com/mojo/manual/metaprogramming/

Mojo's compile-time metaprogramming uses the same language for both compile-time and runtime programs — no separate preprocessor or template syntax.

Key capabilities:
- **Compile-time statements and expressions** via `comptime`
- **Compile-time parameters** on functions and structs
- **Traits and generics** for type-generic code

---

## Compile-time Evaluation

Source: https://docs.modular.com/mojo/manual/metaprogramming/comptime-evaluation/

### `comptime` Values

A `comptime` value is always evaluated at compile time.

```mojo
comptime SIZE = 1024 // 32
comptime block_size = _calculate_block_size()
comptime Float16 = SIMD[DType.float16, 1]  # type alias
```

`comptime` values follow scoping rules similar to `var` variables. You can only assign a `comptime` value to a given identifier once in a given scope.

New scopes created by: function bodies, `comptime if` branches, `comptime for` bodies.

### Compile-time Flow Control

**Conditionals**:
```mojo
comptime if has_accelerator():
    run_on_gpu()
else:
    run_on_cpu()
```

**Loop unrolling** (sequence must be a compile-time expression):
```mojo
comptime for i in range(1, 5):
    b[i-1] = a[i] + a[i-1]
```

Expands to branchless code without runtime bounds checks.

### Limitations

Mojo won't execute at compile time:
- File I/O operations
- Foreign function calls
- Functions that can raise errors
- GPU code (runs on CPU instead)

### How the Compiler Works

Three components:
- **Parser**: constant folding on simple expressions
- **Interpreter**: executes compile-time code
- **Elaborator**: substitutes concrete values into parameterized code

---

## Parameters (Compile-Time Values)

Source: https://docs.modular.com/mojo/manual/parameters/

A parameter is a compile-time input in square brackets `[]`; arguments are runtime values in parentheses `()`.

### Parameterized Functions

```mojo
def repeat[count: Int](msg: String):
    comptime for i in range(count):
        print(msg)

repeat[3]("Hello")  # prints "Hello" 3 times
```

### Parameter Inference

```mojo
var v = Scalar[DType.float16](42)
print(rsqrt(v))  # compiler infers parameter from v's type
```

### Parameterized Structs

```mojo
struct GenericArray[ElementType: Copyable & ImplicitlyDestructible]:
    var data: UnsafePointer[Self.ElementType, MutExternalOrigin]
    var size: Int
```

Reference struct parameters with dot syntax: `Self.ElementType`.

### `comptime` Members

```mojo
struct Circle[radius: Float64]:
    comptime pi = 3.14159265359
    comptime circumference = 2 * Self.pi * Self.radius
```

### Optional and Keyword Parameters

```mojo
def speak[a: Int = 3, msg: String = "woof"]():
    print(msg, a)

speak[msg="baaa"]()  # prints 'baaa 3'
```

### Variadic Parameters

```mojo
struct MyTensor[*dimensions: Int]:
    pass
```

Variadic parameters must be register-passable and homogeneous.

### Infer-only Parameters

Marked with `//` (double slash separator); must be inferred, cannot be specified explicitly:

```mojo
def dependent_type[dtype: DType, //, value: Scalar[dtype]]():
    print("Value: ", value)

dependent_type[Float64(2.2)]()  # dtype inferred from value
```

### Compile-Time Expressions in Parameters

```mojo
def concat[
    dtype: DType, ls_size: Int, rh_size: Int, //
](lhs: SIMD[dtype, ls_size], rhs: SIMD[dtype, rh_size]) -> SIMD[
    dtype, ls_size + rh_size
]:
    ...
```

### Parameterized `comptime` Values

```mojo
comptime AddOne[a: Int] : Int = a + 1
comptime nine = AddOne[8]
```

### Type Binding States

- **Fully-bound**: all parameters specified (concrete type)
- **Partially-bound**: some parameters specified with `_` for unbound
- **Unbound**: no parameters specified

```mojo
comptime StringKeyDict[ValueType: Copyable] = Dict[String, ValueType]
var b: StringKeyDict[UInt8] = {"answer": 42}
```

### Automatic Parameterization

Functions with unbound type arguments automatically gain infer-only parameters:

```mojo
def print_params(vec: SIMD):
    print(vec.dtype)
    print(vec.size)
# equivalent to: def print_params[dtype: DType, size: Int, //](vec: SIMD[dtype, size])
```

### The `rebind()` Builtin

Resolves type ambiguity in static dispatch patterns:

```mojo
def generic_simd[nelts: Int](x: SIMD[DType.float32, nelts]):
    comptime if nelts == 8:
        take_simd8(rebind[SIMD[DType.float32, 8]](x))
```

---

## Traits

Source: https://docs.modular.com/mojo/manual/traits/

A trait is a set of requirements that a type must implement.

### Defining Traits

```mojo
trait Quackable:
    def quack(self):
        ...
```

Methods with `...` (ellipsis) must be implemented by conforming types. Methods with bodies provide default implementations.

### Conforming to Traits

```mojo
struct Duck(Copyable, Quackable):
    def quack(self):
        print("Quack")
```

### Using Traits as Type Bounds

```mojo
def make_it_quack[DuckType: Quackable](maybe_a_duck: DuckType):
    maybe_a_duck.quack()
```

### Trait Composition

```mojo
def quack_and_go[type: Quackable & Flyable](quacker: type):
    quacker.quack()
    quacker.fly()
```

### Trait Refinement

```mojo
trait Bird(Animal):
    def fly(self):
        ...
```

### `comptime` Members in Traits

Traits can include `comptime` members that conforming structs must define.

### Built-in Traits

`Copyable`, `Movable`, `ImplicitlyCopyable`, `ImplicitlyDestructible`, `Sized`, `Writable`, `Hashable`, `Comparable`, `Equatable`, `Boolable`, `Intable`, `KeyElement`, `AnyType`, and more.

---

## Generics

Source: https://docs.modular.com/mojo/manual/generics/

Generics eliminate duplicated logic by writing one implementation that adapts at compile time.

### Type Generics

**Trait bounds** restrict which types are accepted:

```mojo
def all_equal[
    T: Equatable & Copyable
](ref lhs: List[T], ref rhs: List[T]) -> Bool:
    if len(lhs) != len(rhs): return False
    for left, right in zip(lhs, rhs):
        if left != right:
            return False
    return True
```

Naming: type parameters use PascalCase (`T`, `U`, `K`, `V`), value parameters use snake_case (`capacity`, `size`).

Baseline trait options:
- `AnyType`: most permissive, no requirements
- `ImplicitlyDestructible`: common baseline requiring cleanup at scope exit

### Generic Types

```mojo
comptime ComparableValue = Equatable & ImplicitlyCopyable

@fieldwise_init
struct Pair[T: ComparableValue](ComparableValue):
    var left: Self.T
    var right: Self.T

    def __eq__(self, other: Pair[Self.T]) -> Bool:
        return self.left == other.left and self.right == other.right
```

### Mixing Type and Value Parameters

```mojo
def example[
    T: Writable & Copyable,   # type parameter
    count: Int,               # value parameter
](self, data: String, init_value: T) -> String:
    ...
```

### Downcasting Safely

```mojo
def process[T: AnyType](value: T):
    comptime if conforms_to(T, Writable & ImplicitlyCopyable):
        var w = trait_downcast[Writable & ImplicitlyCopyable](value)
        print(w)
    else:
        print("<not writable>")
```

### Value Generics

```mojo
comptime MyCollectionElement = ImplicitlyCopyable & ImplicitlyDestructible

def make_filled[T: MyCollectionElement, size: Int](splat_value: T) -> List[T]:
    var result = List[T](capacity=size)
    for _ in range(size):
        result.append(splat_value)
    return result^

var three_zeros = make_filled[Int, 3](0)
var five_hellos = make_filled[String, 5]("hello")
```

### Conditional Trait Conformance

```mojo
comptime BaseTraits = Copyable & ImplicitlyDestructible

@fieldwise_init
struct Wrapper[T: BaseTraits](
    Writable where conforms_to(T, Writable)
):
    var value: Self.T
```

**Parts conformance**:
```mojo
@fieldwise_init
struct Pair[L: BaseTraits, R: BaseTraits](
    Hashable where conforms_to(L, Hashable) and conforms_to(R, Hashable)
):
    var left: Self.L
    var right: Self.R
```

**Conditional methods** with `where` clauses:
```mojo
def __bool__(self) -> Bool where conforms_to(Self.T, Boolable):
    return trait_downcast[Boolable](self.value).__bool__()
```

**Conditional value parameter conformance**:
```mojo
struct SizedListWrapper[capacity: Int, T: Copyable](
    Sized, Writable where conforms_to(T, Writable) and capacity > 0
):
    ...
    def first(self) -> Self.T where Self.capacity > 0:
        return self.data[0].copy()
```

---

## Constraints and Assertions

Source: https://docs.modular.com/mojo/manual/metaprogramming/constraints/

Constraints express program guarantees beyond the type system using the `where` keyword.

### Defining Constraints

**On function/struct parameters**:
```mojo
def fib[x: Int where x >= 0]() -> Int:
    ...
```

**On method declarations**:
```mojo
def sort() where conforms_to(Self.T, Comparable):
    ...
```

**On trait conformance lists**:
```mojo
struct MyContainer[T: AnyType](Copyable where conforms_to(T, Copyable)):
    ...
```

### Symbolic Propositions

The system tracks propositions as "known true" within scopes. Knowledge introduced by:
- Struct declarations (all struct constraints)
- Function constraints (known within function body)
- `comptime if` blocks (condition known inside)
- `comptime assert` statements (assertion known after)

### Compile-Time Assertions

```mojo
comptime assert x > 0, "x must be greater than 0."
```

Message is optional. Adds condition to known-true list for subsequent code.

### Limited Evaluation

- **Simple implication**: known `A and B` satisfies requirement for `A` alone
- **Canonicalization**: `x > 0` equals `x >= 1`
- **Context-free folding**: `1 + 1` becomes `2`

### Best Practices

For writing functions:
1. Does the function handle the entire input domain?
2. Is the limitation central to the code?
3. Is the constraint understandable by callers?

Use dedicated types for common refinements, `where` clauses for user-facing preconditions, and `comptime assert` for internal invariants.

---

## Materialization

Source: https://docs.modular.com/mojo/manual/metaprogramming/materialization/

Materialization copies a compile-time value into a runtime variable.

```mojo
comptime comptime_value = 1000
var runtime_value = comptime_value
```

Implicitly copyable types (`Int`, `Bool`) materialize automatically. Non-copyable types require explicit materialization:

```mojo
def lookup_fn(count: Int):
    comptime list_of_values = [1, 3, 5, 7]
    var list = materialize[list_of_values]()
    for i in range(count):
        idx = dynamic_function(i)
        lookup = list[idx]
        process(lookup)
```

### Global Lookup Tables

```mojo
from std.builtin.globals import global_constant

def use_lookup(idx: Int) -> Int64:
    comptime numbers: InlineArray[Int64, 10] = [
        1, 3, 14, 34, 63, 101, 148, 204, 269, 343
    ]
    ref lookup_table = global_constant[numbers]()
    if idx >= len(lookup_table):
        return 0
    return lookup_table[idx]
```

Use `ref` (not `var`) to avoid triggering implicit copying.

### Using `comptime` to Force Compile-Time Evaluation

```mojo
comptime tmp = calculate_something()
var y = x * tmp

# Inline form:
var y = x * comptime (calculate_something())
```

### Materializing Literals

```mojo
comptime str_literal = "Hello"
var str = str_literal             # creates String
var static_str: StaticString = str_literal  # creates StaticString
```

---

## Reflection

Source: https://docs.modular.com/mojo/manual/reflection/

Reflection in Mojo enables compile-time code to inspect its own structure. All reflection occurs at compile time. **Note**: Newly introduced and currently incomplete.

### Reflection APIs

```mojo
from std.reflection import (
    struct_field_count, struct_field_names,
    get_type_name, struct_field_types
)
```

- `get_type_name[T]()` — type name as string
- `struct_field_count[T]()` — number of fields
- `struct_field_names[T]()` — indexed list of field names
- `struct_field_types[T]()` — indexed list of field types

### Example: Inspect a Type

```mojo
def show_type[T: AnyType]():
    comptime type_name = get_type_name[T]()
    comptime field_count = struct_field_count[T]()
    comptime field_names = struct_field_names[T]()
    comptime field_types = struct_field_types[T]()

    print("struct", type_name)

    comptime for idx in range(field_count):
        comptime field_name = field_names[idx]
        comptime field_type = get_type_name[field_types[idx]]()
        var intro = "├──" if idx < (field_count - 1) else "└──"
        print(intro, " var ", field_name, ": ", field_type, sep="")

@fieldwise_init
struct MyStruct:
    var x: String
    var y: Optional[Int]

def main():
    show_type[MyStruct]()
```

### Example: Copying Data via Reflection

```mojo
from std.reflection import struct_field_count, struct_field_types

trait MakeCopyable:
    def copy_to(self, mut other: Self):
        comptime field_count = struct_field_count[Self]()
        comptime field_types = struct_field_types[Self]()

        comptime for idx in range(field_count):
            comptime field_type = field_types[idx]
            comptime if not conforms_to(field_type, Copyable): continue

            ref p_value = __struct_field_ref(idx, self)
            trait_downcast[Copyable & ImplicitlyDestructible](
                __struct_field_ref(idx, other)
            ) = trait_downcast[Copyable & ImplicitlyDestructible](
                p_value
            ).copy()
```

### Example: Testing Equality via Reflection

```mojo
def test_equality[T: AnyType](lhs: T, rhs: T) -> Bool:
    comptime field_count = struct_field_count[T]()
    comptime field_types = struct_field_types[T]()

    comptime for idx in range(field_count):
        comptime field_type = field_types[idx]
        comptime if not conforms_to(field_type, Equatable): continue

        ref lhs_value = __struct_field_ref(idx, lhs)
        ref rhs_value = __struct_field_ref(idx, rhs)

        if trait_downcast[Equatable](lhs_value) != trait_downcast[Equatable](rhs_value):
            return False

    return True
```

Key functions:
- `conforms_to(T, Trait)` — check trait conformance
- `trait_downcast[Trait](value)` — rebind value to trait
- `__struct_field_ref(idx, instance)` — get field reference by index (struct types only)
