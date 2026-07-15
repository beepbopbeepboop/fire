# Mojo Manual — Language Basics

Source: https://docs.modular.com/mojo/manual/

---

## Language Basics Overview

Mojo combines Python-like syntax with static type checking, memory safety, and advanced compiler technology. Every Mojo program requires a `main()` function as its entry point.

```mojo
def main():
    print("Hello, world!")
```

Mojo is currently **not** meant for beginners; it is a young language with many features still missing.

---

## Blocks and Statements

Source: https://docs.modular.com/mojo/manual/basics#blocks-and-statements

Code blocks such as functions, conditions, and loops are defined with a colon followed by indented lines. You can use any number of spaces or tabs for your indentation (we prefer 4 spaces).

All code statements in Mojo end with a newline. However, statements can span multiple lines if you indent the following lines. For example, this long string spans two lines:

```mojo
def print_line():
    long_text = "This is a long line of text that is a lot easier to read if"
                " it is broken up across two lines instead of one long line."
    print(long_text)
```

And you can chain function calls across lines:

```mojo
def print_hello():
    text = ",".join("Hello", " world!")
    print(text)
```

---

## Code Comments

Source: https://docs.modular.com/mojo/manual/basics#code-comments

You can create a one-line comment using the hash `#` symbol:

```mojo
# This is a comment. The Mojo compiler ignores this line.
var message = "Hello, World!"  # This is also a valid comment
```

API documentation comments are enclosed in triple quotes (docstrings). Technically, docstrings aren't comments — they're a special use of Mojo's multi-line string literal syntax. You can generate API references from docstrings using the `mojo doc` command:

```mojo
def greet(name: String):
    """Greet a person by name."""
    print("Hello, " + name + "!")
```

---

## Variables

Source: https://docs.modular.com/mojo/manual/variables/

A variable is a name that holds a value or object. All variables in Mojo are mutable.

### Declaration

Two ways to declare a variable:

**Explicitly-declared** (block-level scope):
```mojo
var a = 5
var b: Float64 = 3.14
var c: String
```

**Implicitly-declared** (function-level scope, Python-like):
```mojo
a = 5
b: Float64 = 3.14
c: String
```

Both are strongly typed — the type is set at creation and never changes.

### Type Annotations

```mojo
var name: String = get_name()
name: String = get_name()
```

**Late initialization** (only with explicit type):
```mojo
def my_function(x: Int):
    var z: Float32
    if x != 0:
        z = 1.0
    else:
        z = foo()
    print(z)
```

### Implicit Type Conversion

```mojo
var number: Float64 = Int(1)   # Int implicitly converts to Float64
print(number)  # 1.0
```

Implicit conversion uses the `@implicit` decorator on single-argument constructors.

### Variable Scopes

- `var` variables: **block-level** scope
- Implicit variables: **function-level** scope (like Python)

```mojo
def lexical_scopes():
    var num = 1
    if num == 1:
        var num = 2      # new inner-scope variable (shadows outer)
        print("num:", num)  # 2
    print("num:", num)  # 1 (outer)
```

```mojo
def function_scopes():
    num = 1
    if num == 1:
        num = 2          # updates function-scope variable
    print("num:", num)  # 2
```

### Copying and Moving Values

A variable owns its value; only one variable can own a value at a time.

- **Copyable types**: `second = first.copy()`
- **Implicitly copyable** (e.g., `Int`, `Float64`, `Bool`): `another = one`
- **Transfer ownership**: `second = first^` (leaves `first` uninitialized)

### Reference Bindings

```mojo
animals: List[String] = ["Cats", "Dogs", "Zebras"]
print(animals[2])  # does not copy

ref item_ref = items[1]  # binds a reference
item_ref += 1            # mutates items[1]
```

Reference bindings cannot be re-bound once assigned.

---

## Functions

Source: https://docs.modular.com/mojo/manual/functions/

Functions use the `def` keyword (`fn` is deprecated as of Mojo v26.2).

