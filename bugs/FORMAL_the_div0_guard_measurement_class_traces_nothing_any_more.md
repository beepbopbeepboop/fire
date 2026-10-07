# FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more

**Area:** FORMAL, the arm64 proof generator's own doc-truth test.
`test_formal_call_proof_gen.py::TestTheZeroDivisorGuardAgainstLean`
(`test_the_false_goal_survives_the_documented_next_step`,
`test_the_residual_is_the_same_with_and_without_the_branch_fact`).

**Status: OPEN, diagnosed, not fixed. Pre-existing on this tree — verified by
reverse-applying the `formal/arm64_codegen.py` +
`formal/arm64_proof_gen.py` diff of the branch that found it and re-running the
class: 3 failures before, 3 failures after, identical messages.**

**Re-measured 2026-10-07 (`work/formal115-docs`), and the SYMPTOM has moved
again — the class no longer fails its assertions, it cannot even build its
fixture.** `_symbolic_divisor_proof` calls `compile_formal(..., prove=True,
check=False)`, and on this tree that RAISES `FormalBuildError` in `setUpClass`:

    universal theorem: 2 calls this walk cannot follow
    (0x10000041c -> 0x100000890 (opaque), 0x100000518 -> 0x100000884 (opaque)),
    every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge them.

The two calls are the compiler's, not the program's: `0x10000041c` is the
prologue's stack-floor `getrlimit` and `0x100000518` is the divide-by-zero arm's
`fflush`. **So the class's `setUpClass` errors on any tree with
`lib/ProofLib.olean` and skips on one without**, which is why a doc-truth class
about a residual goal has not reported a goal in two rounds: it is not measuring
the wrong thing, it is not getting a proof file to measure at all.

