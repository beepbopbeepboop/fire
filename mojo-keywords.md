# Mojo Identifiers and Keywords

## Identifiers

**Regular Identifiers**: Names must start with a letter or underscore, followed by letters, digits, or underscores. The pattern is `[a-zA-Z_][a-zA-Z0-9_]*`. Examples include `foo`, `_private`, and `MyStruct`. Identifiers are case-sensitive.

**Escaped Identifiers**: Enclosed in backticks, these allow special characters including non-ASCII text and spaces. As noted, "Backticks allow any characters except vertical whitespace and backticks themselves." This is useful for calling external code using Mojo keywords as names or writing non-English identifiers.

## Keywords by Category

**Control Flow**: `if`, `elif`, `else`, `for`, `while`, `break`, `continue`, `pass`, `return`, `with`

**Error Handling**: `try`, `except`, `finally`, `raise`, `assert`

**Declarations**: `def`, `struct`, `trait`, `var`, `ref`

**Keyword Operators**: `and`, `or`, `not`, `in`, `is`

**Imports**: `import`, `from`, `as`

**Compile-time**: `comptime`

**Literals**: `True`, `False`, `None`, `Self` (all case-sensitive)

## Conventions

These control how values pass through function signatures:

- `mut`: Mutable reference to existing value
- `out`: Returns value without arrow notation
- `deinit`: Destructive transfer at lifecycle end
- `var`: Independent mutable owned copy
- `ref`: Non-owning reference

An unmodified `self` argument remains immutable unless marked `mut`.

---

**Source:** https://docs.modular.com/mojo/reference/mojo-keywords/