```
def function_name[parameters ...](arguments ...) -> return_value_type:
    function_body
```

### Arguments vs. Parameters

- **Arguments** (`()`): runtime values
- **Parameters** (`[]`): compile-time constants

```mojo
def add_tensors[rank: Int](a: MyTensor[rank], b: MyTensor[rank]) -> MyTensor[rank]:
    ...
```

### Optional Arguments

```mojo
def my_pow(base: Int, exp: Int = 2) -> Int:
    return base ** exp

var z = my_pow(3)   # exp defaults to 2
```

### Keyword Arguments

```mojo
var z = my_pow(exp=3, base=2)
```

### Variadic Arguments

**Homogeneous** (same type):
```mojo
def sum(*values: Int) -> Int:
    var total: Int = 0
    for value in values:
        total = total + value
    return total
```

**Heterogeneous** (different types):
```mojo
def count_many_things[*ArgTypes: Intable](*args: *ArgTypes) -> Int:
    var total = 0
    comptime for i in range(args.__len__()):
        total += Int(args[i])
    return total

print(count_many_things(5, 11.7, 12))  # 28
```

### Variadic Keyword Arguments

```mojo
def print_nicely(**kwargs: Int):
    for item in kwargs.items():
        print(item.key, "=", item.value)

print_nicely(a=7, y=8)
```

### Positional-only and Keyword-only

```mojo
def min(a: Int, b: Int, /) -> Int:    # positional-only
    return a if a < b else b

def sort(*values: Float64, ascending: Bool = True):  # keyword-only after *
    pass
```

### Overloaded Functions

```mojo
def add(x: Int, y: Int) -> Int:
    return x + y

def add(x: String, y: String) -> String:
    return x + y
```

Overload resolution order: fewest implicit conversions → no variadic args → no variadic params → shortest param signature → non-static over static.

### Return Values

```mojo
def get_greeting() -> String:
    return "Hello"
```

**Named results** (for non-copyable/non-movable types):
```mojo
def get_name_tag(var name: String, out name_tag: NameTag):
    name_tag = NameTag(name^)

tag = get_name_tag("Judith")
```

### Raising Functions

```mojo
def raises_error() raises:
    raise Error("There was an error.")

def validate(value: Int) raises ValidationError -> Int:
    ...
```

---

## Types

Source: https://docs.modular.com/mojo/manual/types/

All values have an associated data type. Most types are nominal types defined by a `struct`.

### Integer Types

**Signed**: `Int8`, `Int16`, `Int32`, `Int64`, `Int128`, `Int256`  
**Unsigned**: `UInt8`, `UInt16`, `UInt32`, `UInt64`, `UInt128`, `UInt256`  
**Default**: `Int` (system native word size, typically 64-bit), `UInt`

Overflow behavior:
- Signed: wraps using two's complement (`Int8(127) + 1 == -128`)
- Unsigned: wraps to 0 (`UInt8(255) + 1 == 0`)

### Floating-Point Types

Standard: `Float16`, `Float32`, `Float64`, `BFloat16`  
AI-optimized (GPU): `Float8_e5m2`, `Float8_e4m3fn`, `Float4_e2m1fn`, etc.

```mojo
var inf = FloatLiteral.infinity
var nan = FloatLiteral.nan
var negzero = FloatLiteral.negative_zero
```

Use `math.isclose()` for floating-point equality comparison.

### Numeric Literals

- Integer: `1760`, `0xaa`, `0o77`, `0b0111`
- Floating-point: `3.14`, `1.2e9`

Literals are arbitrary-precision at compile time, materialize to `Int`/`Float64` at runtime.

### SIMD and DType

```mojo
var vec = SIMD[DType.float32, 4](3.0, 2.0, 2.0, 1.0)
var vec1 = SIMD[DType.int8, 4](2, 3, 5, 7)
var vec2 = SIMD[DType.int8, 4](1, 2, 3, 4)
var product = vec1 * vec2  # [2, 6, 15, 28]
```

