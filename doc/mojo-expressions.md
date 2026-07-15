# Mojo Expression Reference

## Core Expression Types

**Identifier expressions** refer to named elements like variables, functions, types, or modules.

**Parenthesized expressions** group subexpressions and override precedence: `(a + b) * c`

**Tuples** are fixed-size, ordered value groups. The comma creates the tuple structure: `var a = 2, 3` or `(1,)` for single elements.

## Collections

- **Lists**: `[1, 2, 3]` with comma-separated values
- **Dictionaries**: `{"Alice": 30, "Bob": 25}` using key-value pairs
- **Sets**: `{2, 3, 5, 7}` with values but no colons

## Operations

**Member access** uses dot notation: `text.count()` or `point.x`

**Calls** invoke functions or construct values: `print("hello")` or `Point(1.0, 2.0)`

**Subscripts and slices** access elements: `collection[0]` or `items[0:3]` for ranges

**Ternary conditional**: `"even" if x % 2 == 0 else "odd"`

**Walrus operator** (`:=`) assigns and returns the value within expressions: `if (n := len(items)) > 10:`

## Advanced Features

**Compile-time expressions** using `comptime(expression())` evaluate during compilation, not runtime.

**Comprehensions** build collections concisely:
- List: `[x * x for x in [0, 1, 2, 3, 4] if x % 2 == 0]`
- Set: `{fib(x) for x in range(6)}`
- Dictionary: `{x: x * x for x in range(3)}`

Multiple `for` and `if` clauses support nested iteration and filtering.

---

**Source:** https://docs.modular.com/mojo/reference/mojo-expressions/
