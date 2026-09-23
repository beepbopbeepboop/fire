import ProofLib

/-! # work.lean — active work file

Currently empty: the proven, generic lemmas that lived here (per-instruction
`work_step_*` routing lemmas and the `work_body_run`/`work_body_mid`/
`work_loop_fuel`/`work_exit_hyps` loop-contract helpers) have been promoted
into `ProofLib.lean`.  New unproven work goes here; once proven and generic,
it is moved into `ProofLib.lean` as well. -/

/-! ## Con-branch (CSET) value-flow lemmas

  The `cond_flag` obligation of a `while_*_exit_contract` states that the CSET
  0/1 flag the loop header tests is `0` exactly when the loop condition is
  false.  Both loop generators (countdown and range) reduce to the same
  generic fact; it is proven once here so the generator stays thin. -/

/-- CSET (cc=3, unsigned `<`) zero-test: the 0/1 flag is `0` iff `¬ (a < b)`. -/
theorem work_cset_lt_zero_iff (a b : UInt64) :
    (if arm64_matches_condition 3 (arm64_subs_flags a b) = true then (1 : UInt64) else 0) = 0
    ↔ ¬ a < b := by
  rw [← arm64_flag_lt a b]
  by_cases hc : arm64_matches_condition 3 (arm64_subs_flags a b) = true <;>
    simp [hc]

/-- The CSET `<` flag is `false` exactly when `b ≤ a` (i.e. `¬ a < b`).  This is
    the residual form `simp [work_cset_lt_zero_iff]` leaves behind, so it is a
    one-line closer for the loop `cond_flag` obligation. -/
@[simp] theorem work_cset_lt_false_iff (a b : UInt64) :
    arm64_matches_condition 3 (arm64_subs_flags a b) = false ↔ b ≤ a := by
  calc
    _ ↔ ¬ (arm64_matches_condition 3 (arm64_subs_flags a b) = true) := by simp
    _ ↔ ¬ (a < b) := ⟨fun hp q => hp ((arm64_flag_lt a b).mpr q),
                      fun hq p => hq ((arm64_flag_lt a b).mp p)⟩
    _ ↔ b ≤ a := @UInt64.not_lt a b