Type aliases: `comptime Int8 = Scalar[DType.int8]`, `comptime Float32 = Scalar[DType.float32]`

**Numeric conversion**:
```mojo
simd1 = SIMD[DType.float32, 4](2.2, 3.3, 4.4, 5.5)
simd2 = SIMD[DType.int16, 4](-1, 2, -3, 4)
simd3 = simd1 * simd2.cast[DType.float32]()
```

### Strings

```mojo
var s: String = "Testing"
s += " Mojo strings"
print(s)  # Testing Mojo strings
```

**Construction**:
```mojo
var s = String("Items in list: ", 5)
```

**Template strings (TString)**:
```mojo
var count = 3
var items = "apples"
print(t"Give me {count} {items}.")  # Give me 3 apples.
```

**Raw strings**:
```mojo
print(r"Hello\nWorld")  # Hello\nWorld (literal backslash)
```

**Multi-line**:
```mojo
comptime s = """
Multi-line string literals let you
enter long blocks of text."""
```

**String formatting**:
```mojo
print("{0} {1} {0}".format("Mojo", 1.125))  # Mojo 1.125 Mojo
```

### Booleans

```mojo
var conditionA = False
var conditionB = not conditionA
print(conditionA, conditionB)  # False True
```

### Tuples

```mojo
example_tuple = (1, "Example")
s = example_tuple[1]
x, y = example_tuple
```

### Collection Types

**List** (dynamically-sized array):
```mojo
var list = [2, 3, 5]
list.append(7)
list.append(11)
print(list.pop())  # 11

for item in list:
    print(item, end=", ")

# Mutable iteration:
for ref item in list:
    item = 0
```

List comprehensions:
```mojo
var list2 = [x*Int(y) for x in nums for y in list if x != 3]
```

**Dict** (associative array):
```mojo
var d: Dict[String, Float64] = {"pi": 3.14159, "e": 2.71828}
for item in d.items():
    print(item.key, item.value)
```

**Set** (unique values):
```mojo
i_like = {"sushi", "ice cream", "tacos"}
you_like = {"burgers", "tacos", "ice cream"}
we_like = i_like.intersection(you_like)
```

**Optional** (value or None):
```mojo
var opt: Optional[String] = "Testing"
if opt:
    var value_ref = opt.value()
    print(value_ref)

var custom: Optional[String] = None
print(custom.or_else("Hello"))  # Hello
```

---

## Operators

Source: https://docs.modular.com/mojo/manual/operators/

### Arithmetic

```mojo
7 + 3     # 10
2 ** 8    # 256  (exponentiation, right-associative)
7 / 2     # 3.5  (truncates toward zero)
7 // 2    # 3    (floor division, toward -infinity)
7 % 2     # 1
```

Unary: `-x` (negate), `+x` (identity), `~x` (bitwise NOT)

Matrix multiplication: `@` (calls `__matmul__()`)

### Comparisons

`==`, `!=`, `<`, `<=`, `>`, `>=`

Chained comparisons: `1 < x < 10` evaluates as `(1 < x) and (x < 10)`

### Bitwise

`&` (AND), `|` (OR), `^` (XOR), `<<` (left shift), `>>` (right shift)

### Boolean Logic

```mojo
# Short-circuit evaluation
result = a and b   # b not evaluated if a is False
result = a or b    # b not evaluated if a is True
result = not a
```

Truthiness: zero, empty strings, empty collections, `None` are falsy.

### Membership and Identity

```mojo
print("red" in colors)
print("nut" in "peanut butter")
if opt is None:
    print("No value")
```

### String Operators

```mojo
var greeting = "Hello" + " " + "Mojo"
print("ha" * 3)   # hahaha
```

### Conditional Expression

```mojo
var result = "pass" if score > 65 else "fail"
```

### Assignment Operators

`+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `**=`, `@=`, `&=`, `|=`, `^=`, `<<=`, `>>=`

**Walrus operator**:
```mojo
while (name := input("Name: ")) != "quit":
    print("Hello,", name)
