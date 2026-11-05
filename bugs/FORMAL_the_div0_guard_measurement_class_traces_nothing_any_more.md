# FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more

**Status 2026-10-18 (`work/bunny-merge26-r2-r2`): step 2's option 2 is NO
LONGER REFUTED — measured, generation only, no Lean, the two fixtures side by
side:**

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import formal.build as fb, re
for name, body in (('lit', 'def q(a):\n    return a // 4\n'),
                   ('sym', 'def q(a, b):\n    return a // b\n')):
    open('.tmp/%s.mojo' % name, 'w').write(body)
    r = fb.compile_formal('.tmp/%s.mojo' % name, arch='arm64',
                          output='.tmp/%s.aout' % name, prove=False,
                          check=False)['info']
    print(name, [c['sym'] for c in (r.get('extern_calls') or ())],
          [hex(a) for a in (r.get('compiler_traps') or ())])
    p = fb.compile_formal('.tmp/%s.mojo' % name, arch='arm64',
                          output='.tmp/%s.aout' % name, prove=True,
                          check=False)['proof_path']
    t = open(p).read()
    print('   ', re.findall(r'^theorem (q_.*(?:universal|reaches_call_at_\w+))', t, re.M),
          '_ADMIT', 'all_goals (first | done | sorry)' in t)"
lit ['getrlimit'] []
    ['q_compiles_correctly_universal'] True
sym ['getrlimit', 'fflush'] ['0x100000504']
    ['q_reaches_call_at_0x100000504'] False
```

**The mechanism is not the flush — the div0 ARM IS NOT EMITTED AT ALL for a
non-zero literal divisor**, because `formal/model.py::division_needs_zero_guard`
decides it at build time and `4` is decidable. So the `a // 4` image has no
out-of-image call at all (the startup stub's `getrlimit` is below `func_offset`
and is subtracted by address), `compiler_traps` is empty, and the generated
proof carries BOTH `q_compiles_correctly_universal` AND the walk terminal's
`all_goals (first | done | sorry)`.

**So the class's mechanism WOULD FIRE on a literal-divisor fixture and it would
have a residual to dissect** — which is exactly what "the class traces nothing"
denies. The 2026-10-13 Status block below measured option 2 the other way
(`fflush` present, substitution fired); that measurement no longer reproduces,
and the pin that recorded it
(`test_a_literal_divisor_does_not_restore_the_classs_subject`) was asserting a
thing that has stopped being true, so it is replaced by
`test_a_literal_divisor_RESTORES_the_classs_subject`, which pins the
`universal` + `_ADMIT` half — the half that IS the class's subject — rather than
the `fflush` that used to cause it.

**What this changes and what it does not.** The class is still blind **for the
symbolic divisor**, and this doc's next step is unchanged in that respect. But
option 2 is no longer a refutation, so the two-option decision in "The exact next
step" is a ONE-option decision, and what remains is the FIXTURE SWITCH: measure
`TestTheZeroDivisorGuardAgainstLean` on `def q(a): return a // 4`. That is not
landed here, and it honestly cannot be from a light worker: the class's Lean
rows need a built `lib/ProofLib.olean` (9.8 GB, over an 8 GB reservation), and
the switch "changes what the class measures", which is what the doc has said
since it was filed. **Option 1 is NOT re-measured here** — this block asserts
only what it ran, and the 2026-10-12 measurement that option 1 reaches the
recursion-contract refusal rather than the `⊢ 1 =` goal stands as the last word
on it.

**Status 2026-10-12 (`work/formal282-docs`): the SYMPTOM has moved once
further, the two claims the 2026-10-07/`formal115-docs` block below rests on are
both FALSE on this tree, and the class's own step-1 check now names the real
cause BY NAME. Measured, no Lean in the diagnosis:**
`formal/build.py::compile_formal(..., prove=True, check=False)` on
`_SYMBOLIC_DIVISOR` (`def q(a, b): return a // b`) no longer RAISES in
`setUpClass` — it GENERATES a proof file — and that file has **no**
`q_compiles_correctly_universal`; in its place it emits
`theorem q_reaches_call_at_0x100000504`, a REACHABILITY statement (the
`some s => True | none => False` match the walk substitutes when the run halts
at a call it cannot follow). So `_ADMIT` is absent, the class's
`test_the_measurement_class_can_still_see_what_it_measures` fails naming it, and
`TestTheZeroDivisorGuardAgainstLean` is 5 failures on any tree with
`lib/ProofLib.olean` — which is what "traces nothing" looks like today, not the
`FormalBuildError` the block below records.

