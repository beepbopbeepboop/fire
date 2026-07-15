# Mojo Operator Reference

## Operator Precedence

Mojo follows a standard precedence hierarchy from highest to lowest:

1. **Call, subscript, attribute** (`()`, `[]`, `.`)
2. **Exponentiation** (`**`) - right-associative
3. **Unary prefix** (`+x`, `-x`, `~x`)
4. **Multiplicative** (`*`, `@`, `/`, `//`, `%`)
5. **Additive** (`+`, `-`)
6. **Bitwise shift** (`<<`, `>>`)
7. **Bitwise AND** (`&`)
8. **Bitwise XOR** (`^`)
9. **Bitwise OR** (`|`)
10. **Comparisons, membership, identity** (`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `is`)
11. **Boolean NOT** (`not`)
12. **Boolean AND** (`and`) - short-circuits
13. **Boolean OR** (`or`) - short-circuits
14. **Ternary** (`if`-`else`) - right-associative
15. **Walrus** (`:=`)

## Key Features

**Chaining:** All comparison operators can be chained, evaluating each intermediate value once: `"a < b < c"` is equivalent to `"(a < b) and (b < c)"`.

**Custom Type Support:** Developers implement dunder methods (forward, reversed, in-place) to enable operator overloading on custom structs for arithmetic, bitwise, unary, comparison, and subscript operations.

**Ownership Transfer:** The postfix `^` operator transfers value ownership: `"consume(a^)"` moves `a`'s value, leaving the variable uninitialized.

---

**Source:** https://docs.modular.com/mojo/reference/mojo-operators/
