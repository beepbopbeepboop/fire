# A comprehension inside an `if` body loses its RESULT list's element type, so printing it gives pointer decimals

**Area:** CODEGEN (the container-element-type inference for a function's
RETURN value). Found 2026-10-01 on `work/bugs3-codegen-2-r2` while fixing
`bugs/CODEGEN_comprehension_target_shadows_struct_local.md`, by writing the
first user-level reproducer for that bug. **Not fixed there** — it is a
different loss (the comprehension's own *result*, not its *loop target*) and
it is in the whole-program inference pass rather than in the comprehension
lowering.

## What I ran and what it showed

```
$ cat .tmp/compr/c5.mojo
def a1():
    return [t for t in ["a", "b"]]
def a2(i):
    if i:
        return [t for t in ["a", "b"]]
    return []
def a3(i):
    if i:
        x = [t for t in ["a", "b"]]
        return x
    return []
def a5(i):
    r = []
    if i:
        r = [t for t in ["a", "b"]]
    return r
def a6(i):
    if i:
        return [t for t in ["a", "b"]]
    else:
        return []
def main():
    print(a1())
    print(a2(1))
    print(a3(1))
    print(a5(1))
    print(a6(1))

$ python3 .tmp/compr/c5.py      # CPython 3.14, main() appended
['a', 'b']
['a', 'b']
['a', 'b']
['a', 'b']
['a', 'b']

$ python3 fire.py --jit .tmp/compr/c5.mojo
['a', 'b']
[4377187560, 4377187568]        <-- a2
[4377187560, 4377187568]        <-- a3
['a', 'b']                      <-- a5, CORRECT
[4377187560, 4377187568]        <-- a6
```

The interpreter is right on all five. Exit 0, no diagnostic.

## The narrow shape, which is the useful part

Three separate variables, and the discriminator is NOT "is the
comprehension in a branch":

| case | comprehension's result | compiled |
|---|---|---|
| `a1` | `return <compr>` at function top level | correct |
| `a2` | `return <compr>` inside `if` | **pointer decimals** |
| `a6` | `return <compr>` inside `if` / `else` | **pointer decimals** |
| `a3` | `x = <compr>` inside `if`, then `return x` | **pointer decimals** |
| `a5` | `r = []` first, then `r = <compr>` inside `if`, then `return r` | **correct** |

`a5` is the one that says what is going on: when the returned NAME is already
live, the element type reaches the print through the LOCAL's own type
(`_infer_local_var_types` / the local's `_elem_types` entry), and the branch
does not matter. When the comprehension's result is what flows into the return
— directly (`a2`, `a6`) or through a fresh `x` (`a3`) — the return-element
inference is what has to know, and it does not.

So the missing step is in `mojo/middle/resolve_shared.py`'s
`_infer_return_elem_type` (`:888`): its ReturnStmt element walk does not reach
a comprehension nested inside an `IfStmt` body, so the function's registered
return element type is `None` and `_elem_of` on the caller's `a2(1)` result
falls back to `int64_t`. `a1` works because the comprehension is the
function's whole body.

## Why it is worth its own doc rather than a line in the target-shadowing fix

It is a different layer. The comprehension target fix is a local change in
`mojo/backend_gimple/emit_infra.py::_compr_list_loop` — one missing
`force=` argument. This one is in the whole-program hermetic inference pass
that decides what a function returns, which is a deliberate, carefully-tuned
scan (`_infer_return_elem_type`'s docstring documents its own 153,580-call
cost and its hermetic-scratch design), and its ReturnStmt walk has to learn to
descend into `IfStmt` / `WhileStmt` / `TryStmt` bodies without either losing
hermeticity or becoming quadratic. That is not a change to make as a
drive-by beside an unrelated one.

## Exact next step

In `_infer_return_elem_type`, extend the ReturnStmt element walk's node
iteration to descend into nested statement BODIES — `IfStmt.then_body`,
each `elifs` arm, `else_body`; `WhileStmt.body`; `WithStmt.body`;
`TryStmt.body` / `handlers[i].body` / `else_body` / `finally_body`;
`ForStmt.body` — the same body set `mojo/middle/types.py`'s
`_declared_vars_body` already enumerates, so the two should be reviewed
together rather than a third variant of "walk a statement list" being written.

The cheap first experiment, which is how the table above should be read:
confirm that a comprehension in a `while` body and one in a `for` body are
affected the same way as the `if`, and that a `return` at the END of a
function (after the `if`) is unaffected. If the `while`/`for` cases are
already correct, the walk is partially recursive and the gap is narrower than
"does not descend", which is worth knowing before touching it.

Verify with a `test_runtime_diff.py` case CPython can also run: one function
per nesting shape, all printing their result, so each line is one question.
`test_gimple.py` is the wrong home — the shape COMPILES, and the defect is
only visible in what the result prints as.

## Evidence

- The table above, from `.tmp/compr/c5.mojo` (5 functions, 5 answers) run
  through `fire.py --jit` and through CPython 3.14 on the same text.
- `mojo/middle/resolve_shared.py:888` (`_infer_return_elem_type`) and its
  callers `mojo/backend_gimple/module_gen.py:4587` and `:4601`.
- `mojo/middle/types.py::_declared_vars_body` for the body-set enumeration to
  copy.
