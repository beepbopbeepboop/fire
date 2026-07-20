# INTERP: `var name = a, b, c` (bare tuple RHS) fails to parse under `var`

## Status
**Fixed** (2026-07-20)

## Fix
`mojo_compiler.py`'s `_parse_var_decl` (the single-name `var`/`let` declaration
path, distinct from both the tuple-unpacking-names branch above it and the
plain-assignment `AssignStmt` path in `_parse_stmt`) never checked for a
trailing comma after parsing the RHS expression. Added the same
bare-comma-RHS-becomes-`TupleExpr` collection loop used by the plain-assignment
path (`_parse_stmt`'s `ASSIGN` branch) and by the existing `var a, b = x, y`
tuple-unpacking branch, right after `value = self._parse_expr(0)` in the
single-name `ASSIGN` case. `var name = 'a', 'b', 'c'` (and the typed form
`var t: T = a, b, c`) now parse to `VarDecl(value=TupleExpr(...))`, matching
the plain-assignment behavior.

_(original report below)_
**Open** (found 2026-07-20, re-testing the backlog for still-live interpreter bugs)

## Reproduction
```mojo
def f():
    var name = 'a', 'b', 'c'
    print(name[0])
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:2:14: Unexpected COMMA(',')
```

## Expected Behavior
Should behave like Python's implicit tuple assignment: `var name = ('a', 'b', 'c')`.

## Root Cause / Relationship to prior work
`PARSE_FAIL_implicit_tuple_assignment.md` (this same directory) documents this
exact syntax as "Fixed (2026-07-15)" — and it genuinely is fixed for **plain**
assignment (`name = 'a', 'b', 'c'` parses and runs fine today). But Mojo's own
`var`/`let` declaration-statement is parsed by a different code path in
`mojo_compiler.py`'s `_parse_stmt` (the `var`/`let` branch, not the bare-NAME
assignment branch), and that path never got the same bare-comma-tuple-RHS
handling. Since `var` is the idiomatic Mojo way to declare a variable (used
throughout this codebase's own test files and the stdlib), this gap is more
impactful than the original (Python-style, no `var`) report.

## Files Likely Affected
- `mojo_compiler.py` — the `var`/`let` declaration parsing branch in `_parse_stmt`
  (search near where the plain-assignment fix was made per
  `PARSE_FAIL_implicit_tuple_assignment.md`, and reuse the same TupleExpr-collection
  logic for the `var` branch's RHS).
