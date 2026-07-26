# CODEGEN: calling an untyped string-passthrough function DIRECTLY inside an f-string interpolation still produces garbage

## Repro

```python
def g(a, b):
    return a + b
print(f"result: {g('a', 'b')}")
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints
  `result: ab`.
- `python3 mojo.py build repro.py -o out && ./out`: prints a garbage
  integer, e.g. `result: 8682773656`.

## Relationship to the just-fixed sibling bug

This is a narrower remaining gap in the same bug family as
`bugs/CODEGEN_untyped_param_string_passthrough_wrong.md` (fixed in commit
`8799ec4`). That fix correctly handles the two-step shape:

```python
def g(a, b):
    return a + b
y = g("a", "b")
print(f"result: {y}")     # now correct after 8799ec4: "result: ab"
```

But calling `g(...)` DIRECTLY inside the f-string's `{...}` interpolation
expression, with no intermediate variable assignment, still produces
garbage — confirmed as a distinct remaining case immediately after
verifying `8799ec4`'s fix landed. The `y = g(...)` assignment case now
goes through `AssignStmt`'s corrected local-variable-type handling
(per `8799ec4`'s summary, `AssignStmt`'s "trust the actually-lowered
value's type over a stale pre-pass hint" rule was generalized to any
pointer type) — but an f-string interpolation expression's inline call
apparently doesn't route through that same corrected path, or hits a
different, still-`int64_t`-defaulting assumption specific to how
interpolation expressions are lowered/formatted.

## Suggested fix

Investigate how `gimple_codegen.py` lowers an f-string interpolation's
`{expr}` sub-expression specifically (as opposed to an ordinary
`AssignStmt`'s right-hand side) — find wherever it decides how to format/
convert the interpolated expression's value for insertion into the
resulting string (likely calling some `_mojo_repr`/format helper keyed off
an assumed or inferred type), and check whether it's using a stale/default
type instead of the same corrected type information `8799ec4` now
threads through for other consumers (`func_return_types`,
`_infer_local_var_types`, etc.). This may be as simple as making sure the
interpolation-expression lowering path also runs after (or consults the
same corrected state as) `8799ec4`'s new "Pass 1.3e"/"Pass 1.3f"
re-inference passes, rather than needing a fourth, separate mechanism —
check for consolidation opportunities per CLAUDE.md before adding
anything new.
