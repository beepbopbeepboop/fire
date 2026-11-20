# Plan: Foreign-Callable Signature Table (tables.py / c_analyzer group)

Source bug: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Goal: make `c_common/tables.py`, `c_analyzer/__init__.py`, `c_common/fsutil.py` compile.

## Decomposition

Step 1 — Foreign-callable table (types.py)
  Create a module-level dict `_FOREIGN_CALLABLES: dict[str, str]` mapping a
  callable's qualified name to its `_CPP_CALLABLE_CTYPE`-family declared ctype.
  Seed with `csv.reader` -> `_CPP_CALLABLE_CTYPE` (iterator of list[str]).
  Files: mojo/middle/types.py
  Test: unit test that `_FOREIGN_CALLABLES.get('csv.reader')` is not None.

Step 2 — Bind default type in _infer_param_types (infra_infer.py)
  When a parameter has a default whose value is a name present in
  _FOREIGN_CALLABLES, bind the parameter's inferred type to that ctype
  instead of the int64_t fallback.
  Files: mojo/middle/infra_infer.py
  Test: a `def f(x, _g=csv.reader)` gets a callable-typed param in declared dump.

Step 3 — Admit default in _cpp_lambda_ctype (types.py)
  Currently returns None for any default. Admit a default whose value is a
  known foreign callable (table lookup).
  Files: mojo/middle/types.py
  Test: `_cpp_lambda_ctype` returns the table ctype for a lambda default.

Step 4 — _cpp_for_stmt branch for callable-local call (cpp_core.py)
  New branch after generator-handle branch: `for <target> in <call through
  callable local>` whose callee's table entry gives an iterator element ctype.
  Files: mojo/backend_gimple/cpp_core.py
  Test: cpp_for_over_callable_param_names_the_callee extended.

Step 5 — Element access + fix_row typing (cpp_core.py)
  Per-row accessor for the iterator element type; type-check fix_row body.
  Files: mojo/backend_gimple/cpp_core.py
  Test: read_table-like shape compiles past the for.

Step 6 — Flip refusal test to stdlib-output comparison
  Update _regression_read_table_callable_reader from refusal to comparison.
  Files: test_gimple_generator_runner.py

## Ordering
Steps 1-3 are independent of runtime work and can land first.
Steps 4-5 need a runtime iterator for csv.reader (separate project).
Step 6 last.
