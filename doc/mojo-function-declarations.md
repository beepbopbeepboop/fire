# Mojo Function Declarations Reference

## Core Structure

Every Mojo function begins with `def` and includes a name, parentheses, and a colon. The simplest form requires just these elements: `def do_nothing(): pass`

## Function Signatures

A complete signature incorporates several optional components:

- **Name**: Must be a valid identifier (keywords can be escaped with backticks)
- **Parameters**: Compile-time values in square brackets, appearing before arguments
- **Arguments**: Runtime values in parentheses, each requiring name and type annotations
- **Return Type**: Specified with `->`, omitted returns `None`
- **Body**: Code block executing when called

## Parameter and Argument Markers

Three markers control passing conventions:

**Infer-only (`//`)**: Parameters the compiler deduces from context. Cannot be specified positionally but allow keyword syntax like `[T=Int]`.

**Positional-only (`/`)**: Values callers must pass by position, rejecting named arguments.

**Keyword-only (`*`)**: Values requiring named passage. Multiple keyword-only items can mix required and optional freely.

## Argument Conventions

Conventions control value passing mechanics:

- **`mut`**: Mutable reference; caller's value modified
- **`var`**: Owned copy; caller's original unaffected
- **`out`**: Function's return slot, replacing `->` syntax
- **`deinit`**: Ownership transfer with destruction
- **`ref`**: Reference with optional origin tracking
- **Default**: Immutable borrow; caller retains ownership

## Variadic Arguments

**Homogeneous**: `*values: Int` accepts multiple same-type arguments.

**Packs**: `*args: *Ts` accepts mixed types through variadic pack parameters.

Restrictions: Maximum one `*args` per function; no default values; `out` cannot be variadic.

## Constraints

**Where clauses** restrict parameter values: `n: Int where (n == 1 or n == 2...)`. Can appear inline or end the declaration.

**Trait conformance** constrains types: `T: Copyable & Equatable` requires multiple trait satisfaction.

**Arguments cannot use where clauses**—only parameters allow this restriction.

## Special Methods

- **`__init__`**: Requires `out self` result
- **Copy constructor**: Single `copy` keyword-only argument
- **Move constructor**: Single `deinit take` keyword-only argument
- **`__del__`**: Destructor taking `deinit self`; cannot raise

## Additional Features

**Default values**: Once provided, all following parameters/arguments need defaults (except keyword-only items).

**Effects**: `raises` declares error capability, optionally specifying error type.

**Nested functions**: Automatically capture enclosing scope values.

**Static methods**: `@staticmethod` decorator enables type-level operations without instance.

---

**Source:** https://docs.modular.com/mojo/reference/mojo-function-declarations/
