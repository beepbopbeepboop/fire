# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Status 2026-10-13 (`work/formal336-docs`): the `maximum recursion depth` cluster
is a LIMIT, not an infinite loop, and it is NOT avoidable from the generator side
by the two things measured here — so the fix is the ProofLib statement change
below or a raised limit, and nothing smaller.** What was measured, all on
`formal/examples`-sized proofs and the `same_image_leaf` fixture:

* `same_image_leaf_proof.lean` FAILS at the generated `set_option maxRecDepth
  100000` and PASSES with 0 sorries at `maxRecDepth 1000000` (measured: rc=0,
  ~1m34s, 3.9 GB) and at `10000000` (~1m32s) — so the depth needed is between
  1e5 and 1e6 and the reduction is finite.
* The failing line is the `rw [runs_cons_seq st (<block>_qT0 st) …]` of a
  `*_b3_selfN` run certificate (`leafout_proof.lean:3890`), i.e. the run lemma's
  UNIFIER on a concrete run-exit state, and `set_option diagnostics true` names
  `List.get?Internal` / `List.rec` / `Nat.rec` — the reduction of `main_code`'s
  `main_code_list.getD` under that unifier, not `arm64_ext_imm12` (which is the
  §"most likely cause" hypothesis above, and is NOT where the depth is).
* Two candidate generator-side fixes were tried and NEITHER works:
  `let`-binding the run-exit state before the `rw` (the idiom the loop path uses
  at `formal/arm64_proof_gen.py:6177`) moves the error by one column and does
  not remove it; and a generator-emitted `@[simp] arm64_ext_imm12 w = …` lemma
  changes nothing (the depth is in a defeq, which `[simp]` does not reach).

So a taker has the same two options the section below names, and the
`maxRecDepth` one is a real fix rather than a hammer only if the depth is
bounded — measured: it is.

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: the two recursion reds and
the fact-count red are CLOSED; the four `TestTheZeroDivisorGuardAgainstLean`
rows and the `sgt8` row are OPEN and are NOT the recursion defect.** The fix is
`9e0cbcec` + `a487538f`; what is left is written down at the bottom of this
file and in
`bugs/FORMAL_arm64_the_two_writes_peel_names_a_path_state_that_did_not_write_the_slot.md`.

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
already records for this tree. The `sgt8` row fails with `Tactic rewrite failed`
at `mem_read_two_writes_adj_uint _ (((s_0).sp - …) …)`, verified byte-identical
before and after this fix; it is filed as
`bugs/FORMAL_arm64_the_two_writes_peel_names_a_path_state_that_did_not_write_the_slot.md`.

## Status 2026-10-12 (`work/formal275-docs`): the reds are unchanged, the
## `arm64_ext_imm12` cause below is DISPROVEN, and the real site is in the
## CFG RUN proof

Re-measured on master with the library built
(`test_formal_call_proof_gen.py`'s four classes, `TestTheZeroDivisorGuardAgainstLean`
included — 8 failures of 15). The failure named below is still, byte for byte,
`mod_proof.lean:4899:68: error: maximum recursion depth has been reached`, and
the Lean verdict is a cache REPLAY (the whole class runs in 0.7 s), so the
proof bytes are unchanged.

**It is not `arm64_ext_imm12`, and this is measurable without Lean.** The
generated `mod_by_var` proof contains **zero** occurrences of
`arm64_ext_imm12`; the only construct that names it is the step-RESULT lemma's
proof (`sr_87`'s `exact work_step_add_imm64 …`, which reads the model term by
DEFEQ), and that theorem is declared at line 2753 and accepted. The failing
declaration is the run proof's `b6_self1`:

```
4899  rw [runs_cons_seq st (mod_by_var_b6_qT0 st) mod_by_var_code 0 hs0 rfl,
4900      show st.pc + 4 = 4294968608 from by rw [hpc]]
```

so the recursion is in the `rw`'s matching over the CFG block state defs
(`qS0`/`qT0`/`qS1`), not in reducing the immediate. The next reader should
start at `runs_cons_seq` and the generated `{name}_{tag}_self{k}` chain
(`formal/arm64_proof_gen.py`, the `self{k}` emitter around the `runs_cons_seq`
call), NOT at `lib/ProofLib.lean`.

