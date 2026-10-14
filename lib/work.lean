import ProofLib
import X86

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

/-! ## Unsigned division/remainder identity (UDIV+MSUB)

  Bridges the machine's UDIV/MSUB remainder sequence to the model's `%`. -/

/-- `a - (a / b) * b = a % b` for unsigned 64-bit division when `b ≠ 0`.
    Bridges the machine's UDIV/MSUB remainder sequence to the model's `%`. -/
theorem u64_div_msub (a b : UInt64) (hb : b ≠ 0) :
    a - a / b * b = a % b := by
  apply UInt64.toNat.inj
  rw [UInt64.toNat_sub, UInt64.toNat_mul, UInt64.toNat_div, UInt64.toNat_mod]
  have hb' : b.toNat ≠ 0 := by
    intro h; apply hb; apply UInt64.toNat.inj; rw [h]; rfl
  have hy0 : 0 < b.toNat := Nat.pos_of_ne_zero hb'
  have hprod : a.toNat / b.toNat * b.toNat = a.toNat - a.toNat % b.toNat := by
    have h := Nat.div_add_mod a.toNat b.toNat
    rw [Nat.mul_comm] at h
    omega
  have hqdb : a.toNat / b.toNat * b.toNat < 2^64 := by
    rw [hprod]
    have := UInt64.toNat_lt a
    omega
  have hmod_le : a.toNat % b.toNat ≤ a.toNat := Nat.mod_le _ _
  have hr64 : a.toNat % b.toNat < 2^64 := by
    have := UInt64.toNat_lt a
    omega
  have hmod_qd : a.toNat / b.toNat * b.toNat % 2^64 = a.toNat / b.toNat * b.toNat :=
    Nat.mod_eq_of_lt hqdb
  rw [hmod_qd]
  have hsum : 2^64 - a.toNat / b.toNat * b.toNat + a.toNat
            = 2^64 + (a.toNat - a.toNat / b.toNat * b.toNat) := by omega
  rw [hsum, Nat.add_mod, Nat.mod_self, Nat.zero_add, Nat.mod_mod]
  rw [hprod]
  have hcancel : a.toNat - (a.toNat - a.toNat % b.toNat) = a.toNat % b.toNat := by omega
  rw [hcancel]
  exact Nat.mod_eq_of_lt hr64

/-! ## Signed division/remainder helpers and identity (SDIV+MSUB) -/

theorem emod_eq_mod (a b : Int) : a.emod b = a % b := rfl

theorem int_add_sub_cancel (x a : Int) : x + (a - x) = a := by
  rw [Int.sub_eq_add_neg, ← Int.add_assoc, Int.add_comm x a, Int.add_neg_cancel_right]

theorem int_add_mul_emod (a b k : Int) : (a + k * b) % b = a % b := by
  calc (a + k * b) % b
      = (a % b + (k * b) % b) % b := Int.add_emod a (k * b) b
    _ = (a % b + ((k % b) * (b % b) % b)) % b := by rw [Int.mul_emod]
    _ = (a % b + ((k % b) * 0 % b)) % b := by rw [Int.emod_self]
    _ = (a % b + (0 % b)) % b := by rw [Int.mul_zero]
    _ = (a % b + 0) % b := by rw [Int.zero_emod]
    _ = a % b % b := by rw [Int.add_zero]
    _ = a % b := Int.emod_emod a b

theorem ofNat_lt_pow_emod (n : Nat) (h : n < 2^64) :
    (Int.ofNat n).emod (2^64 : Int) = Int.ofNat n := by
  have hediv : (Int.ofNat n) / (2^64 : Int) = (Int.ofNat n).tdiv (2^64 : Int) := by
    rw [Int.ediv_eq_tdiv]
    simp
  have htdiv : (Int.ofNat n).tdiv (2^64 : Int) = Int.ofNat (n / 2^64) :=
    (Int.ofNat_tdiv n (2^64)).symm
  have hdiv0 : n / 2^64 = 0 := by omega
  have h0 : (Int.ofNat n) / (2^64 : Int) = 0 := by
    rw [hediv, htdiv, hdiv0]
    rfl
  have hdef : (Int.ofNat n).emod (2^64 : Int)
            = Int.ofNat n - (2^64 : Int) * ((Int.ofNat n) / (2^64 : Int)) :=
    Int.emod_def _ _
  rw [hdef, h0]
  simp

