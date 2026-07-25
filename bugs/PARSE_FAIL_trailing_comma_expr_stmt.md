# PARSE_FAIL: a bare expression statement with a trailing comma fails to parse

## Status
Fixed (2026-07-25).

`mojo_compiler.py`'s statement parser (the branch starting at
`if self._peek().kind == "COMMA":`, right after `expr = self._parse_expr(0)`
for a bare statement) collected a comma-separated `first_group` but, on
seeing a comma, unconditionally tried to parse another expression after it —
there was no check for a trailing comma with nothing meaningful following
(NEWLINE/DEDENT/EOF/SEMICOLON), unlike the sibling chained-assignment-RHS
loop a few lines below which already had that check. So `print(1),` advanced
past the comma and tried to parse an expression starting at the NEWLINE
token, producing `SyntaxError: Unexpected NEWLINE('')`.

Fix: added the same terminator check to this loop (break instead of trying
to parse), and introduced a `saw_comma` flag (set whenever the COMMA branch
is entered) so a *single* trailing comma after one expression
(`first_group` staying length-1) still produces a 1-element `TupleExpr` —
previously the downstream `if len(first_group) > 1:` check that decides
"wrap in TupleExpr vs. treat as plain expression" would have suppressed
tuple-wrapping in exactly this case, silently dropping the trailing comma's
Python semantics (constructing a discarded 1-tuple) instead of raising or
mishandling it.

Verified:
- Repro (`print(1),` followed by `print("done")`) now runs, prints `1` then
  `done`.
- No-comma bare expression statement (the overwhelmingly common case)
  unaffected.
- Multi-element trailing-comma statement (`1, 2,`) and non-trailing bare
  tuple (`1, 2`) both parse and execute without incident — no visible side
  effect from constructing-then-discarding the tuple.
- `python3 test_gimple.py`: 161 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes (mojo.py compiling its own source, 1
  passed, 0 failed).
- From-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(jobs=8)`): 0 `skip <module>:` lines
  both before and after the fix (checked by stashing the change and
  rebuilding clean for the baseline) — no regression.

## Reproduction
```mojo
def f():
    print(1),
    print("done")
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:2:0: Unexpected NEWLINE('')
```
(reported at the line AFTER the trailing comma — the parser consumed
`print(1)` fine, then apparently choked trying to continue parsing after
the trailing `,`.)

## Expected Behavior
`EXPR,` at statement level is valid (if unusual) Python: a trailing comma
after a single expression makes the whole statement a **1-element tuple
literal expression statement** (equivalent to `(EXPR,)` — the tuple is
constructed and then immediately discarded, since it's not assigned to
anything). This is almost always an accidental typo in real code (a
leftover comma from converting a multi-arg call into a single statement, or
similar), but it's syntactically 100% legal Python and must not be a parse
error. This project has already fixed several close relatives of this exact
"bare trailing/interior comma makes an implicit tuple" pattern today
(`PARSE_FAIL_implicit_tuple_assignment.md`'s RHS-of-`=` case,
`PARSE_FAIL_chained_assign_with_tuple_target.md`'s target case,
`for x in a, b, c:`'s bare-tuple-iterable case) — this is the same
underlying grammar rule, just for a plain (non-assignment) expression
statement.

## Real-world impact
Confirmed via real CPython 3.14 stdlib source: `Lib/test/test_itertools.py:954-955`:
```python
self.assertEqual(list(pairwise('ab')),
                      [('a', 'b')]),
```
(a trailing comma left after `self.assertEqual(...)`, almost certainly an
accidental artifact of the test's own multi-line formatting, but real,
unmodified CPython source nonetheless).

## Files Likely Affected
- `mojo_compiler.py` — wherever a plain expression statement
  (`ExprStmt`) is parsed (after `expr = self._parse_expr(0)`, before/instead
  of expecting a statement terminator). Check for a trailing `COMMA` the
  same way the plain-assignment RHS tuple-collection fix already does, and
  wrap the expression (plus any further comma-separated expressions, for
  full generality — `EXPR1, EXPR2,` is also valid, though the real-world
  motivating case here only needs a single trailing comma after one
  expression) into a `TupleExpr` if a comma follows. Reuse whatever
  tuple-collection helper/pattern the earlier implicit-tuple fixes already
  established rather than writing new logic.
- `myinterpreter.py` — verify executing a bare `ExprStmt` whose value is a
  `TupleExpr` already works correctly (evaluate and discard) — this is
  likely already fine since it's the same AST shape any other tuple
  expression produces, just double-check once the parser change lands.
