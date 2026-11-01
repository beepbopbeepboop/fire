# CODEGEN_cpp_path_reads_stale_generator_registry: the cpp escape hatch reads the previous module's generator registry

## Status (2026-11-01): PARTIAL — the registry index and the pointer-evidence tables are refreshed on the cpp path

Reproduced (it was "found by reading" before). The cpp branch of `lower()` now
calls `_index_generator_defs(stmts)` (the pure `_GEN_DEFS` population split out of
`_register_generator_defs`) and `_compute_pointer_evidence(stmts)`, and clears
`_GEN_VALUE_KINDS`, `_GEN_RESOLVING`, `_LIST_RET_KINDS`, `_PTR_RET_KINDS`. Repro:
previous module `def h(): yield 2.5` (stack-switch), then a cpp-path module whose
plain `def h(): return ["p", "q"]` is consumed by `for v in h()` inside generator
`g`. Before: refused ("a `yield` of a float value is typed 'char *'"). After:
compiles, output identical to the same module compiled fresh.
Regression test: `cpp_path_ignores_previous_generator_registry`
(`test_gimple_generator_runner.py`), fails before, passes after. Runner file
430 passed 0 failed. Generated cpp for four cpp-only programs is byte-identical.

REMAINING (still stale on the cpp path):
- `_GEN_REC_ASSUME` (filled from `_static_env`/`_yield_kind` in
  `_register_generator_defs`, so not a pure function of `stmts`; needs the
  call-site tables below to be current first).
- `_CALLSITE_PARAM_KINDS` and `_PLAIN_CALLSITE_PARAM_KINDS` are cleared only inside
  `_scan_callsite_param_kinds`, which only the stack-switch path runs. The cpp
  path never clears them, so they carry the previous module's call-site kinds.
  Observed in one process: stack-switch compile of `D4` then cpp compile of `D4`
  gives a refusal (`typed 'int64_t'`), while cpp-only gives a silent `2`. Two
  different wrong answers for one source, depending on what ran before.
  Next step: decide whether the cpp path should run the call-site scan (it reads
  `closure_stmts`, so it needs the same arguments) or clear and refill those tables
  from `stmts` alone. Then move `_GEN_REC_ASSUME` behind it.
- Separate silent bug (float call in generator truncated on cpp path):
  a fresh cpp-only compile of `y = h()` (plain `h` returning 2.5) prints `2`.


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