theorem ofNat_sub_pow_mod (n : Nat) :
    (Int.ofNat n - (2^64 : Int)) % (2^64 : Int) = (Int.ofNat n) % (2^64 : Int) := by
  rw [show Int.ofNat n - (2^64:Int) = Int.ofNat n + (-1:Int) * (2^64:Int) by
        rw [Int.sub_eq_add_neg, Int.neg_one_mul]]
  exact int_add_mul_emod (Int.ofNat n) (2^64) (-1)

theorem u64_toS64_mod (x : UInt64) :
    (u64_toS64 x).emod (2^64 : Int) = Int.ofNat x.toNat := by
  unfold u64_toS64
  by_cases h : (x >>> 63) = 1
  · rw [if_pos h]
    have h1 : (Int.ofNat x.toNat - (2^64 : Int)).emod (2^64 : Int)
            = (Int.ofNat x.toNat - (2^64 : Int)) % (2^64 : Int) := rfl
    rw [h1, ofNat_sub_pow_mod]
    exact ofNat_lt_pow_emod x.toNat (UInt64.toNat_lt x)
  · rw [if_neg h]
    exact ofNat_lt_pow_emod x.toNat (UInt64.toNat_lt x)

theorem u64_toS64_ne_zero (b : UInt64) (hb : b ≠ 0) :
    u64_toS64 b ≠ 0 := by
  unfold u64_toS64
  by_cases h : (b >>> 63) = 1
  · rw [if_pos h]
    intro h0
    have heq : Int.ofNat b.toNat = (2^64 : Int) := by omega
    have hn : b.toNat = 2^64 := Int.ofNat_inj.mp heq
    have hlt := UInt64.toNat_lt b
    omega
  · rw [if_neg h]
    intro h0
    have hn : b.toNat = 0 := Int.ofNat_inj.mp h0
    exact hb (UInt64.toNat.inj hn)

