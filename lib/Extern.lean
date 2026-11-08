import ProofLib

/-!
# Extern.lean — contracts for calls that leave the image, as HYPOTHESES

An extern callee (`strlen`, ...) is outside the image, so the model cannot run it
(`arm64_step` has no arm there).  What a proof can say about it is conditional on
the callee obeying its calling convention and its documented behaviour.  Those
conditions are stated here as `structure`s a generated theorem takes as a PREMISE
(never an axiom, never a `sorry`): the assumption sits in the theorem's signature
where the reader sees it.

This module has no `sorry` (it is not `Scaffold`) and depends on `ProofLib` only.
-/

/-- The NUL-terminated byte run at `addr` in `mem` has length `n`. -/
def cstring_at (mem : Nat → UInt8) (addr n : Nat) : Prop :=
  (∀ i, i < n → mem (addr + i) ≠ 0) ∧ mem (addr + n) = 0

theorem cstring_at_unique (mem : Nat → UInt8) (addr n m : Nat)
    (hn : cstring_at mem addr n) (hm : cstring_at mem addr m) : n = m := by
  rcases Nat.lt_trichotomy n m with h | h | h
  · exact absurd hn.2 (hm.1 n h)
  · exact h
  · exact absurd hm.2 (hn.1 m h)

/-- What returning from an extern call to `ret` means for the caller's state: the
    AAPCS64 callee-saved registers, `sp` and memory are as the caller left them. -/
structure ExternReturn (s s' : Arm64State) : Prop where
  pc_ret : s'.pc = s.x30.toNat
  sp_same : s'.sp = s.sp
  x19_same : s'.x19 = s.x19
  x20_same : s'.x20 = s.x20
  x29_same : s'.x29 = s.x29
  mem_same : s'.mem = s.mem

/-- The `strlen` contract as a HYPOTHESIS (never an axiom): `s` is the state at the
    callee's entry (after the `BL`), `s'` the state at its return. -/
structure StrlenReturns (s s' : Arm64State) (addr n : Nat) : Prop where
  ret : ExternReturn s s'
  arg : s.x0.toNat = addr
  str : cstring_at s.mem addr n
  res : s'.x0 = UInt64.ofNat n

theorem strlen_returns_len (s s' : Arm64State) (addr n : Nat)
    (h : StrlenReturns s s' addr n) : s'.x0 = UInt64.ofNat n := h.res

theorem strlen_result_unique (s s' s'' : Arm64State) (addr n m : Nat)
    (h : StrlenReturns s s' addr n) (h2 : StrlenReturns s s'' addr m) :
    n = m := cstring_at_unique s.mem addr n m h.str h2.str

/-! ## The epilogue after an extern call, over an ABSTRACT post-call state

The theorems a generated proof states about what follows a `BL` to an extern
(`<name>_post_extern_strlen_returns`) walk a short epilogue (`add sp`, `ldp`,
`ret`) from a state `s_ret` that is only known through its contract.  These are
the generic pieces: one `arm64_go_exit` iteration over a step that leaves `pc`
where it was, and the projections of a register write that the walk needs.
-/

/-- One `arm64_go_exit` iteration over a step that leaves `pc` where it was (the
    model's `arm64_step` does not advance it; the loop adds 4). -/
theorem go_exit_step_adv (st st' : Arm64State) (code : Nat → UInt8) (exit fuel : Nat)
    (hne : st.pc ≠ exit) (h : arm64_step st code = some st') (hpc : st'.pc = st.pc) :
    arm64_go_exit st code exit (fuel + 1) =
      arm64_go_exit { st' with pc := st.pc + 4 } code exit fuel := by
  have hf : ¬ (fuel + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hf, if_neg hne, h]
  simp only [hpc, if_true, Nat.add_sub_cancel]

theorem set_reg_pc_keeps (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).pc = s.pc := by
  unfold arm64_set_reg
  split <;> simp_all

theorem set_reg_mem_keeps (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).mem = s.mem := by
  unfold arm64_set_reg
  split <;> simp_all

theorem set_reg_sp_keeps (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).sp = s.sp := by
  unfold arm64_set_reg
  split <;> simp_all

theorem set_reg_x0_keeps (i : Nat) (hi : i ≠ 0) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).x0 = s.x0 := by
  unfold arm64_set_reg
  split <;> simp_all

theorem set_reg_x30_same (s : Arm64State) (v : UInt64) :
    (arm64_set_reg 30 s v).x30 = v := by
  unfold arm64_set_reg
  simp