This section's own diagnosis (§"Why it went blind") is the upstream half and it
is right: `_unfollowable_calls` does not subtract `info["compiler_traps"]`. What
is new, and what blocks the fix this doc wants, is that (a) on master arm64's
`compiler_traps` list is EMPTY because the emitter recording was dropped by a
merge (`8df5b273`; the EMITTER half is landed again on `work/formal115-docs`,
see
`bugs/FORMAL_arm64_the_compiler_trap_recording_is_lost_and_the_stack_guards_getrlimit_is_a_program_call.md`),
so on master there is nothing to subtract, and (b) subtracting it is measured NOT to reach
the div0 residual: with the recording restored and the traps filtered out of
`_unfollowable_calls`, `q(a,b)` moves to a THIRD refusal (`recursion contract: the
call in block 2 has to be below the source condition's negation`), not to the
`⊢ 1 = …` goal. The next step this doc states (option 1, "subtract
`compiler_traps` in `_unfollowable_calls`") is therefore necessary and not
sufficient; the walk needs a terminal for a call it cannot follow, which is
`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`.
Option 2 (a literal-divisor fixture) remains the only cheap way to make the class
GREEN, and it changes what the class measures.

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean
    FAIL: test_the_false_goal_survives_the_documented_next_step (spelling='as_emitted')
    FAIL: test_the_false_goal_survives_the_documented_next_step (spelling='doc_next_step')
    FAIL: test_the_residual_is_the_same_with_and_without_the_branch_fact
    Ran 2 tests in 30.536s
    FAILED (failures=3)

## What was seen, and why the diagnosis the test gives is wrong

The failure text is

    AssertionError: '⊢ 1 =' not found in 'div0_doc_next_step.lean:29:8:
    warning: declaration uses `sorry` … ' : doc_next_step: the div0 path's
    residual is no longer the `1 = …` goal — fdiv64's div0 arm or the div0
    path's exit status may have been corrected, which is the fix this doc wants

which is a **false diagnosis**, and the class's own second assertion says so if
you read it: `"no residual goal was traced at all, so the measurement this
class exists for did not happen"`.

The mechanism, step by step:

1. `_symbolic_divisor_proof` compiles `def q(a, b): return a // b` and splits
   the generated file at `"theorem q_compiles_correctly_universal"`.
2. **That theorem is no longer emitted.** Measured on this tree, the generated
   file has 234 theorems, **zero** of them matching `compiles_correctly`, **zero**
   `sorry`, and this line:

       /- CALL BOUNDARY.  This function calls out of the image: the `BL` at
          0x100000474 branches to 0x100000498, which is not in the code the
          model was given …

   `0x100000474` is `_emit_div_shift_pow`'s divide-by-zero arm — the same
   `BL fflush` that `formal/arm64_proof_gen.py::_program_extern_calls` now
   subtracts from the CONCRETE run tests. The UNIVERSAL theorem's path,
   `_unfollowable_calls`, scans raw code bytes and does **not** subtract
   `info["compiler_traps"]`, so it still sees that flush as a call it cannot
   follow and the program is left with `q_reaches_call_at_0x100000474` and
   nothing else.
3. So `text.partition(...)` puts the WHOLE file in `head`, `tail` is `""`, and
   `tail.replace(_ADMIT, _TRACE)` is a **no-op** — `_ADMIT` is
   `all_goals (first | done | sorry)` and the generator emits that string
   nowhere in this file any more (measured: 0 occurrences in `head`, 0 in
   `tail`, and `tail` itself is empty).
4. With no `trace_state` anywhere, no goal is ever printed, and `⊢ 1 =` cannot
   appear. The class asserts on a string it has stopped producing.

So the three failures are not evidence about `fdiv64`'s div0 arm, and they are
not evidence that anything was corrected. They are a doc-truth test that has
gone blind while reporting a diagnosis about the wrong thing — the failure mode
`bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`
records for `bootstrap-stage2-dumps`, and the one CLAUDE.md calls "a check that
did not look at what it produced".

## Why it went blind, and it is not only the fixture

Two independent drifts, and a fix needs both:

* **The fixture no longer generates the theorem the class dissects.** Whatever
  the div0 residual is today, it is not in a file that has a
  `q_compiles_correctly_universal` to dissect. Restoring the class therefore
  means either a fixture whose image has no unfollowable call (e.g. `a // 4`,
  where the divisor is a literal and the divide needs no call) or landing the
  `compiler_traps` subtraction in `_unfollowable_calls` as well.
* **The class does not check that its own mechanism fired.** It should assert
  that `_ADMIT` was present in the text before replacing it — one
  `assertIn` in the fixture, or `cls.traced = _ADMIT in tail` in `setUpClass`
  and a test that fails on it. Without that, any future drift of the same shape
  produces the same misleading "the fix this doc wants" message instead of
  "the thing I measure is gone".

## The exact next step

1. Add the mechanism check first (it is five lines and it is what makes the
   rest of the work verifiable): `setUpClass` records whether `_ADMIT` occurred
   in the tail it built, and a row fails when it did not.
2. Then decide which of the two the class should measure:
   * **subtract `info["compiler_traps"]` in `_unfollowable_calls` too.** This is
     the same fix as
     `formal/arm64_proof_gen.py::_program_extern_calls` and the same argument
     (the flush is the COMPILER's, on a path a program with a non-zero divisor
     never takes), and it is what `a // b` needs to get a universal theorem at
     all. It is *not* free: with the subtraction, `a // b`'s universal theorem
     has to discharge the div0 arm's `⊢ 1 = …`, which is FALSE for a symbolic
     divisor — so this step changes the class's subject from "the residual is
     false" to "the residual is reachable and unprovable", and needs the
     `formal40-4` disjunction work behind it.
   * **or** change the fixture to a literal divisor, where the model can step
     the divide and the residual is a different (and provable-or-not) goal.
     Cheaper, and it measures something real, but it stops measuring the
     symbolic-divisor case this class was written for — which is why it is the
     second option and not the first.

**Not done in the branch that found it:** that branch's claim is the arm64
extern-call and subscript diagnostics, and re-scoping a doc-truth measurement
class (plus the `_unfollowable_calls` change, which reaches the universal
theorem for the whole corpus) is a different piece of work with a whole-corpus
Lean sweep attached.
