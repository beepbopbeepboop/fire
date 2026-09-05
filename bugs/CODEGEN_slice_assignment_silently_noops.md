# CODEGEN: bounded/full slice-assignment (`x[a:b] = y`, `x[:] = y`) silently does nothing

## Symptom

An assignment whose target is a `SliceExpr` compiles cleanly and runs, but
the target container is never mutated — no error, no refusal, just a
silent no-op.

```mojo
def main():
    a = [1, 2, 3]
    a[0:2] = [7, 8]
    print(a[1])      # prints 2, should print 8

    b = [1, 2]
    b[:] = [9, 9]
    print(b[0])      # prints 1, should print 9
```

## Scope

Codegen-wide, NOT generator-specific — reproduces identically in an
ordinary top-level function via the plain GIMPLE path. Found 2026-09-05
while closing `bugs/hard/CODEGEN_generator_non_plain_assignment_target_
refused.md` (whose generator-eligibility-gate half is now resolved: the
A3 stack-switch path routes a generator body through ordinary codegen,
which handles self-field / subscript / tuple- and list-pattern-unpack
targets fine — only `SliceExpr` targets remain, and they are this
codegen-wide gap, not a generator gate issue).

## Root cause (not yet fixed)

`gimple_gen_stmts.py`'s `_gen_stmt_AssignStmt` has no `SliceExpr`-target
branch. The full-slice case (`x[:] = y`) could lower to the existing
`mojo_list_clear` + `mojo_list_extend` runtime helpers (real in-place
mutation, matching Python semantics). The bounded/stepped case
(`x[a:b] = y`, `x[::2] = y`) needs a real element-shifting splice
helper in `runtime/mojo_runtime.h`, which does not exist yet (only the
read-only `mojo_list_slice(l, start, stop)` copy helper).

Until then this should at minimum be an honest refusal, not a silent
no-op.
