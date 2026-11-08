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
