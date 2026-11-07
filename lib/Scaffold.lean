import ProofLib
import X86
import Peephole

/-!
# Scaffold.lean — the ONLY home of scaffold `sorry` in `lib/`

This module exists so that holes in the Lean library can be counted honestly.
The invariant is strict:

- **The ONLY file in `lib/` allowed to contain `sorry`.** Every other library
  module (`ProofLib`, `X86`, `Peephole`, `work`, `Refine`, `Contracts`, `Specs`,
  `IEEE754`) must remain sorry-free. `lib/Peephole.lean`'s header promises "every
  theorem below is proved, and there is no `sorry`", and `formal/peephole.py`'s
  licence check depends on it.
- **Holes are ledgered.** Every theorem in this module that ends in `by sorry`
  must appear in `formal/proof_gaps.py::SCAFFOLD_HOLES`. The census test
  `test_formal_proof_gaps.py` enforces this from `formal.lean::library_census`
  (which measures elaborated holes, not text scans).
- **Promotion procedure:** prove the theorem, move it to its home module
  (`Peephole.lean`, `ProofLib.lean`, `X86.lean`, etc.), and delete its ledger row.
  A scaffolded theorem is never moved into `Peephole.lean` while it still contains
  `sorry` (that would license peephole rules prematurely).

This module is imported by NOTHING and is appended LAST to
`formal.lean::LIBRARY_MODULES`. A hole here cannot propagate into generated
proofs or other library theorems.
-/

set_option autoImplicit false

/-- Positive control for the census; delete when the first real scaffold lands. -/
theorem scaffold_canary : True := by sorry

/-- **Rule `arm64/movz_pair`.** Two `MOVZ Xd,#i ; MOVZ Xd,#j` with same `Xd`:
deleting the first and keeping the second is sound. -/
theorem peephole_arm64_movz_pair (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (h1 : (w1 &&& 0xffe00000) = 0xD2800000)
    (h2 : (w2 &&& 0xffe00000) = 0xD2800000)
    (hrd1 : (w1 &&& 0x1f).toNat < 31)
    (hrd2 : (w2 &&& 0x1f).toNat < 31)
    (heq : (w1 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (s1 s2 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 }) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s1)
    ∧ s2.nzcv = s1.nzcv
    ∧ s2.mem = s1.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s1 with pc := pc + 4 } := by
  sorry

/-- **Rule `arm64/mem_pair_str`.** Two identical `STR Xt,[Xn,#o]` instructions:
deleting the second is sound by idempotence of the store. -/
theorem peephole_arm64_str_pair (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (h1 : (w1 &&& 0xffe00000) = 0xF9000000)
    (h2 : (w2 &&& 0xffe00000) = 0xF9000000)
    (hrt1 : (w1 &&& 0x1f).toNat < 31)
    (hrt2 : (w2 &&& 0x1f).toNat < 31)
    (hrn_eq : ((w1 >>> 5) &&& 0x1f).toNat = ((w2 >>> 5) &&& 0x1f).toNat)
    (hrt_eq : (w1 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (himm_eq : ((w1 >>> 10) &&& 0xfff).toNat = ((w2 >>> 10) &&& 0xfff).toNat)
    (s1 s2 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 }) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s1)
    ∧ s2.nzcv = s1.nzcv
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s1 with pc := pc + 4 } := by
  sorry

/-- Scaffold: write-back contract for a by-reference one-field mutator (single exit).
    Depth bound is a hypothesis, not an axiom. The cell is in the caller's frame. -/
theorem scaffold_cell_writeback_one_exit
    (s s' : Arm64State) (p : UInt64)
    (h_cell : True) :
    True := by sorry

/-- Scaffold: write-back contract for a by-reference one-field mutator (multiple exits).
    Per-exit obligation is scaffolded as a hole pending proof. Depth bound is a hypothesis. -/
theorem scaffold_cell_writeback_multi_exit
    (s s' : Arm64State) (p : UInt64)
    (h_cell : True) :
    True := by sorry

/-- **Rule `arm64/mem_pair_ldr`.** Two identical `LDR Xt,[Xn,#o]` with `Xt ≠ Xn`:
the base is unchanged and memory unchanged, so second load is redundant. -/
theorem peephole_arm64_ldr_pair (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (h1 : (w1 &&& 0xffe00000) = 0xF9400000)
    (h2 : (w2 &&& 0xffe00000) = 0xF9400000)
    (hrt1 : (w1 &&& 0x1f).toNat < 31)
    (hrt2 : (w2 &&& 0x1f).toNat < 31)
    (hrn_eq : ((w1 >>> 5) &&& 0x1f).toNat = ((w2 >>> 5) &&& 0x1f).toNat)
    (hrt_eq : (w1 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (himm_eq : ((w1 >>> 10) &&& 0xfff).toNat = ((w2 >>> 10) &&& 0xfff).toNat)
    (hne_rt_rn : (w1 &&& 0x1f).toNat ≠ ((w1 >>> 5) &&& 0x1f).toNat)
    (s1 s2 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 }) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s1)
    ∧ s2.nzcv = s1.nzcv
    ∧ s2.mem = s1.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s1 with pc := pc + 4 } := by
  sorry

/-- **Rule `arm64/store_load`.** `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]` with same
location and register: deleting the second is sound. -/
theorem peephole_arm64_store_load (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (h1 : (w1 &&& 0xffe00000) = 0xF9000000)
    (h2 : (w2 &&& 0xffe00000) = 0xF9400000)
    (hrt1 : (w1 &&& 0x1f).toNat < 31)
    (hrt2 : (w2 &&& 0x1f).toNat < 31)
    (hrn_eq : ((w1 >>> 5) &&& 0x1f).toNat = ((w2 >>> 5) &&& 0x1f).toNat)
    (hrt_eq : (w1 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (himm_eq : ((w1 >>> 10) &&& 0xfff).toNat = ((w2 >>> 10) &&& 0xfff).toNat)
    (s1 s2 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 }) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s1)
    ∧ s2.nzcv = s1.nzcv
    ∧ s2.mem = s1.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s1 with pc := pc + 4 } := by
  sorry

/-- **Scaffold (step-04d):** `add r,0` / `sub r,0` leave `cf = false`, `of_ = false`,
and `zf`/`sf` equal to the flags of `r` (from `x86_flags_add`/`x86_flags_sub`).
Statement left here as a scaffold; the pass cannot yet use it soundly without a
continuation predicate (design recorded in `Peephole.lean`). -/
theorem peephole_x86_imm_zero_flags (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x81)
    (h_b2 : code (m + 2) = modrm)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 3)
    (h_digit : (modrm.toNat >>> 3) &&& 7 = 0 ∨ (modrm.toNat >>> 3) &&& 7 = 5)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_imm : read_i32_le code (m + 3) = 0)
    (t : X86State) (hs : x86_step s code = some t) :
    t.cf = false ∧ t.of_ = false ∧ t.zf = (x86_get_reg s (rm + x86_rex_b rex) = 0)
    ∧ t.sf = x86_msb (x86_get_reg s (rm + x86_rex_b rex)) := by
  sorry


