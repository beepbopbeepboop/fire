# formal-call-proofgen is red on HEAD: 33 failures + 1 error, none in the x86 body-end change

## What was run

`python3 test_formal_call_proof_gen.py` (the registered `formal-call-proofgen`
job, not in the `gate` bucket) on the work branch, 2026-10-29:
`Ran 224 tests in 3450.442s`, `FAILED (failures=33, errors=1)`.

To separate pre-existing from new, the 26 failing test methods were rerun on a
copy of the worktree with the four changed `formal/` files restored to `HEAD`
(`git show HEAD:<file>`): `Ran 26 tests in 1828.513s`, `FAILED (failures=33)`.
Every one of the 33 failing cases fails identically on `HEAD`. The one
difference (`TestGeneratorSource.test_the_generated_mojo_is_declared_at_the_entry_arities_arity`,
an error on the work branch) was a regression of the work branch's own change
(a hand-built `info` fixture lacked the new `float_repr_addr` key) and is fixed
there; it passes.

## The pre-existing failures (all on HEAD)

Lean typechecks, guard emission and trap-list cases, by test method:

- `TestAComparisonWithTheImmediateOnTheLeft.test_both_spellings_elaborate` (left, right)
- `TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
- `TestAPlaceholderModelClaimsNothing.test_the_control_claims_all_four` (x86_64)
- `TestBottomTestedRangeLoop.test_it_is_refused_because_the_contract_would_be_false`
- `TestCompilerTrapIsNotAProgramCall` (three methods; x86_64 `plain`, `string`)
- `TestEntryArity.test_lean_accepts_the_two_parameter_proof_on_both_backends` (arm64)
- `TestExternCallTheRunDoesNotReach` (three methods; `print1` probe)
- `TestLean.test_generated_proofs_typecheck_with_no_sorries` (`no_params`, `print`)
- `TestSameImageCallLean.test_the_followed_call_proves_with_no_admission`
- `TestStringValueInTheModel` (two methods; arm64 `printf_literal`, `return_literal`)
- `TestTheBranchFlagLemmaIsTheBranchOwns.test_both_shapes_generate`
- `TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire` (two methods, arm64 and x86_64)
- `TestTheRecursionFamiliesStillGenerate.test_the_one_that_refuses_says_why` (`sum_range`)
- `TestTheRegisterValueReaderReadsEveryWrapper.test_the_epilogue_blocks_own_chain_states_what_it_wrote`
- `TestTheStackFloorGuardLeavesNoCallOnTheWalkedPath.test_the_div0_example_still_takes_the_run_test_path`
- `TestTheStackFloorGuardReadsTheLimitInTheStartupStub.test_either_has_a_value_theorem_and_the_read_is_in_the_stub`
- `TestTheZeroDivisorGuardAgainstLean` (four methods; `as_emitted`, `doc_next_step`)

## What is known and not known

Not diagnosed. These are Lean-side and guard-emission failures, not the decode
path. Whether they share one cause (the div0 and stack-floor guard cases are
the common thread) is unestablished.

## Next step

Pick one failing method (`TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire.test_a_variable_divisor_still_emits_its_guard`
is the smallest), run it on HEAD, read the first failing assertion, and decide
whether the guard emitter or the test's expectation is stale. Then the others
by the same reasoning.

## Status (2026-10-30)

The next step above was executed on HEAD, and the remaining failures were
clustered by the same reasoning.

**The smallest method: the test's expectation was stale, and it is fixed.**
`test_a_variable_divisor_still_emits_its_guard` failed `1 != 3` on both
backends. The guard emitter is right: a variable divisor emits exactly one
guard-exit call (arm64 `bl fflush` + raw `svc`, x86-64 `call exit`), a
literal divisor none. What changed is the image: since the float-repr helper
(commit `a2135f390`) is emitted unconditionally after every function body,
every image carries two extra `snprintf`/`strtod` calls, and `_calls` counted
the WHOLE image. The class's `_calls` now counts the guard's own exit call by
callee (arm64 `fflush`, x86_64 `exit`) — `TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire`
is 4/4 (was 2 methods / 4 subTests red). This also de-couples the class from
any future helper: the rows assert the guard's behaviour, not the image's
call census.

**The rest, by cluster, with the first reading of each:**

- **Cluster A — the extern-call census now includes the helper, so the
  run-test section and the reaches-call decision changed** (largest cluster:
  `TestTheStackFloorGuardLeavesNoCallOnTheWalkedPath.test_the_div0_example_
  still_takes_the_run_test_path`, `TestCompilerTrapIsNotAProgramCall` (3),
  `TestExternCallTheRunDoesNotReach` (3), `TestLean.test_generated_proofs_
  typecheck_with_no_sorries` (`no_params`, `print`), `TestEntryArity` (arm64),
  `TestSameImageCallLean`, `TestTheZeroDivisorGuardAgainstLean` (4), and the
  x86 half of `TestAPlaceholderModelClaimsNothing.test_the_control_claims_all_
  four` — the generated file now carries the `NO RUN TESTS` marker). Measured:
  `mod_by_var.mojo`'s proof now states `theorem mod_by_var_reaches_call_at_
  0x100000508` instead of `theorem mod_by_var_runs_…` — the walk halts at a
  call the run-test path used to treat as a compiler trap (`info
  ["compiler_traps"]`, the div0 `fflush`/`exit`), while x86-64's
  `_run_tests_section` refuses the whole run-test section for an image with
  ANY extern call, which is now every image (the helper's `snprintf`/
  `strtod`). Next: diff the `extern_calls`/`compiler_traps` the
  `mod_by_var` image publishes against the pre-helper shape, and find where
  the reaches-call plan outranks the run test; the x86 half needs the
  run-test refusal to ignore calls the emitter itself owns (the helper), the
  same subtraction `TestCompilerTrapIsNotAProgramCall` already records for the
  stack-floor trap.
- **Cluster B — the signed-condition refusal lost its reason** (`TestBottom
  TestedRangeLoop.test_it_is_refused_because_the_contract_would_be_false`,
  `TestTheRecursionFamiliesStillGenerate.test_the_one_that_refuses_says_why`
  on `sum_range`; both expect the refusal to name `SIGNED condition code 11`
  / `arm64_flag_lt_s` / `while_lt_exit_contract_bottom` / `FALSE`). Traced
  with `sys.settrace` on the generator: in the current `sum_range` image the
  countdown-shape discovery (`a b block whose target is a cbz block`) matches
  the print epilogue's byte-copy loop first (`b` at 0x1000005dc onto the cbz
  at 0x1000005cc; its terminator has no condition code), so `loop_check` is
  non-None. The bottom-tested search is guarded by `if loop_check is None:`,
  so it never runs; `_gen_countdown_loop` declines the epilogue cbz;
  `_loop_contract` stays `None`; the walk then refuses the real loop's back
  edge with the generic message (`_lc` is None, so `_why` is empty). Next:
  let the bottom-tested discovery run independently of the countdown hit (or
  fall back to it when `_gen_countdown_loop` declines), so the declined
  contract with `_range_declined` reaches the cbz arm's `_why`.
- **Cluster C — the x86 epilogue chain's `native_decide` is false** (`TestThe
  RegisterValueReaderReadsEveryWrapper.test_the_epilogue_blocks_own_chain_
  states_what_it_wrote`): `chain.lean:152` — the claimed equality of the
  epilogue block's exit run to `mojo 10` evaluates false on the `bitops`
  image; the chain concludes at a `sp + 8` read the value flow cannot close.
  Separate from A: the proof GENERATES and the machine runs; the statement is
  the thing that is false. Next: read the epilogue block's `x30` chain on the
  `bitops` image and find which write the reader's answer assumes.