theorem s64_to_u64_toNat' (y : Int) :
    (s64_to_u64 y).toNat = (y.emod (2^64 : Int)).toNat := by
  unfold s64_to_u64
  rw [UInt64.toNat_ofNat']
  have hnn : 0 ≤ y.emod (2^64 : Int) := Int.emod_nonneg y (by omega)
  have hlt : y.emod (2^64 : Int) < (2^64 : Int) := Int.emod_lt y (by omega)
  have hto : (y.emod (2^64 : Int)).toNat < 2^64 :=
    (Int.toNat_lt hnn).mpr hlt
  exact Nat.mod_eq_of_lt hto

theorem ofNat_emod (m n : Nat) : Int.ofNat m % Int.ofNat n = Int.ofNat (m % n) := by
  rw [Int.emod_def]
  have hedgeiv : Int.ofNat m / Int.ofNat n = Int.ofNat (m / n) := by
    rw [Int.ediv_eq_tdiv]
    have hnn : 0 ≤ Int.ofNat m := Int.natCast_nonneg m
    rw [if_pos (Or.inl hnn)]
    rw [Int.sub_zero]
    exact Int.ofNat_tdiv m n
  rw [hedgeiv]
  rw [show Int.ofNat n * Int.ofNat (m / n) = Int.ofNat (n * (m / n)) from Int.natCast_mul n (m / n)]
  have hle : n * (m / n) ≤ m := Nat.mul_div_le m n
  have h1 : Int.ofNat m - Int.ofNat (n * (m / n)) = Int.ofNat (m - n * (m / n)) :=
    (Int.ofNat_sub hle).symm
  rw [h1]
  rw [Nat.mod_def]

theorem neg_ofNat_emod (M k : Nat) (hk : 0 < k) (hkM : k ≤ M) :
    (-(Int.ofNat k)) % (Int.ofNat M) = Int.ofNat (M - k) := by
  have hadd : ∀ z : Int, (z + Int.ofNat M) % Int.ofNat M = z % Int.ofNat M := by
    intro z
    calc (z + Int.ofNat M) % Int.ofNat M
        = (z % Int.ofNat M + Int.ofNat M % Int.ofNat M) % Int.ofNat M := Int.add_emod z _ _
      _ = (z % Int.ofNat M + 0) % Int.ofNat M := by rw [Int.emod_self]
      _ = z % Int.ofNat M % Int.ofNat M := by rw [Int.add_zero]
      _ = z % Int.ofNat M := Int.emod_emod z _
  have hcancel' : Int.ofNat M - Int.ofNat k = Int.ofNat (M - k) :=
    (Int.ofNat_sub hkM).symm
  have hcancel : Int.ofNat M + (-(Int.ofNat k)) = Int.ofNat (M - k) := by
    rw [← Int.sub_eq_add_neg]
    exact hcancel'
  have hz : (-(Int.ofNat k)) % Int.ofNat M = (-(Int.ofNat k) + Int.ofNat M) % Int.ofNat M :=
    (hadd (-(Int.ofNat k))).symm
  rw [hz, Int.add_comm, hcancel, ofNat_emod]
  have hlt : M - k < M := by omega
  rw [Nat.mod_eq_of_lt hlt]

theorem wrap_bridge (M a X : Nat) (_hM : 0 < M) (hX : X < M) :
    (M - X + a) % M = ((Int.ofNat a - Int.ofNat X) % Int.ofNat M).toNat := by
  by_cases h : X ≤ a
  · have hsub : Int.ofNat a - Int.ofNat X = Int.ofNat (a - X) :=
      (Int.ofNat_sub h).symm
    rw [hsub, ofNat_emod]
    have hto : (Int.ofNat ((a - X) % M)).toNat = (a - X) % M := rfl
    rw [hto]
    have heq : M - X + a = (a - X) + M := by omega
    rw [heq, Nat.add_mod, Nat.mod_self, Nat.add_zero, Nat.mod_mod]
  · have hlt : a < X := Nat.lt_of_not_ge h
    have hneg : Int.ofNat a - Int.ofNat X = -(Int.ofNat (X - a)) := by
      rw [Int.sub_eq_add_neg]
      have hXa : Int.ofNat X - Int.ofNat a = Int.ofNat (X - a) :=
        (Int.ofNat_sub (Nat.le_of_lt hlt)).symm
      have hneg' : -(Int.ofNat (X - a)) = -(Int.ofNat X - Int.ofNat a) := by
        rw [hXa]
      rw [hneg']
      rw [Int.sub_eq_add_neg, Int.neg_add, Int.neg_neg, Int.add_comm]
    rw [hneg]
    have hk0 : 0 < X - a := by omega
    have hkM : X - a ≤ M := by omega
    rw [neg_ofNat_emod M (X - a) hk0 hkM]
    have hto : (Int.ofNat (M - (X - a))).toNat = M - (X - a) := rfl
    rw [hto]
    have hrewrite : M - X + a = M - (X - a) := by omega
    rw [hrewrite]
    have hlt2 : M - (X - a) < M := by omega
    exact Nat.mod_eq_of_lt hlt2

/-- `a - sdiv64 a b * b = srem64 a b` for signed 64-bit division when `b ≠ 0`.
    Bridges the machine's SDIV/MSUB remainder sequence to the model's `srem64`. -/
theorem srem64_sub (a b : UInt64) (hb : b ≠ 0) :
    a - sdiv64 a b * b = srem64 a b := by
  unfold sdiv64 srem64
  simp [hb]
  apply UInt64.toNat.inj
  rw [UInt64.toNat_sub, UInt64.toNat_mul, s64_to_u64_toNat', s64_to_u64_toNat']
  have heq : ∀ x : Int, x.emod (2^64 : Int) = x % (2^64 : Int) := fun _ => rfl
  rw [heq, heq]
  have hsa : (u64_toS64 a) % (2^64 : Int) = Int.ofNat a.toNat := by
    rw [← heq]; exact u64_toS64_mod a
  have hsb : (u64_toS64 b) % (2^64 : Int) = Int.ofNat b.toNat := by
    rw [← heq]; exact u64_toS64_mod b
  have hsb0 : u64_toS64 b ≠ 0 := u64_toS64_ne_zero b hb
  have hr : (u64_toS64 a).tmod (u64_toS64 b)
          = u64_toS64 a - u64_toS64 b * (u64_toS64 a).tdiv (u64_toS64 b) :=
    Int.tmod_def _ _
  rw [hr, Int.sub_emod, hsa]
  have hmul : (u64_toS64 b * (u64_toS64 a).tdiv (u64_toS64 b)) % (2^64 : Int)
            = (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int) := by
    rw [Int.mul_emod, hsb]
  rw [hmul]
  have hQnn : 0 ≤ (u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int) :=
    Int.emod_nonneg _ (by omega)
  have hQlt : (u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int) < (2^64 : Int) :=
    Int.emod_lt _ (by omega)
  have hQto : ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat < 2^64 :=
    (Int.toNat_lt hQnn).mpr hQlt
  have hnnb : 0 ≤ Int.ofNat b.toNat := Int.natCast_nonneg _
  have hnnm : 0 ≤ (2^64 : Int) := by omega
  have hneM : (2^64 : Int) ≠ 0 := by omega
  have hprod : (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int)
             = Int.ofNat ((b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat) % 2^64) := by
    have hmul_nn : 0 ≤ Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)) :=
      Int.mul_nonneg hnnb hQnn
    have hprod_nn : 0 ≤ (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int) :=
      Int.emod_nonneg _ hneM
    have hprod_lt : (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int) < (2^64 : Int) :=
      Int.emod_lt _ hneM
    have hto_lt : ((Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int)).toNat < 2^64 :=
      (Int.toNat_lt hprod_nn).mpr hprod_lt
    have ht1 : ((Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int)).toNat
             = (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))).toNat % (2^64 : Int).toNat :=
      Int.toNat_emod hmul_nn hnnm
    have ht2 : (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))).toNat
             = b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat :=
      Int.toNat_mul hnnb hQnn
    have ht3 : (2^64 : Int).toNat = 2^64 := rfl
    have htoNat_eq : (Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int)
                   = Int.ofNat (((Int.ofNat b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int))) % (2^64 : Int)).toNat) := by
      exact (Int.toNat_of_nonneg hprod_nn).symm
    rw [htoNat_eq, ht1, ht2, ht3]
  rw [hprod]
  have hcomm : ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat * b.toNat
             = b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat :=
    Nat.mul_comm _ _
  rw [hcomm]
  have hX : b.toNat * ((u64_toS64 a).tdiv (u64_toS64 b) % (2^64 : Int)).toNat % 2^64 < 2^64 :=
    Nat.mod_lt _ (by omega)
  exact wrap_bridge _ _ _ (by omega) hX