/-! ## x86-64 memory rules (steps 04a-04c)

Common shape: the pair starts at `m`, both instructions are the disp8 form
(`REX.W 89|8b /r`, `mod = 1`, `rm ≠ 4`, so no SIB byte and no RIP-relative
operand), four bytes each. The conclusion is stated as the pair's final state
`t2` equalling the FIRST instruction's final state `t1` with the pc advanced
past BOTH (`m + 8`), which is what the rewrite (delete the second) needs.
Proof route for the promotion commit, using lemmas that already exist:
`x86_step_mov_mem_disp8` (X86.lean:3031) for the store,
`x86_step_mov_rm64_mem_disp8` (:2950) for the load,
`mem_read_bytes_write_same` (:3694), `x86_set_reg_self` (Peephole.lean) and
`x86_get_reg_set_reg_other` (Peephole.lean). Stores additionally need write
idempotence at width 8 (`mem_write_bytes` applied twice at one address). -/

/-- **Scaffold (step-04b), rule `x86_64/store_load`.** `mov [b+d8], r ; mov r, [b+d8]`
is the store alone. No condition relating `r` and `b`: the load's address is
computed from the state after the store, which changed memory and `rip` only. -/
theorem peephole_x86_store_load_disp8 (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat) (disp : Int)
    (h_rip : s.rip = m)
    (h_s0 : code m = rex) (h_s1 : code (m + 1) = 0x89)
    (h_s2 : code (m + 2) = modrm) (h_sd : read_i8 (code (m + 3)) = disp)
    (h_l0 : code (m + 4) = rex) (h_l1 : code (m + 5) = 0x8b)
    (h_l2 : code (m + 6) = modrm) (h_ld : read_i8 (code (m + 7)) = disp)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 1) (h_rm : modrm.toNat &&& 7 = rm)
    (h_rm_ne : rm ≠ 4)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_dst_lt : reg + x86_rex_r rex < 16)
    (t1 t2 : X86State)
    (hs1 : x86_step s code = some t1) (hs2 : x86_step t1 code = some t2) :
    t2 = { t1 with rip := m + 8 } := by
  sorry

/-- **Scaffold (step-04c), rule `x86_64/mem_pair_store`.** Two identical
`mov [b+d8], r`: the second writes the same value to the same address. -/
theorem peephole_x86_store_pair_disp8 (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat) (disp : Int)
    (h_rip : s.rip = m)
    (h_s0 : code m = rex) (h_s1 : code (m + 1) = 0x89)
    (h_s2 : code (m + 2) = modrm) (h_sd : read_i8 (code (m + 3)) = disp)
    (h_t0 : code (m + 4) = rex) (h_t1 : code (m + 5) = 0x89)
    (h_t2 : code (m + 6) = modrm) (h_td : read_i8 (code (m + 7)) = disp)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 1) (h_rm : modrm.toNat &&& 7 = rm)
    (h_rm_ne : rm ≠ 4)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (t1 t2 : X86State)
    (hs1 : x86_step s code = some t1) (hs2 : x86_step t1 code = some t2) :
    t2 = { t1 with rip := m + 8 } := by
  sorry

/-- **Scaffold (step-04c), rule `x86_64/mem_pair_load`.** Two identical
`mov r, [b+d8]`. UNSOUND without `r ≠ b` (the first load overwrites the base),
which is hypothesis `h_ne`; the pass-side matcher must check it too. -/
theorem peephole_x86_load_pair_disp8 (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat) (disp : Int)
    (h_rip : s.rip = m)
    (h_s0 : code m = rex) (h_s1 : code (m + 1) = 0x8b)
    (h_s2 : code (m + 2) = modrm) (h_sd : read_i8 (code (m + 3)) = disp)
    (h_t0 : code (m + 4) = rex) (h_t1 : code (m + 5) = 0x8b)
    (h_t2 : code (m + 6) = modrm) (h_td : read_i8 (code (m + 7)) = disp)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 1) (h_rm : modrm.toNat &&& 7 = rm)
    (h_rm_ne : rm ≠ 4)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_dst_lt : reg + x86_rex_r rex < 16)
    (h_ne : reg + x86_rex_r rex ≠ rm + x86_rex_b rex)
    (t1 t2 : X86State)
    (hs1 : x86_step s code = some t1) (hs2 : x86_step t1 code = some t2) :
    t2 = { t1 with rip := m + 8 } := by
  sorry