```

### Precedence (tightest to loosest)

Function calls → exponentiation → unary prefix → arithmetic → shifts → bitwise → comparisons → boolean logic → conditional expression → walrus

---

## Control Flow

Source: https://docs.modular.com/mojo/manual/control-flow/

### `if` / `elif` / `else`

```mojo
temp_celsius = 25
if temp_celsius <= 0:
    print("It is freezing.")
elif temp_celsius < 20:
    print("It is cool.")
elif temp_celsius < 30:
    print("It is warm.")
else:
    print("It is hot.")
```

Single-line: `if temp_celsius > 20: print("It is warm.")`

Short-circuit evaluation: `or` stops if first is `True`, `and` stops if first is `False`.

Conditional expression: `forecast = "warm" if temp_celsius > 20 else "cool"`

### `while`

```mojo
fib_prev, fib_curr = 0, 1
while fib_curr < 50:
    print(",", fib_curr, end="")
    fib_prev, fib_curr = fib_curr, fib_prev + fib_curr
```

`continue` skips to next iteration; `break` exits loop.

Optional `else` clause runs when condition becomes `False` (not when `break`/`return`):
```mojo
while n < 4:
    n += 1
else:
    print("Loop completed")
```

### `for`

Iterates over any type with `__iter__()`, `__next__()`, and `__len__()`.

```mojo
states = ["California", "Hawaii", "Oregon"]
for state in states:
    print(state)

# Dict iteration
for state in capitals:
    print(capitals[state])

for item in capitals.items():
    print(item.value, item.key)
```

**Mutable iteration**:
```mojo
var values = [1, 4, 7, 3, 6, 11]
for ref value in values:
    if value % 2 != 0:
        value -= 1
```

**Range**:
```mojo
for i in range(5):
    print(i, end=", ")
```

`continue`, `break`, and optional `else` work the same as `while`.

**Python collections**:
```mojo
from std.python import Python

def main() raises:
    py_list = Python.list(42, "cat", 3.14159)
    for py_obj in py_list:
        print(py_obj)
```

---

## Errors and Error Handling

Source: https://docs.modular.com/mojo/manual/errors/

Mojo uses a value-based error model (not stack-unwinding exceptions) for minimal runtime overhead.

### Raising Errors

```mojo
raise Error("file not found")
raise "file not found"  # equivalent

def read_file_fn(path: String) raises -> String:
    if not path:
        raise "path cannot be empty"
    return "contents of " + path
```

### Handling Errors

```mojo
try:
    result = process_record(id)
except e:
    print("Error:", e)
else:
    print("Success:", result)
finally:
    print("Cleanup")
```

**Re-raising**:
```mojo
except e:
    print("Logging:", e)
    raise e^
```

### Typed Errors

```mojo
@fieldwise_init
struct ValidationError(Copyable, Writable):
    var field: String
    var reason: String

    def write_to(self, mut writer: Some[Writer]):
        writer.write("ValidationError(", self.field, "): ", self.reason)

def validate_username(username: String) raises ValidationError -> String:
    if username.byte_length() == 0:
        raise ValidationError(field="username", reason="cannot be empty")
    return username

try:
    var name = validate_username("")
except e:
    print("Error in field '" + e.field + "': " + e.reason)
```

### Enumerated Error Types

```mojo
@fieldwise_init
struct FileError(Equatable, ImplicitlyCopyable, Writable):
    var _variant: Int
    comptime not_found = FileError(_variant=1)
    comptime permission_denied = FileError(_variant=2)

try:
    print(open_file("/secret"))
except e:
    if e == FileError.not_found:
        print("Not found:", e)
```

### The `Never` Type

```mojo
def panic(msg: String) raises -> Never:
    raise Error(msg)
```

### Parametric Raises

```mojo
def run_action[
    ErrorType: AnyType
](action: def() thin raises ErrorType -> Int) raises ErrorType -> Int:
    return action()
```

### Stack Traces

```bash
MODULAR_DEBUG=stack-trace-on-error ./program
mojo build --debug-level full program.mojo
```

```mojo
try:
    func1()