/-! ## Straight-line run pc-avoidance (the `*_mid` obligation)

  A block's `*_mid` lemma must show that running fewer than its instruction
  count never lands on the exit pc.  Stating that as a right-associated
  conjunction of per-pc disequalities (`p₀ ≠ exit ∧ p₁ ≠ exit ∧ …`) forces Lean
  to synthesise a single `Decidable` instance for the whole nested `And`, and
  that synthesis fails once a block runs past ~40 instructions — `native_decide`
  fails identically, since it synthesises the same instance.

  So the hypothesis is stated over the *list* of visited pcs instead.  Proving
  `∀ p ∈ [p₀, p₁, …], p ≠ exit` rewrites the membership to a disjunction and
  closes each ground leaf, which is depth-1 work per leaf and therefore scales
  with block length. -/

/-- The pc-avoidance hypothesis for a straight-line run visiting `pcs`. -/
theorem work_mid_hk {exit pc : Nat} {pcs : List Nat}
    (hexit : ∀ p ∈ pcs, p ≠ exit) (hmem : pc ∈ pcs) : pc ≠ exit :=
  hexit pc hmem

/-- `simp`-dischargeable form of `work_mid_hk` for a literal run. -/
theorem work_mid_hk_of_mem {exit pc : Nat} {pcs : List Nat}
    (hexit : ∀ p ∈ pcs, p ≠ exit) (hmem : pc ∈ pcs) : pc ≠ exit :=
  work_mid_hk hexit hmem

