# CODEGEN_generator_runner_70_fails_empty_output: 70 cases in test_gimple_generator_runner.py print nothing

## Status (2026-11-01, OPEN — cause not identified)

Found while landing the `yield from` `_resume`-first-step fix (commit f05457811).
`python3 test_gimple_generator_runner.py` reports **70 FAIL** on the tree BEFORE
that commit (`git archive HEAD~1`, run from a copy) and the **same 70** after it.
The failure sets are byte-identical (`diff` of the sorted FAIL names is empty),
and PASS is 372 in both runs. So this is pre-existing and not caused by the
`yield from` change. Most failures are `expected '...', got ''`, i.e. the compiled
program produced no stdout at all.

Examples (both trees): `generator_yield_from_same_kind_string`,
`generator_mixed_yield_kinds_yield_from_str_int`, `generator_next_method_string_values`,
`star_args_coroutine_await_packs`, `kwonly_default_literal_still_accepted`,
`cpp_path_float_call_in_generator_yields_as_double`.

## What is known

- The runner does not print the compiler's stderr for most of these. Only one
  g++ error line surfaces in the whole log:
  `prog_gen.cpp:456:37: error: invalid conversion from 'int64_t' to 'MojoList*'`.
  That is one data point, not the explanation for the 70.
- The failing cases are mostly string- and float-yielding generators and
  `*args` / keyword-only shapes. Integer `yield from` shapes pass.

## Next step

1. Pick ONE failing case, e.g. `generator_yield_from_same_kind_string`, and
   reproduce it outside the runner: take its program text from
   `test_gimple_generator_runner.py`, build it with `_build_generator_program`,
   and capture the build's stderr and the exit status of the run.
2. Decide whether it is a real codegen bug (a wrong C type on the string path)
   or a harness problem (the program is built but run from the wrong place, or
   the runner discards the compiler's output). The stderr from step 1 decides it.
3. If it is a runner harness problem, make `test_generator_stdout` report the
   build's stderr on failure. Then re-run and file one doc per real root cause.

## Quick test

`python3 test_gimple_generator_runner.py` shows the same 70 FAILs as
before. The doc is deleted when those cases PASS, or when each one has a
per-root-cause doc and its own `expect=`/fix.