except e:
    var stack_trace = e.get_stack_trace()
    if stack_trace:
        print(stack_trace.value())
```

### Context Managers

```mojo
@fieldwise_init
struct Timer(ImplicitlyCopyable):
    var start_time: Int

    def __enter__(mut self) -> Self:
        self.start_time = Int(time.perf_counter_ns())
        return self

    def __exit__(mut self):
        elapsed = round(Float64(time.perf_counter_ns() - UInt(self.start_time)) / 1e6, 3)
        print("Elapsed time:", elapsed, "milliseconds")

with Timer():
    time.sleep(1.0)
```

**Multiple context managers**:
```mojo
with open(input_file, "r") as f_in, open(output_file, "w") as f_out:
    f_out.write(f_in.read().upper())
```

**Conditional `__exit__`** (return `True` to suppress, `False` to re-raise):
```mojo
def __exit__(mut self, e: Error) -> Bool:
    if String(e) == "just a warning":
        return True
    return False
```

---

## Structs

Source: https://docs.modular.com/mojo/manual/structs/

A struct bundles data (fields) with operations (methods). Unlike Python classes, Mojo structs are static and bound at compile time.

### Basic Definition

```mojo
struct MyPair:
    var first: Int
    var second: Int

    def __init__(out self, first: Int, second: Int):
        self.first = first
        self.second = second
```

`out self` indicates `self` is uninitialized and must be initialized before returning.

### Fieldwise Constructor

```mojo
@fieldwise_init
struct MyPair:
    var first: Int
    var second: Int
```

### Instantiation

```mojo
var mine = MyPair(2, 4)
print(mine.first)  # 2
```

### Mutating Methods

```mojo
struct MyStruct:
    var value: Int

    def increment(mut self):
        self.value += 1
```

### Copyability and Moveability

```mojo
struct MyPair(Movable):          # move-only
    ...

struct MyPair(Copyable):         # copyable (also movable)
    ...

struct MyPair(ImplicitlyCopyable):  # implicitly copyable
    ...
```

### Fields

- Declared with `var`
- Unique names (no clash with methods/comptime)
- Must be initialized in constructors

### Methods

```mojo
@fieldwise_init
struct MyPair:
    var first: Int
    var second: Int

    def get_sum(self) -> Int:
        return self.first + self.second

var mine = MyPair(6, 8)
print(mine.get_sum())  # 14
```

### Static Methods

```mojo
struct Logger:
    @staticmethod
    def log_info(message: String):
        print("Info: ", message)

Logger.log_info("Static method called.")
```

### Special Methods (Dunder)

- Lifecycle: `__init__()`, `__del__()`
- Operator overloading: `__add__()`, `__lt__()`, `__eq__()`, etc.
- Value ownership: copy and move constructors

### Structs vs. Python Classes

| Feature | Python Classes | Mojo Structs |
|---------|---|---|
| Binding | Dynamic (runtime) | Static (compile-time) |
| Modification | Monkey-patching allowed | Fixed structure |
| Inheritance | Supported | Not supported; use traits |
| Class attributes | Supported | Not supported |

---

## Modules and Packages

Source: https://docs.modular.com/mojo/manual/packages/

### Modules

A Mojo module is a single source file for import by other files.

```mojo
# mymodule.mojo
struct MyPair:
    var first: Int
    var second: Int
    def dump(self): print(self.first, self.second)
```

Importing:
```mojo
from mymodule import MyPair
import mymodule
import mymodule as my
```

### Packages

A package is a directory with a `__init__.mojo` file.

```
main.mojo
mypackage/
    __init__.mojo
    mymodule.mojo
```

```mojo
from mypackage.mymodule import MyPair
```

**Compile a package**:
```bash
mojo package mypackage -o mypack.mojopkg
```

**`__init__.mojo`** can re-export members:
```mojo
from .mymodule import MyPair
```

Then callers can do:
```mojo
from mypackage import MyPair
```