/-- A chain of `ADD Xd, Xn, #imm` / `SUB Xd, Xn, #imm` on the stack pointer
    moves `sp` by the sum of the immediates.

    This is the generic form of the identity the loop-contract slot lemmas
    need.  The emitter splits a large frame adjustment into `imm12`-sized
    chunks (32 × `SUB sp, #4095` plus a remainder), and the loop generators
    previously closed the resulting 34-term chain with `grind` against a
    *hardcoded* expected total.  When the frame layout moved on (the scratch
    grew, the pair count changed) that literal went stale, `grind` failed, and
    — worse — the statement being closed was simply false.

    Stating it as a fold over the emitted chunk list removes both problems: the
    total is whatever the emitter's chunks sum to, so it cannot go stale, and
    the proof is one induction rather than a 34-term linear-arithmetic blast.
    No no-wrap side condition is needed: `u64_ofNat_add` holds unconditionally
    because `UInt64` addition is mod 2^64 and the total is a `Nat` literal
    reduced the same way. -/
theorem u64_sp_add_chunks (sp : UInt64) (chunks : List Nat) (total : Nat)
    (hsum : chunks.sum = total) :
    chunks.foldl (fun a b => a + UInt64.ofNat b) sp = sp + UInt64.ofNat total := by
  -- Lean core has no `foldl`-distributes-over-`+` lemma, so prove the one
  -- shape needed here: folding `+ ofNat` into a nonzero base agrees with
  -- folding into zero and then adding the base.
  have foldl_base : ∀ (l : List Nat) (s : UInt64),
      l.foldl (fun a b => a + UInt64.ofNat b) s
        = s + l.foldl (fun a b => a + UInt64.ofNat b) (0 : UInt64) := by
    intro l
    induction l with
    | nil => intro s; simp
    | cons c cs ih =>
        intro s
        simp only [List.foldl_cons]
        rw [ih]
        grind
  induction chunks generalizing sp total with
  | nil => simp only [List.foldl_nil, List.sum_nil] at hsum ⊢; subst hsum; simp
  | cons c cs ih =>
      simp only [List.foldl_cons, List.sum_cons] at hsum ⊢
      have h1 := ih (sp := sp + UInt64.ofNat c) (total := cs.sum) (by simp)
      rw [h1]
      calc (sp + UInt64.ofNat c) + UInt64.ofNat cs.sum
          = sp + (UInt64.ofNat c + UInt64.ofNat cs.sum) := UInt64.add_assoc _ _ _
        _ = sp + UInt64.ofNat (c + cs.sum) := by rw [u64_ofNat_add]
        _ = sp + UInt64.ofNat total := by rw [hsum]

def work_export_names (exports : List DylibExport) : List String :=
  exports.map DylibExport.symbol

theorem work_export_names_length (exports : List DylibExport) :
    (work_export_names exports).length = exports.length := by
  simp [work_export_names]
