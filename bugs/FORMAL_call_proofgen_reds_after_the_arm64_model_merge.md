# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: the two recursion reds, the fact-count red and the `sgt8` row are
CLOSED; the four `TestTheZeroDivisorGuardAgainstLean` rows are OPEN and are NOT
the recursion defect.** The recursion/fact fix is `9e0cbcec` + `a487538f`;
`sgt8` is closed by the ADD/SUB immediate-shift fix in `formal/
arm64_proof_gen.py::_addsub_imm` (`work/formal412-docs`), whose own doc was
deleted with it. What is left is written down at the bottom of this file.

## What the reds were, and what turned out to cause them

**The recursion reds (`mod_by_var`, `same_image_leaf`) were `rfl`, not
`arm64_ext_imm12`.** The doc's §"The most likely cause" below guessed the
shifted immediate's own term; measured, that term reduces in microseconds
(`arm64_ext_imm12 (2436924415 : UInt32) = 131072 := rfl` at the default
`maxRecDepth 1000`), and so does `UInt64.ofNat` of the result. What does *not*
reduce for free is `rfl` over a COMPOSED state — `_gen_run_cert`'s
`have hpc{k} : ({S}_qS{k} st).pc = …` and every `runs_cons_seq`/`runs_cons_jump`
`hseq` — because `rfl` asks Lean to `whnf` that state, the whnf re-reduces the
`UInt64` numeral from inside the record, and the reduction walks `Nat.mod_lt`'s
own `Nat.decLe` evidence, whose `Nat.ble` is a structural recursion.

Measured by holding everything else fixed and varying ONE word's scaled
immediate (`add sp, sp, #imm{, lsl #12}`, `rd = rn = 31`, through
`runs_cons_seq`): `#0`, `#1`, `#16`, `#32`, `#1024`, `#4095`, `#+4096` and
`#+16384` all fit in `maxRecDepth 1000`; `#+32768` needs between 20000 and
40000; `#+131072` does not fit in 100000 at all; and the whole proof then takes
40 s at `10^7`. Two further controls pin it to `rfl` rather than to the state:
the SAME state written inline (no `def`) is free, and a state `def` built with
an explicit `Arm64State.mk` is expensive, so what costs is the unfolding `rfl`
performs and not the numeral.

**The fact-count red was never a red.** The test measures the per-path
INCREMENT, `counts[k] - counts[k-1]`, not the totals — that changed in
`4bd482ce`, after this file was filed. Measured here: 3 / 9 / 21 / 45 facts for
1 / 2 / 3 / 4 conditions, increment 12 then 24 (exactly x2, the path count), and
4 / 6 / 8 DISTINCT statements, i.e. exactly two new facts per condition (the
tested value and the new `x`). Nothing is duplicated —
`test_every_fact_is_proved_once_per_scope_and_in_scope` is green, and the totals'
`9 -> 21` is the constant prologue term the test's own comment describes, not
growth.

**The other five reds are not this defect.** `TestTheZeroDivisorGuardAgainstLean`'s
four rows and `TestTheZeroDivisorGuardIsAFalseGoal`'s row all fail on the same
thing — the fixture generates a file with no `q_compiles_correctly_universal`, so
the class partitions an empty tail — which
`bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`
already records for this tree. The `sgt8` row failed with `Tactic rewrite failed`
at `mem_read_two_writes_adj_uint _ (((s_0).sp - …) …)`, verified byte-identical
before and after this fix; **it is FIXED** (`work/formal412-docs`), and the
cause was neither the recursion depth this file is about nor the "path state
that did not write the slot": the four `sp` trackers in
`formal/arm64_proof_gen.py` read an ADD/SUB immediate's twelve bits and dropped
its `sh` field, so the prologue's `sub sp, sp, #32, lsl #12` (131072) was
tracked as `32` and every peel addressed a slot 131040 bytes off. One reader,
`_addsub_imm`, and `test_formal_call_proof_gen.py::TestAddSubImmediateShift`
pins all four trackers.

## What was run

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py

    FAILED (failures=10)

and, class by class, the ones this doc is about:

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py TestExternCallTheRunDoesNotReach
    # 1 failure: test_the_corpus_example_that_was_false_is_proved

## What was seen

* `TestExternCallTheRunDoesNotReach.test_the_corpus_example_that_was_false_is_proved`
  — `formal/examples/mod_by_var.mojo`'s generated proof does not typecheck:

      mod_proof.lean:4899:68: error: maximum recursion depth has been reached

  The site is the application of the generated step lemma
  `mod_by_var_sr_87` (an `ADD sp, sp, #32, lsl #12`, whose RHS is
  `s.sp + UInt64.ofNat 131072`) inside the run proof. `maxRecDepth` is already
  `100000` in the generated file, so this is a looping/deep kernel reduction and
  not a low limit.
