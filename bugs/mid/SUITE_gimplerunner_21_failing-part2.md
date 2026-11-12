# SUITE_gimplerunner_21_failing-part2: generator codegen for for-over-call and check-all idiom

## Status (2026-11-12): measured, not fixed; a plan for the next round

Measured on this tree (not inferred):
- The refusal is the companion-.cpp one. `test_gimple_runner.py` calls `compile_to_gimple`,
  which cannot return the C++20 companion. `compile_to_gimple_with_cpp` does return it: for the
  `gimple_check_all_idiom` program it emits a 13204-byte `.cpp` beside a 45828-byte `.ci`.
- `fire.py build` on that program (scratch copy, same source) builds `checkall.exe` and it runs
  without crashing, so the coroutine translation itself links and resumes.
- The output is WRONG. CPython: `2 big / 3 big / 2 big / None None` style lines with the string
  tag. Compiled: the failure string prints as a pointer decimal (`2 4308203864`), and the failfast
  run prints `None None` where the second line should be `2 big`.
  The cause is the yield tuple's element kinds: a generator yielding `(x, None)` and `(x, "big")`
  is a mixed-kind tuple, and the consumer's `for d, f in gen` reads slot 1 as an int.

Plan (next round, in this order):
1. Make the generator value typing kind-aware at the consumer: the tuple target of a loop over
   a generator call takes per-slot kinds from the yield sites (the same `_struct_slot_kinds` /
   `_maybe_kinds_vals` machinery the list and dict fixes use), not a single int64 word.
   Test: `checkall.mojo` printed by `fire.py build` must equal CPython line for line.
2. Only then change the harness: `compile_mojo_to_gimple_exe` must build the companion the way
   `fire.py build_executable` does (compile the `.cpp` with the coroutine flags, link it). Doing
   the harness first would turn a clear refusal into a wrong answer that passes, which is the
   failure mode this file exists to prevent.
3. Cost note: `fire.py build` takes about two minutes per program (the stdlib dylib closure),
   so the harness change must reuse a single build, not one per case.


Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group B, subset).

## Goal

Implement or lower the generator/coroutine codegen needed so the following `test_gimple_runner.py` cases compile and run instead of being refused with C++20 generator symbols:
- `gimple_for_over_a_call_through_a_function_value`
- `gimple_check_all_idiom`

## Acceptance

- `gimple_for_over_a_call_through_a_function_value` compiles and its stdout matches the test's expected output.
- `gimple_check_all_idiom` compiles and its stdout/result matches the test's expected behavior.
- No `gcc -fgimple compilation failed` refusal caused by missing generator lowering for these shapes.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part2.log; ! grep -q '^FAIL  gimple_for_over_a_call_through_a_function_value' .tmp/SUITE_gimplerunner_21_failing-part2.log`

The command exits 0 when `gimple_for_over_a_call_through_a_function_value` no longer fails.
