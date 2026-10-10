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

**Re-measured 2026-10-07 (`work/formal145-docs`), and the class's premise has
moved one step further away, not closer. Three measurements, each a correction
to the plan below:**

1. **The fixture no longer produces a blind file — it REFUSES.** This document
   records the class dissecting a generated file that has 234 theorems, no
   `compiles_correctly_universal` and no `sorry`, so `tail` is empty and the
   trace is a no-op. Measured on this tree, `_symbolic_divisor_proof` now raises
   `formal.build.FormalBuildError` inside `setUpClass`:

       universal theorem: 2 calls this walk cannot follow
         (0x100000424 -> 0x10000088c (opaque), 0x100000514 -> 0x100000880 (opaque)),
         every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge
         them. …

   The two opaque calls are the `BL fflush` in the divide-by-zero arm of
   `_emit_div_shift_pow` and the `BL fflush` in `_emit_exit` — both the
   COMPILER's, both on paths a non-zero divisor never takes. So the class does
   not measure the wrong thing today; it cannot build its subject at all, and
   its failure is an `ERROR` in `setUpClass` rather than the three assertion
   failures this document records.

2. **`info["compiler_traps"]` IS EMPTY ON ARM64, and that is a second defect on
   this path.** `formal/arm64_codegen.py` declares `_compiler_trap_addrs` (line
   724) and publishes it as `info["compiler_traps"]` (line 1100), and its own
   comment says the set holds "the ADDRESSES of the `BL fflush` this backend
   emits inside its own bounded stops" — but **nothing ever adds to it** (the
   only two occurrences in the file are the declaration and the export; x86-64
   appends at `x86_64_codegen.py:1914`). So `_program_extern_calls`'s documented
   subtraction of the compiler's own flush is a no-op on arm64, and the class's
   first option below rests on a set that is always `[]`.

3. **Option 1 ("subtract `info["compiler_traps"]` in `_unfollowable_calls`
   too") is confirmed a PROJECT, not a subtraction at one site — measured by
   trying it.** With the trap addresses recorded (defect 2 fixed) AND `_calls`
   in `_gen_universal_e2e_cfg` filtered by them, the "2 calls" refusal is gone
   and the generator refuses at a DIFFERENT point:

       recursion contract: the call in block 13 has to be below the source
       condition's negation (`u64_sub_one_toNat_le` needs it), and this walk
       reached the call with no enclosing branch condition to take it from.

   The WALK still meets the `BL fflush` as an instruction and executes it as a
   call, so filtering the unfollowable-call LIST does not tell the walk to treat
   the compiler's trap as the boundary it is. Both edits were reverted: they
   change what every arm64 theorem says and this is a light worker with no
   whole-corpus Lean sweep. **So the next step is unchanged** — either the
   `formal40-4` disjunction work behind option 1, or option 2's literal-divisor
   fixture — and defect 2 is worth fixing on its own before either, because it
   is a false claim in `_program_extern_calls`'s own docstring today.

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

## Status 2026-10-07: step 1 landed, and it now names the REAL cause

`work/formal128-docs` landed step 1 only. `setUpClass` records, per spelling,
why the class's own mechanism did not fire (`cls.blind`), and
`test_the_measurement_class_can_still_see_what_it_measures` fails on it by
NAME, so the bare `assertIn("⊢ 1 =")` can no longer report "the residual
moved" when the truth is "there is no residual here to move". Measured with
`lib/*.olean` materialised from the cas:

    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean
    FAIL: test_the_measurement_class_can_still_see_what_it_measures
    AssertionError: as_emitted: the fixture no longer generates a proof at all,
      so the residual this class exists for cannot be traced: FormalBuildError:
      … universal theorem: 2 calls this walk cannot follow
      (0x100000424 -> 0x10000088c (opaque), 0x100000514 -> 0x100000880 (opaque)),
      every one of them OUT OF THE IMAGE, and ONE halt address cannot discharge
      them. …

**And the cause it names is NOT this doc's line-6 diagnosis.** The fixture does
not "dissect a file with no theorem": `_symbolic_divisor_proof` now REFUSES at
generation. The two opaque calls are the arm64 compiler's own — the
stack-floor guard's `getrlimit` and the div0 arm's `fflush` — read as calls the
PROGRAM makes because `info["compiler_traps"]` is published and never filled on
arm64 (a merge lost the recording), and because the walk cannot discharge a
compiler call on a conditional path
(`FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`).
Step 2's option 1 ("subtract `compiler_traps` in `_unfollowable_calls`") is
necessary and not sufficient.

**So this doc's premise — that the class goes blind while proof generation
still succeeds — is superseded by that regression.** The step-1 check is what
made the difference visible; the class stays red until the emitter (formal115)
and walk (the conditional-halt doc's owner) land, and no part of that is this
branch's to change.
