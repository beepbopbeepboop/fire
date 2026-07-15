# Mojo Simple Statements Reference

## Overview
A simple statement performs a single action on one logical line. Multiple simple statements can share a line when separated by semicolons.

## Key Statement Types

**Import Statements**
These expose modules and members to current scope. Forms include:
- Module imports: `import math` or `import numpy as np`
- Selective imports: `from math import sqrt, pi`
- Wildcard imports: `from math import *`
- Multi-line selective imports (parenthesized): 
  ```mojo
  from module import (
      name1,
      name2,
      name3,
  )
  ```
  The opening `(` on the import line starts a multi-line import list that continues until the closing `)`. Names are separated by commas and can span multiple lines with optional trailing comma. Blank lines and indentation are ignored within the parentheses.

**Expression Statements**
These evaluate expressions for side effects. The compiler warns when results go unused, except for functions returning `None`. Use `_ = update()` to explicitly discard results.

**Assignment Statements**
Bind values to names using `=`. Type annotations are optional but recommended. Mojo supports:
- Simple assignment: `var x = 42`
- Annotated assignment with type specifications
- Multiple/destructuring assignment: `a, b = 1, 2`
- Augmented assignment operators: `+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `**=`, `@=`, `&=`, `|=`, `^=`, `<<=`, `>>=`

**Control Flow & Other Statements**
- `pass`: No-op placeholder for empty blocks
- `return`: Exits function, optionally returning a value
- `raise`: Raises errors (requires `raises` declaration or `try` block)
- `break`/`continue`: Loop control
- `comptime`: Declares compile-time constants and type aliases

---

**Source:** https://docs.modular.com/mojo/reference/mojo-simple-statements/