1. **`info["compiler_traps"]` is populated on arm64 again, so the block below's
   "IS EMPTY ON ARM64" is false.** `e632f228` ("arm64: record the compiler's own
   calls again") restored `_emit_trap_flush`/`_record_trap_addresses`
   (`formal/arm64_codegen.py:3077`). Measured on the fixture: `compiler_traps =
   ['0x100000504']`, `extern_calls = [('0x1000003e0','getrlimit'),
   ('0x100000504','fflush')]`, `func_offset = 0x100000458`. The `getrlimit` is
   below `func_offset` (the startup-stub move) and `_program_extern_calls`
   subtracts both classes by address; the div0 arm's `fflush` is the one that
   still stops the WALK.
2. **The cause of the substitution is the walk, not the emitter, and the
   doc's option 1 is measured necessary and NOT sufficient — re-confirmed on
   this tree.** `_unfollowable_calls` is what decides the halt address and it
   does not consult `compiler_traps`, so the div0 `fflush` is read as the
   program's opaque call. Monkeypatching the subtraction in (generation only,
   no Lean) moves the refusal to
   `recursion contract: the call in block 4 has to be below the source
   condition's negation (u64_sub_one_toNat_le needs it), and this walk reached
   the call with no enclosing branch condition to take it from` — the same third
   refusal `formal145-docs` measured, so the fix this doc wants ends at
   `bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
   (set-valued / per-block terminal, a `lib/ProofLib.lean` project). **The class
   is therefore BLOCKED on that doc's owner, not on anything this branch may
   change**: it is the intended outcome of the step-1 check, which fails by name
   rather than reporting "the residual moved".
3. **And a second, separate red sits under it, so even with a universal theorem
   the class would not yet get a residual.** The generated `q(a,b)` proof does
   not typecheck: `lean` on it fails at `q_b6_self1`'s
   `q_sr_86 (q_b6_qS0 st) (hpc0)` with `maximum recursion depth has been
   reached` (`q_check.lean:4723:50`) — the same merge-era
   `maxRecDepth`-at-a-block-start defect measured on `mod_by_var` (its
   `b6_self1`), which `f7bd05ea` closes by discharging the block-start
   `runs_cons_seq` side condition with `first | (simp only [qT0, qS0] <;> done)
   | rfl` rather than a bare `rfl`.

**What landed here, and it is a pin rather than a fix.**
`TestTheZeroDivisorGuardAgainstLean`'s `blind` report now NAMES the
reachability substitution instead of only "no theorem carrying `_ADMIT`", and
`test_formal_call_proof_gen.py::TestTheDiv0FixtureHaltsAtTheCompilerTrap` pins
the substitution itself with no Lean (the fixture emits
`q_reaches_call_at_0x100000504`, not `q_compiles_correctly_universal`, and no
`_ADMIT`), so the day the walk lands this test goes red and says the class is
measurable again. Verified with `lib/*.olean` materialised from the cas:
`TestTheDiv0FixtureHaltsAtTheCompilerTrap` 1 test / OK;
`TestTheZeroDivisorGuardAgainstLean` still 5 failures, each now naming the
substitution.

**Area:** FORMAL, the arm64 proof generator's own doc-truth test.
`test_formal_call_proof_gen.py::TestTheZeroDivisorGuardAgainstLean`
(`test_the_false_goal_survives_the_documented_next_step`,
`test_the_residual_is_the_same_with_and_without_the_branch_fact`).

**Status 2026-10-13 (`work/formal400-docs`): the Lean-free pin this doc's step 1
added is GREEN again — taught the THIRD state the fixture now has, the ANNOUNCED
substitution — and the doc's step 2 is now DOUBLY refuted by measurement. The
class itself stays red for the honest reason (it is blind and says so by NAME),
so this doc is still OPEN; what changed is that both routes out are now named as
unreachable on this tree rather than merely unpicked.**

* **The pin
  (`TestTheZeroDivisorGuardIsAFalseGoal::test_the_symbolic_divisor_fixture_
  still_has_its_subject`) demanded `_ADMIT` in the tail OR a refusal containing
  `this walk cannot follow`. Neither holds today: the generator SUBSTITUTES the
  universal theorem with the reachability theorem `q_reaches_call_at_0x100000504`
  (one out-of-image `BL`, so one halt address, so no refusal), and it ANNOUNCES
  the substitution in the emitted note — the one-opaque-call behaviour
  `bugs/FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md`'s
  item 2 landed. The pin now accepts that third state **only if** the note names
  `q_compiles_correctly_universal` as `NOT emitted`, so a SILENTLY empty tail is
  still forbidden. This is not a weakening: outcome 3 still leaves
  `_ADMIT not in tail`, which is exactly what makes the class set `cls.blind`
  and fail its Lean row by NAME. Measured, library absent:
  `python3 tools/memslot.py --gb 8 --label t -- python3
  test_formal_call_proof_gen.py` → **178 tests, 0 failures, 13 skipped** (was
  177 tests / 1 failure, the pin). With a built `lib/ProofLib.olean` the class's
  Lean rows still run and still fail, by NAME (`cls.blind`) — and `setUpClass`
  now records the substitution specifically ("the generator SUBSTITUTED
  `q_compiles_correctly_universal` with the announced reachability theorem
  (`q_reaches_call_at_…`) …"), so the failure says which of the three states the
  fixture is in rather than "no `_ADMIT`". Measured:
  `… test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean` → 5
  failures, every one carrying that sentence.
* **Step 2's option 2 — "change the fixture to a literal divisor, where the
  model can step the divide" — is REFUTED.** Measured, generation only, on this
  tree:

      def q(a): return a // 4      # arch=arm64, prove=True, check=False
      extern_calls carry ('fflush', 0x1000004fc) and
      compiler_traps == [0x1000004fc]; the generated file carries NO
      `theorem q_compiles_correctly_universal` and IS substituted by
      `q_reaches_call_at_…`, exactly as the symbolic case.

  A CONSTANT non-zero divisor still emits the divide-by-zero arm and its
  `_emit_exit` `fflush`, so there is one out-of-image call and the substitution
  fires either way. Step 2's option 1 (subtract `compiler_traps` in
  `_unfollowable_calls`) was already refuted (it moves the refusal to the
  recursion contract, §"Re-measured 2026-10-07" item 3). **Both options are now
  refuted**, and the second is pinned by
  `test_a_literal_divisor_does_not_restore_the_classs_subject`.
  *(SUPERSEDED 2026-10-18 — the "STILL emits" claim here is FALSE on this tree:
  `division_needs_zero_guard` is decidable for a literal, so the arm is not
  emitted at all and option 2 WORKS.  The Status block at the top of this
  document is the measurement; the pin is now
  `test_a_literal_divisor_RESTORES_the_classs_subject`.)*

**So the class cannot measure the div0 residual until the arm64 walk can
discharge a call on a conditional path — `bugs/FORMAL_arm64_the_walk_cannot_
discharge_a_call_on_a_conditional_path.md`'s option 1 — which is not a
`test_formal_*` change. The three Lean rows stay RED, by NAME, and this document
stays OPEN.**

**Step 1 LANDED 2026-10-08 (`work/formal152-docs`).** `setUpClass` now records
`cls.traced[label] = _ADMIT in tail` (and records a generation refusal the same
way), and the new row `test_the_mechanism_that_prints_the_residual_fired` fails
when it did not fire — so this class can no longer report a `fdiv64` diagnosis
about a goal it never traced. `## The exact next step` item 1 is marked done
below; item 2 (which of the two the class should measure) is the work that
remains, and this row is what makes it verifiable. **The new row is only
observable with an integrator's `prooflib` build** — `lib/ProofLib.olean` is
absent on this worktree, so the class SKIPS there; the file parses and every
Lean-free class in it is green.

**Step 1 LANDED 2026-10-08 (`work/formal166-docs`).** `setUpClass` now records
`cls.traced[label] = _ADMIT in tail` (and records a generation refusal the same
way), `test_the_mechanism_that_prints_the_residual_fired` fails when it did not
fire, and both existing rows check that flag FIRST so a fixture that stopped
producing a residual can no longer report the misleading "fdiv64 may have been
corrected" diagnosis.  **The mechanism check is also pinned Lean-free**, which
the class itself cannot be: `TestTheZeroDivisorGuardIsAFalseGoal::
test_the_symbolic_divisor_fixture_still_has_its_subject` asserts, without a
built library, that the fixture's outcome is one the class RECOGNIZES and NAMES
— a tail carrying `_ADMIT`, a refusal with the two-unfollowable-calls message,
or (the state the 2026-10-13 Status above added) the ANNOUNCED
`q_reaches_call_at_…` substitution whose note says the universal theorem is
`NOT emitted` — never a SILENTLY empty tail.  That row is why a light worker can
observe this half.  On this tree the class is red for the honest reason: the
div0 arm's `fflush` is the one out-of-image call, so the universal theorem is
SUBSTITUTED (an earlier tree REFUSED at generation because arm64 also read its
own stack-guard `getrlimit` as a program call; that is fixed, which is why the
state moved from a refusal to the substitution).  Step 2 (which of the two the
class should measure) is the work that remains, and the 2026-10-13 Status above
measures BOTH of its options refuted.

**Status: OPEN, diagnosed, not fixed. Pre-existing on this tree — verified by
reverse-applying the `formal/arm64_codegen.py` +
`formal/arm64_proof_gen.py` diff of the branch that found it and re-running the
class: 3 failures before, 3 failures after, identical messages.**

**Re-measured 2026-10-10 (`work/formal266-docs`), generation only, no Lean:
the fixture GENERATES again, so the "REFUSES" entries below are stale.** The
class's own `setUpClass` call `_symbolic_divisor_proof(tmp)` — this file's
helper, `compile_formal(..., arch="arm64", prove=True, check=False)` — RETURNS
instead of raising `FormalBuildError`. What it builds carries a
`theorem q_reaches_call_at_0x100000504` and NO
`theorem q_compiles_correctly_universal` and no `all_goals (first | done |
sorry)` admission: the universal theorem has been REPLACED by a reachability
statement, which is precisely the silent half the FLUSH doc names. So option 1
("subtract `compiler_traps` in `_unfollowable_calls`") did not move this, and
the live owner of what this class now measures is
`bugs/FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md`
(`formal267-docs`) — the three red rows that doc lists are these three. Step 1
LANDED: `test_the_measurement_class_can_still_see_what_it_measures` is the
blind-guard (present in the file) that reports this by NAME on a tree WITH
`lib/ProofLib.olean`; on a tree without it the whole class still SKIPs, so the
outcome is unobservable from this worktree.

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
merge (`8df5b273`; the EMITTER half is landed again in `e632f228`, "arm64: record
the compiler's own calls again", and the stack guard's `getrlimit` has since
moved into the startup stub below `func_offset`, so it is subtracted by ADDRESS
rather than published as a trap — pinned by `test_formal_call_proof_gen.py`'s
`TestCompilerTrapIsNotAProgramCall`), so on master there is nothing to subtract,
and (b) subtracting it is measured NOT to reach
is new, and what blocks the fix this doc wants, is that (a) at the time it was
written arm64's `compiler_traps` list was EMPTY because the emitter recording
had been dropped by a merge (`8df5b273`; the emitter half has since landed
again, and the stack guard's `getrlimit` read has moved to the startup stub,
below `func_offset`, where it is subtracted by address), so on that tree there
was nothing to subtract, and (b) subtracting it is measured NOT to reach
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

1. **The fixture no longer produces a blind file — it REFUSES.** *(STALE
   2026-10-13: the `FormalBuildError` below no longer reproduces — the startup
   stub's `getrlimit` moved below `func_offset`, so the image has only ONE
   opaque call and the fixture generates a blind file again; see the Status at
   the top.)* This document
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

2. **`info["compiler_traps"]` WAS EMPTY ON ARM64, a second defect on this path —
   FIXED 2026-10-13 (`_emit_trap_flush` now records each `BL fflush`; see the
   Status at the top of this doc). The paragraph is kept as history.** `formal/arm64_codegen.py` declares `_compiler_trap_addrs` (line
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

**Status 2026-10-08 (`work/formal180-docs`): step 1 of "The exact next step"
below is LANDED — the class now checks its own mechanism, which is what makes
it fail on "the measurement did not happen" instead of on a diagnosis about the
div0 arm. And the blocker the doc diagnoses has MOVED: the fixture does not
generate a file at all on this tree, and BOTH reasons it does not are another
worker's claim.**

* **The mechanism check is in.** `TestTheZeroDivisorGuardAgainstLean` now
  catches a fixture refusal, records whether the fixture generated and whether
  the walk terminal's `all_goals (first | done | sorry)` admission was in the
  tail it built, and has `test_the_measurement_mechanism_fires` fail naming the
  refusal. The two goal rows call the same
  `_assert_the_measurement_happened`, so a missing fixture reports "the fixture
  produced no proof file, so NO residual was traced" rather than the class's own
  (wrong) "fdiv64's div0 arm … may have been corrected". That is the doc's own
  finding: "a check that did not look at what it produced."
* **What the fixture does today, measured.** `_symbolic_divisor_proof` raises
  `NotImplementedError` out of `generate_arm64_proof`, which reports **2 calls
  this walk cannot follow**: `0x100000424 -> 0x10000088c` is **`getrlimit`**,
  the stack-floor guard's call in every arm64 prologue, and
  `0x100000514 -> 0x100000880` is the div0 trap's **`fflush`**.
  `info["compiler_traps"]` is **empty** on this tree, so `_program_extern_calls`
  subtracts nothing and `_unfollowable_calls` sees both calls; the count rule
  (`len(_calls) - (1 if _intra else 0) > 1`) then refuses. So §"Why it went
  blind, and it is not only the fixture" is doubly stale now: the flush is not
  subtracted **anywhere**, and there is a SECOND opaque call — the guard's
  `getrlimit` — that the doc's single-call account does not have.
* **Both halves are another worker's.** The `getrlimit` guard and the dropped
  `_emit_trap_flush` were
  `FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call`
  (now deleted: `work/formal163-docs` fixed it — the read moved to the startup
  stub and `_emit_trap_flush` is restored; the re-measurement below is the
  measurement), whose own next step 1 was exactly
  "subtract the compiler's calls from `_calls`". Step 2 below is therefore not
  this tree's to take and is not taken here. When it lands, the check added here
  is what makes the resumed measurement trustworthy: the mechanism row passes
  only if a proof file is produced AND it carries the admission the class
  dissects, so a future drift of the same kind cannot masquerade as a div0
  result again.

**Re-measured 2026-10-12 on the merged tree (`work/merge-qwen1`): the
"2 calls this walk cannot follow" refusal is GONE, and the failure has
moved one step down the class's own mechanism.** The two opaque calls the
bullets above measured are fixed on this tree: the trap `fflush` is
recorded in `info["compiler_traps"]` again (`arm64_codegen`'s
`_emit_trap_flush`), and the guard's `getrlimit` read moved to the STARTUP
STUB (`_emit_stack_floor_init`), below `func_offset` and subtracted by
address. The fixture no longer refuses: it generates, but the generated
file carries no `q_compiles_correctly_universal` at all, so the tail the
class partitions is empty and the Lean-free pin
(`TestTheZeroDivisorGuardIsAFalseGoal::test_the_symbolic_divisor_fixture_
still_has_its_subject`) is RED on this tree for exactly that reason — a
documented pre-existing red of this run, not chased here. The step-1
mechanism check — the `cls.blind` implementation measured in the "Status
2026-10-07: step 1 landed" section below, this branch's
`test_the_measurement_mechanism_fires` having merged as a parallel of it —
is what keeps the class from reporting the fdiv64 diagnosis for that empty
tail.

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

1. ~~Add the mechanism check first~~ **DONE 2026-10-08** — landed in
   parallel on several branches that day; the implementation in this tree
   is the `cls.blind` one the "Status 2026-10-07: step 1 landed" section
   below measures: `setUpClass` records, per spelling, whether the
   fixture generated and whether `_ADMIT` occurred in the tail it built
   (a generation refusal is caught into the same flag), and
   `test_the_measurement_class_can_still_see_what_it_measures` fails by
   NAME when it did not, with both goal rows checking the same flag
   before their assertions.  It is pinned Lean-free by
   `TestTheZeroDivisorGuardIsAFalseGoal::test_the_symbolic_divisor_
   fixture_still_has_its_subject` — the fixture either produces a tail
   carrying `_ADMIT` or refuses outright, never a silently empty tail.
   The 2026-10-08 section above records this branch's parallel landing
   (`test_the_measurement_mechanism_fires` and the shared
   `_assert_the_measurement_happened`), whose row names are the ones it
   measured on its own tree.
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
     second option and not the first. **MEASURED WORKING 2026-10-18**: the
     Status block at the top of this document shows a `a // 4` image with no
     out-of-image call at all and a proof carrying both
     `q_compiles_correctly_universal` and `_ADMIT`, so this is the ONE option
     left, and the step it names is the FIXTURE SWITCH — needs a built
     `lib/ProofLib.olean`, so it is not a light worker's.

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

## Status 2026-10-12 (`work/formal313-docs`): the regression is GONE, and the
## class is blind again in its ORIGINAL shape — the `FormalBuildError` above is
## superseded, and the class's own `blind` message is the correct one now

**The `FormalBuildError` this doc's last two Status blocks record no longer
happens.** The two independent changes both landed: `formal/arm64_codegen.py`
records its own trap `fflush` again (`_emit_trap_flush` →
`info["compiler_traps"]`), and the stack-floor guard's `getrlimit` moved into
the startup stub (`_emit_stack_floor_init`) **below `func_offset`**, so
`_program_extern_calls` subtracts both and the walk's range
`[func_entry, func_end)` no longer contains `getrlimit` at all. Measured,
`prove=False`:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import formal.build as fb
r = fb.compile_formal('.tmp/symdiv.mojo', arch='arm64', output='.tmp/symdiv.aout',
                      prove=False, check=False)['info']
print('extern_calls', r['extern_calls']); print('compiler_traps', r['compiler_traps']);
print('func_offset', r['func_offset'])"
extern_calls [{'sym': 'getrlimit', 'addr': 4294968288}, {'sym': 'fflush', 'addr': 4294968580}]
compiler_traps [4294968580]
func_offset 4294968408
```

`getrlimit` is below `func_offset` and `fflush` is in `compiler_traps`, so
`_program_extern_calls` is `[]` and there is no "2 calls" refusal. **What the
class sees instead is the ORIGINAL blindness of this doc's very first section,
one layer down:** generation SUCCEEDS, and the generated file has no
`q_compiles_correctly_universal` and no `_ADMIT` — its only universal theorem is
a reachability statement for the compiler's own flush:

```console
$ python3 … compile_formal('.tmp/symdiv.mojo', prove=True, check=False) …
theorems matching universal/reaches: ['q_reaches_call_at_0x100000504']
'_ADMIT' present in the file: False
```

`0x100000504` is the `BL fflush` in `_emit_div_shift_pow`'s divide-by-zero arm
— a COMPILER call, on an arm a non-zero divisor never takes — and
`_unfollowable_calls` does not subtract `info["compiler_traps"]`, so the walk
still halts the universal theorem at it. `setUpClass` therefore sets
`blind['as_emitted']` to the *"generates no `q_compiles_correctly_universal`
carrying `_ADMIT`"* message (not the `FormalBuildError` one), and
`test_the_measurement_class_can_still_see_what_it_measures` fails on it BY NAME
— which is step 1 working as designed. **This doc's `FormalBuildError` Status
blocks are history; the measured state is the one this doc was filed about.**

**Nothing else changes.** Step 2's two options are the same and neither is this
doc's to take: option 1 ("subtract `compiler_traps` in `_unfollowable_calls`")
still reaches the conditional-call refusal rather than the `⊢ 1 =` goal
(`FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`), and
option 2 (a literal-divisor fixture) still changes what the class measures. The
class stays red until the walk keeps a terminal for a compiler call, which is
that doc's `lib/ProofLib.lean` project. The correction worth having is that the
walk fix is now the ONLY thing standing in the way — the emitter half and the
`getrlimit` half are both landed and pinned
(`test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall`, 10 tests,
0.289 s, OK).
