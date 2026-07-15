# Mojo Compound Statements Reference

## Overview

Compound statements feature a header ending with `:` followed by an indented body containing simple statements, other compound statements, or both. The body's indentation is set by the first statement.

## Control Flow Statements

### If Statements
"An `if` statement executes a block conditionally" with support for `elif` and `else` clauses. Conditions are evaluated sequentially, executing the first true branch. Single-line syntax is possible but discouraged: `if x > 0: print("positive")`

### While Loops
The `while` construct repeats its body while a condition remains true. Use `break` to exit early or `continue` to skip iterations.

### For Loops
For loops iterate over sequences requiring `__iter__()` and `__next__()` implementations. The syntax supports destructuring: "Destructuring works directly in the loop target. This lets you unpack tuple elements as you iterate."

### Loop Else Clauses
An optional `else` clause executes when loops exit normally (condition becomes false), but not when `break` is used.

## Error Handling

The `try` statement requires at least one `except` or `finally` clause. Execution order: try block → except block (if error) → else block (if no error) → finally block (always).

Error binding captures exceptions: `except e:` binds the error to variable `e`. Without binding, errors are caught silently.

"When a function declares a specific error type with `raises ErrorType`, the bound variable's type is inferred."

## Context Managers

The `with` statement manages resources via `__enter__()` and `__exit__()` methods. "The cleanup always runs when the block exits, even if an error occurs." Multiple managers share one statement: `with open(...) as f_in, open(...) as f_out:`

## Compile-Time Control Flow

**comptime if**: Selects branches at compile time, pruning unselected ones. Conditions must be compile-time expressions.

**comptime for**: "Unrolls a loop at compile time. Each iteration is compiled as separate code," creating larger binaries with improved performance.

## Scoping

Each compound body creates a new scope. Variables declared inside aren't accessible outside. "Nested functions create their own scope and can capture variables from enclosing functions with the `capturing` keyword."

---

**Source:** https://docs.modular.com/mojo/reference/mojo-compound-statements/
