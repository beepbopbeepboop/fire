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
