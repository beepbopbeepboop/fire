# CODEGEN_cpp_path_reads_stale_generator_registry: the cpp escape hatch reads the previous module's generator registry

Found 2026-11-01 while fixing the stale `_MODULE_STMTS` read on the cpp path (the
cpp branch of `coro.lower()` judged a module against the previous module's
statements; fixed by refreshing `_MODULE_STMTS` there). The sibling registries
populated by `_register_generator_defs` were NOT touched, and that function runs
only on the stack-switch path.

## What was read

`_register_generator_defs` (mojo/middle/coro.py) clears and refills:
`_GEN_DEFS`, `_GEN_VALUE_KINDS`, `_GEN_RESOLVING`, `_LIST_RET_KINDS`,
`_PTR_RET_KINDS`, `_GEN_REC_ASSUME`, and the pointer-evidence tables. The cpp
branch of `lower()` returns before it, so on `MOJO_CORO=cpp` these keep the values
of the last module lowered on the stack-switch path.

Readers reached from the cpp path:
- `_static_env`'s generator-call branch (about coro.py:279-300) checks
  `n.value.func.name in _GEN_DEFS` and `_GEN_VALUE_KINDS.get(g)`.
- `_generator_value_kind` -> `_static_env` (cpp_async.py:1136 calls it directly).
- `_sibling_gen_kind` / the resolver (about coro.py:2040-2174) answers from
  `_GEN_DEFS` and `_GEN_VALUE_KINDS`.

## What was NOT observed

Not reproduced. This was found by reading the code, not by a failing compile. The
analogous `_MODULE_STMTS` case did reproduce (`test_gimple_generator_runner.py`,
`cpp_path_ignores_previous_module_state`).

## Exact next step

1. Write a repro in the same shape as the `_MODULE_STMTS` test: a stack-switch
   module `B` defining a generator `h`, then a cpp-path module `A` that calls a
   same-named non-generator `h` (or a generator whose kind differs), and check
   whether `A`'s output matches CPython. If it does not, the stale read is real.
2. Fix it in the same place as the `_MODULE_STMTS` line: the cpp branch of
   `lower()`. Do NOT simply call `_register_generator_defs` there; it also
   fills `_GEN_VALUE_KINDS` and the ret-kind tables, which the cpp path does not
   expect, and that changes its output. Split out the `_GEN_DEFS` population
   (a pure function of `stmts`) and run that alone on both paths, and clear the
   memo on the cpp path too.
3. Gate note: the cpp-only tests must stay byte-identical before and after.
