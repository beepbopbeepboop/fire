# `for x in f(...)` where `f` RETURNS a generator (it is not one) compiles to `mojo_unsupported_iter`

Class: medium. One lowering path. Three sites in the compiler's own
`myinterpreter.py` hit it.

## Symptom

`myinterpreter.py` (near lines 8473, 8501 and 10380):

    for value in _mojo_iter(iterable):
        ...

`_mojo_iter` (near line 5191) is an ordinary function, not a generator: it
returns a generator on one path (`return _mojo_struct_iter_steps(...)`) and
`iter(value)` on another. Its return type is inferred as a generator handle. The
compiled loop is:

    _t58 = _mojo_iter_9f63a2 (iterable);
    _t59 = _slit_10947;          /* "myinterpreter.py:8473: MojoGenerator *" */
    mojo_unsupported_iter (_t59);

so the self-hosted interpreter refuses every such `for` at run time.

Reproduce, from an empty directory outside the tree:

    python3 /path/to/tree/fire.py --dump /path/to/tree/myinterpreter.py
    grep -n -A2 '_mojo_iter_[0-9a-f]* (iterable)' myinterpreter.ci

## History (why this is new on 2026-11-16)

Until 2026-11-16 the loop compiled to something worse. The table
`gen._generator_var_api` (temp name -> the resume/value/destroy functions of
the generator it holds) was never emptied between functions. This call's
result temp is `_t58`, and an EARLIER function had a `_t58` that held an
`_ast_nodes` generator, so the loop was emitted as

    _t59 = __mgco__ast_nodes_resume (_t58);
    _t60 = __mgco__ast_nodes_value (_t58);

that is, it resumed `_mojo_iter`'s handle with a different generator's
resume function. `_reset_func` now empties the table, and the loop reports
what is true: the backend does not know which generator the handle is.

## Cause

The for-loop lowering finds the API of a `MojoGenerator *` value in
`gen._generator_var_api[<temp>]`. That entry is written where a generator
is CONSTRUCTED (`mojo/backend_gimple/emit_calls.py`, the `_generator_var_api[t] = api`
sites). A call to a plain function that returns a generator built
somewhere else writes no entry.

## Fix

A `MojoGenerator *` whose API is not known statically must be driven
through the handle itself. The runtime already has the entry points for a
handle of unknown generator (`__mojo_gen_resume`, `__mojo_gen_destroy`; see
their uses in `mojo/backend_gimple/emit_methods.py`). In the for-loop
lowering (search `mojo_unsupported_iter` in
`mojo/backend_gimple/emit_loops.py` and `emit_infra.py`), when the iterable's
type is `MojoGenerator *` and `gen._generator_var_api` has no entry for it,
emit the handle-driven loop instead of `mojo_unsupported_iter`.

Do NOT fix it by making `_generator_var_api` survive across functions
again. `test_gimple_lint.py` (`value tables`) fails if a table that
`carry_value_info` copies is not reset per function.

## How to verify

1. Add to `test_gimple_runner.py` (compare with CPython; measured
   2026-11-16: both loops compile to `mojo_unsupported_iter`):

       def count(n):
           i = 0
           while i < n:
               yield i
               i += 1
       def make(v):
           if isinstance(v, int):
               return count(v)
           return iter(v)
       def main():
           for x in make(3):
               print(x)
           for y in make([7, 8]):
               print(y)
       main()

   A function with ONE `return count(n)` is already handled (the callee is
   known to return that generator); the failing shape returns a generator
   on one path and something else on another, which is `_mojo_iter`'s shape.
2. The `grep` above shows no `mojo_unsupported_iter` after the three calls.
3. `python3 test_gimple.py` keeps its pass count with 0 failed;
   `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` passes.

## Done when

The three `myinterpreter.py` loops compile to a real loop, the new test
passes, and this file is deleted in the same commit (then
`python3 tools/dangling_doc_refs.py --ratchet`).