* `TestSameImageCallLean.test_the_followed_call_proves_with_no_admission` — the
  same `maximum recursion depth has been reached`, in
  `same_image_leaf_proof.lean`.
* `TestNestedConditionFactSharing.test_the_fact_count_grows_with_the_paths_and_not_with_the_branches`
  — 2 -> 3 conditions grew the `hprior_` facts by x2.33 (9 -> 21) where the test
  bounds it at x2.2 ("the per-path memo makes this x2").
* `TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
  (`sgt8`) — a `rewrite` that no longer finds its pattern; the test's own
  message says `sgt8` "did not typecheck before this fix either", so this one is
  plausibly pre-existing.
* `TestTheZeroDivisorGuardAgainstLean` (4 rows) — the class's fixture generates
  no `q_compiles_correctly_universal`, which
  `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`
  already records as the class's state on the base tree; treat those four as
  pre-existing.

## The most likely cause — MEASURED WRONG, and what the fix actually was

This section's guess was that the reds all come from `arm64_ext_imm12` in
`work_step_add_imm64`'s statement (`lib/ProofLib.lean:5117`), so that unifying
the concrete generated step with that lemma "reduces through
`arm64_ext_imm12`". **It does not.** Measured:

* `arm64_ext_imm12 (2436924415 : UInt32) = 131072` closes by `rfl` at the
  DEFAULT `maxRecDepth` (1000), and so does
  `UInt64.ofNat (arm64_ext_imm12 …) = UInt64.ofNat 131072` — the helper is cheap
  to reduce.
* Spelling the generated RHS through the helper instead of the literal
  (`UInt64.ofNat (arm64_ext_imm12 (2436924415 : UInt32))` in
  `mod_by_var_b6_qT0` and in `mod_by_var_sr_87`, all four occurrences) changes
  nothing: `mod_proof.lean:4899:68: error: maximum recursion depth has been
  reached` again.
* What does move the error is the TACTIC. In a 39-line standalone file, the
  single failing goal is `have hpc : (b_qT0 st).pc = st.pc := rfl` for
  `def b_qT0 (st) := { st with sp := (st.sp + UInt64.ofNat 131072) }`, and the
  same statement with the state written INLINE is free while the same statement
  over a `def` built as an explicit `Arm64State.mk` is expensive.

So `rfl` over a composed state is the whole cost, the cost grows with the
immediate *because* `rfl` re-reduces the `UInt64` numeral inside the record, and
the `lsl #12` fix only made it visible by being the first thing in the corpus to
carry a large `UInt64` literal in a block state.

**What landed** (`9e0cbcec`, `a487538f`): `_state_proof` discharges those side
conditions with `by simp only [<the block's own `qS`/`qT` defs>, arm64_reg,
arm64_set_reg]` instead of `rfl` — a textual unfolding that never forces the
reduction. The same change is applied to `_emit_reg_chain`'s `hS{k+1}` and to
the dylib contract's `runs_cons_seq … (by rfl)`. `lib/ProofLib.lean` is
untouched; the model change stays, because the shift is a real correctness fix
and its own tests (Peephole's `sh = 0` side conditions, this file's trap rows)
depend on it.

## What is left, and what it is not

`python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py`
now reports **FAILED (failures=7)**, down from 10, and every one of the seven is
a mechanism this fix does not touch:

* four rows of `TestTheZeroDivisorGuardAgainstLean` plus
  `TestTheZeroDivisorGuardIsAFalseGoal::test_the_symbolic_divisor_fixture_still_
  has_its_subject` — all "the fixture generates no
  `q_compiles_correctly_universal` carrying the admission", i.e. the class
  partitions an empty tail. Already recorded for this tree in
  `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`;
  NOT fixed here.
* `TestANarrowTypedParameterGetsItsRange::test_lean_accepts_the_three_examples`
  (`sgt8`) — **FIXED** (`work/formal412-docs`). The `Tactic rewrite failed` was
  at `mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) -
  UInt64.ofNat 16) _ _`, a peel addressed 131040 bytes away from the store,
  because the ADD/SUB immediate's `sh` field was dropped by the four `sp`
  trackers. Same cause and same fix as `ifonly`/`condassign`/`elif3`, which
  were unexpected failures of the `formal` job for the same reason.
