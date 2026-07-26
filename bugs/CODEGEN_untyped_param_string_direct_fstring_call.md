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

## Status
**Fixed**

Root cause was upstream of `8799ec4`'s "Pass 1.3e"/"Pass 1.3f"
re-inference: those passes and Pass 1.3d's cross-call scalar contract all
build their evidence by scanning real `CallExpr` AST nodes reachable from
statement trees (`_calls_in_stmts` → `_collect_calls`). An f-string
interpolation's `{expr}` is NOT such a node — it's raw source text kept
inside the `StringLiteral.value`, parsed fresh only at actual codegen
time by `_lower_StringLiteral`. So `g('a', 'b')` embedded directly inside
`f"result: {g('a', 'b')}"` was invisible to the call-site scanners
entirely; `g`'s param/return types stayed at the naive `int64_t` default
by the time `_lower_StringLiteral` looked them up, even after Pass 1.3e/
1.3f ran (there was no other call site to `g` anywhere in the program to
correct them from). The two-step `y = g(...); ...{y}...` shape worked
because `y = g(...)` is a genuine `AssignStmt.value` `CallExpr`, visible
to the same scan.

Fix (`gimple_codegen.py`): added `_fstring_sub_exprs`, which parses an
f-string `StringLiteral`'s `{expr}` interpolations into real AST nodes
using the same fresh-parse-from-text + `ast_rewriter.rewrite_node`
handling `_lower_StringLiteral` already does, and wired it into
`_collect_calls` (`StringLiteral` case added ahead of the existing
`CallExpr` branch) so any call embedded in an f-string interpolation is
now a call site the existing Pass 1.3d/1.3e/1.3f machinery already sees —
no new inference mechanism, per CLAUDE.md's consolidation guidance.

Regression test: `test_gimple_runner.py`'s
`gimple_untyped_param_string_direct_fstring_call` (behavioral, checks
actual compiled-binary stdout, not just exit code).

Verified: `python3 mojo.py build repro.py -o out && ./out` now prints
`result: ab` (was `result: 8682773656`). `8799ec4`'s own repro shapes
(two-step `y = g(...)` and the plain identity function) still print
correctly. `test_gimple.py` 186/186, `test_gimple_runner.py` 16/16,
`test_module_cache.py` 64/64, `make check-selfhost` clean, and a
from-scratch `build_stdlib_dylib.py` rebuild: 0 skips before and after.
