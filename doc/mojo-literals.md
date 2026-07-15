# Mojo Literals Reference

## Overview
Mojo supports several literal types that produce values directly in source code without requiring variable reads or function calls.

## Integer Literals
Integers can be expressed in four bases:
- Decimal: `42`
- Hexadecimal: `0xFF` (0x or 0X prefix)
- Octal: `0o52` (0o or 0O prefix)
- Binary: `0b101010` (0b or 0B prefix)

Key rules: "Integer literals are always non-negative" and underscores between digits enhance readability. Leading zeros in decimal form are prohibited; use the octal prefix instead.

## Floating-Point Literals
These represent numbers with fractional or exponent components: `1.0`, `3.14159`, `.5`, `2.5e-3`. Like integers, floats are always non-negative, and underscores improve readability.

## String Literals
Mojo supports single quotes, double quotes, and triple-quotes for multi-line strings. Adjacent strings automatically concatenate. The `r` or `R` prefix creates raw strings where "Backslashes treated literally". Escape sequences include `\\`, `\n`, `\t`, `\xHH` (hex), and `\0–\377` (octal).

## T-String Literals
These enable expression interpolation: `t"Hello, {name}!"` evaluates expressions at runtime. They support triple-quote and raw prefixes (`rt`/`tr`). Use `{{` and `}}` for literal braces, and nesting is supported up to 20 levels deep.

## Other Literals
- **Boolean**: `True` and `False`
- **None**: Represents absence of value
- **Self**: References the enclosing type within struct/trait definitions
- **Discard pattern**: `_` ignores assignment values
- **Ellipsis**: `...` marks required trait methods (not interchangeable with `pass`)

---

**Source:** https://docs.modular.com/mojo/reference/mojo-literals/
