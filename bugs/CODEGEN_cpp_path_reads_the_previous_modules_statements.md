# CODEGEN_cpp_path_reads_the_previous_modules_statements: the C++ escape hatch decides from stale module state

Found 2026-11-01 while landing the per-kind specialization for a tagged generator
passed beside a list (`CODEGEN_a_tagged_generator_passed_to_a_function_is_refused`,
now fixed and deleted).

## What was run

`mojo/middle/coro.py` keeps the module being lowered in `_MODULE_STMTS`, and
`_tagged_consumers_ok(name)` reads that global whenever `module_stmts` is not
passed. `_MODULE_STMTS` is written only by `_register_generator_defs`, which runs
on the stack-switch path, AFTER `lower()`'s `if not enabled():` early return. So
on the `MOJO_CORO=cpp` path the global keeps whatever module was last lowered on
the stack-switch path (or by an earlier cpp-path call that reached it).

Reproduction (a short driver calling the two entry points in one process):

```python
gimple_codegen.compile_to_gimple_with_cpp(TWO, do_imports=False)   # stack-switch
with coro.pinned('cpp'):
    gimple_codegen.compile_to_gimple_with_cpp(MIXED, do_imports=False)
    print([getattr(s, 'name', None) for s in coro._MODULE_STMTS])
```

where `TWO` defines `g`, `inner`, `use`, `main` (and so, after the per-kind split,
`use__g` and `inner__g`), and `MIXED` is an unrelated module with `g`/`use`.

Measured: `coro._MODULE_STMTS` after the cpp compile is
`['g', 'inner', 'inner__g', 'use', 'use__g', 'main', None]`, the previous module,
not `MIXED`. The cpp compile of `MIXED` still succeeded, because the names it
consults happen to match.

## What was expected

The cpp path's decisions (`_generator_value_kind` -> `_tagged_consumers_ok`, reached
from `cpp_async.py`, `module_gen.py`, and `coro.py`'s own callers) should be made
from the module being lowered, the same as on the stack-switch path.

## Why it matters

A decision read from another module's statements can flip for a same-named
generator or callee: a `g` in the previous module with a different set of
consumers answers for this module's `g`. No wrong output has been observed yet.
It was not reproduced as a failure, only as a stale global.

## Exact next step

1. In `lower()`, on the `if not enabled():` branch, set the module before the
   early return: `_MODULE_STMTS[:] = list(stmts)` (or pass `stmts` through to
   `_tagged_consumers_ok` on the cpp path). Put it next to the existing
   `_scan_unthreadable_nested_async_gens` call, which already has the comment
   about the two backends sharing process state.
2. Regression test in `test_gimple_generator_runner.py`: compile a module whose
   `g` is refused by its consumers, then a cpp-path module with a same-named `g`
   whose consumers are boxed; the second must match CPython (or assert the cpp
   output directly). It must fail before step 1 and pass after.
3. Gate note for the integrator: the cpp path's output must stay byte-identical
   on the cpp-only tests, because the change only alters which module the
   decision reads.