The other three reds are still present and were confirmed in the same run:
`TestSameImageCallLean.test_the_followed_call_proves_with_no_admission` (the
same `maximum recursion depth`, in `same_image_leaf_proof.lean`),
`TestNestedConditionFactSharing.test_the_fact_count_grows_with_the_paths_and_not_with_the_branches`
(2 → 3 conditions grow the `hprior_` facts 9 → 21, and the count is
`3 * (2**k - 1)` over k conditions — `9, 21, 45` — so the growth is above the
test's `x2.2` for the small-k step only; this is a property of the generated
path/scope tree and has nothing in it that names the model), and
`TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
(`sgt8`). `TestTheZeroDivisorGuardAgainstLean`'s rows are the class's own
"the fixture generates no `q_compiles_correctly_universal`" guard, i.e. the
pre-existing div0 residual recorded elsewhere, not a new failure.

**This doc's fix is NOT the same as `lib/ProofLib.lean`'s imm12 arms.** Not
fixed here — a light worker cannot iterate on a proof this deep without a Lean
run per attempt, and the corrected site above is the next step.

## 2026-10-12, second pass: items 1, 2 and 4 are the `runs` side condition and the shifted immediate, and NEITHER is `arm64_ext_imm12` mis-stated

With `lib/ProofLib.olean` built, the Lean rows run and items 1, 2 and 4
reproduce exactly as written. **The recursion depth is the argument to
`runs_cons_seq`, not the step lemma or `arm64_ext_imm12`:**

* the error column is the `rfl` in
  `rw [runs_cons_seq st (mod_by_var_b6_qT0 st) mod_by_var_code 0 hs0 rfl, …]`,
  the proof of `(qT0 st).pc = st.pc`;
* `rfl` on `(qT st).pc = (qS st).pc` reaches the kernel's recursion limit once
  the block's `sp` adjust is a `UInt64` literal at or above **512** — measured
  on a four-field toy structure:
  `{ st with sp := st.sp + (1024 : UInt64) }.pc = st.pc` fails under `rfl`
  while `+ 257` succeeds. `ADD sp, sp, #32, lsl #12` is `+131072`, inserted by
  the div0 guard arm, so `mod_by_var_b6_self1` is exactly the first block over
  the line. **This is why the `sh`-field fix is what exposed it and why reverting
  the fix is not the repair** — before it the immediate was `32`;
* `work_step_add_imm64` and `mod_by_var_sr_87` themselves elaborate fine (no
  error at their own lines), so §"The most likely cause" is wrong about this.

**Fixed in the emitter** (generator side, no `lib/` change): the side condition
is now `(by simp only [<qS>, <qT>, arm64_set_reg])` instead of `rfl`, at the six
`runs_cons_seq`/`runs_cons_jump` sites (`arm64_proof_gen.py`'s block run-theorem
emission). Unfolding `qS`/`qT` closes the `{ … with sp := … }` shape by
projection without reducing the `sp` term, and unfolding `arm64_set_reg` is what
keeps the register-setting transitions `rfl` DID handle working.

**Item 4 (`sgt8`) is the OTHER half of the same `sh`-field fix**: the model and
`_step_rhs`/`_cbz_reg_const` read the shift, but the Python spill-address
decoders (`_hcond_mem_rws`, `_frame_read_addrs`, `_frame_ldp_addrs`,
`_sp_stores`) did not, so a `#32, lsl #12` frame adjust was tracked as `+32`
where the code does `+131072` and the condition proof emitted a
`mem_read_two_writes_adj_uint` rewrite for an address the goal does not contain
(`Tactic 'rewrite' failed: Did not find an occurrence of the pattern …
⊢ arm64_matches_condition 13`). They now share `_addsub_imm12`. That one fix is
also what makes `sign`, `twoifs` and `elif3` elaborate again — examples the
committed baseline records as `proved`, so this was a live regression outside
this doc's table. See
`bugs/FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md` for the
model half.

Verified: `mod_by_var`, `same_image_leaf`, `sign`, `twoifs`, `elif3` and `sgt8`
now elaborate; running `test_formal_call_proof_gen.py` drops from 8 failures to
**5**, and the five that remain are all item 5's
(`TestTheZeroDivisorGuardAgainstLean`). Pinned by
`TestARunsSideConditionUnfoldsItsBlocks` and
`TestTheImmediateShiftReachesTheSpDecoders` (generation only, no Lean) and by the
Lean rows that now pass.

## 2026-10-12: item 3 is a miscalibrated TEST, not the generator

The first non-Lean red, and it is not the `arm64_ext_imm12` change either:

* the `hprior_*` emission is **byte-identical** to `cfd550b5` (the commit that
  introduced the per-path memo and where the bound was calibrated), verified by
  diffing `git show cfd550b5:formal/arm64_proof_gen.py` against HEAD in the
  emission region;
* the counts are now `c_k = 2 * c_{k-1} + 3`, i.e. `3 * (2**k - 1)` — **the PATH
  count (x2) plus one fixed startup constant**, measured 9 / 21 / 45 / 93 for
  k = 2/3/4/5, residual exactly 3 at every step;
* the old ratio bound of 2.2 was calibrated on `3 * 2**(k+1)` (24 / 48 / 96 /
  192 at `cfd550b5`), where the ratio is exactly 2. The counts are ~2x smaller
  now (a block-layout change after `cfd550b5`, not a memo change), so the fixed
  startup alone puts the k=2 -> 3 ratio at 2.33 while it falls back to 2.03 by
  k=6. **A ratio cannot distinguish "x2 plus a constant" from "exponential" at
  three samples of a small integer.**

**Fixed test-side, and the new assertion is the stronger one.**
`test_the_fact_count_grows_with_the_paths_and_not_with_the_branches` now reads
the RESIDUAL `c_k - 2*c_(k-1)` over FIVE programs (k = 2..5) and requires it to
be one constant across three independent steps: a generator that had gone
exponential shows a GROWING residual and fails, which the old single-ratio
bound could not see at these counts. No generator behaviour changed. **The
`CONDS` tuple grew one disjoint-bit condition so k=5 is a real 5-condition
program**; the two classes above still build their own programs from it.

## What is NOT fixed, and whose it is

Item 5 (`TestTheZeroDivisorGuardAgainstLean`'s rows) remains, **and the filing
already called it pre-existing** ("the class's state on the base tree"). It is
the div0 residual `FORMAL_a_conditions_operand_read_through_an_earlier_stores_
slot.md` owns, not this doc's, and the five remaining failures of the file are
exactly its subtests. Measured after the fixes: **183 tests, 5 failures**, down
from 8.


## Status, 2026-10-13 (`work/formal338-docs`): the `arm64_ext_imm12` attribution
## below is REFUTED; the recursion is `_code`'s `List.getD`, and it is deep, not
## infinite

Everything below is from 2026-10-08 and its "most likely cause" is wrong.  The
reproduction still holds — `mod_by_var`'s proof still stops with `maximum
recursion depth` — but the term that recurses is not `arm64_ext_imm12`:

* **`arm64_ext_imm12` reduces cheaply, at the DEFAULT depth.**  With the library
  built, `example : arm64_ext_imm12 (2436924415 : UInt32) = 131072 := by rfl`
  — and again with `decide`, `native_decide`, and `simp [arm64_ext_imm12]` —
  each checks at `maxRecDepth 1000` (not 100000).  So neither the ADD/SUB/CMP
  arm change nor an `@[simp]` lemma for it can be the cause, and the doc's
  option 2 cannot help a failing `rw` (which does not `simp`).
* **`set_option diagnostics true` names the recursion instead**:
  `List.get?Internal` / `List.rec` / `Nat.rec`, unfolding to depth > 100000.
  That is `_code`'s own definition,
  `formal/arm64_proof_gen.py::_gen_code_defs`:
  `def <name>_code addr := if addr < base then 0 else
  <name>_code_list.getD (addr - base) 0` — a `List.getD` indexed by a
  NEGATIVE-shifted `Nat`, so `List.get?Internal`/`Nat.rec` unfold on the index
  wherever the address is symbolic.
* **The depth boundary, measured on this tree** (the same
  `mod_by_var` proof, only `set_option maxRecDepth` moved):
  FAILS at `100000` (the generated file's own setting); TYPECHECKS at `150000`
  (69.8 s, 4.1 GB peak), `200000` (58.1 s), `300000` (58.9 s), `4000000`
  (48.0 s).  So it is deep-but-finite, needs ~1.2-1.5x the current bound, and
  costs ~60 s / ~4 GB once allowed to finish at all.
* **The `hprior` fact-count red is a separate question and is also not this
  cause.**  Its sibling `test_every_fact_is_proved_once_per_scope_and_in_scope`
  PASSES, so no fact is proved twice in a scope and the total (measured 3 / 9 /
  21 / 45 for 1..4 conditions = `3 * (2^k - 1)`) is minimal for the emission
  scheme.  The `2.2` ratio bound fails only at the 2 -> 3 step (21 / 9 = 2.33),
  because the counts are now small enough that the `-3` constant dominates; the
  ratio is 2.14 at the 3 -> 4 step.  Nothing here moved it.

**The corrected next step is a representation change in `_gen_code_defs`, not a
model or lemma change.**  A `List.getD` forces the `get?Internal`/`Nat.rec`
unfold; a `match addr with | <base + i> => byte | _ => 0` over the concrete
addresses (or a `ByteArray`/`Vector` read) is STUCK on a symbolic `addr`
instead of unfolding, which is what removes the depth.  It touches every
generated proof's `_code`, so it wants its own pass and a
`tools/formal_proof_census.py` re-measure, not a drive-by.

The pin is unchanged:
`test_formal_call_proof_gen.py::TestExternCallTheRunDoesNotReach.test_the_corpus_example_that_was_false_is_proved`
— it SKIPS without a built `lib/ProofLib.olean`, so build the library first
(`formal/lean.py::ensure_library`) before re-running it.

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
  (`sgt8`) — `Tactic rewrite failed` at
  `mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) -
  UInt64.ofNat 16) _ _`, a peel addressed at a path state that does not hold
  the store. Verified byte-identical against the pre-fix generator, so it is
  pre-existing and not this defect. Filed as
  `bugs/FORMAL_arm64_the_two_writes_peel_names_a_path_state_that_did_not_write_the_slot.md`.
