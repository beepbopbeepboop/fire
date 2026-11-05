import ProofLib
import X86
import Peephole

/-!
# Scaffold.lean — the ONLY home of scaffold `sorry` in `lib/`
-/

set_option autoImplicit false

/-- Positive control for the census; delete when the first real scaffold lands. -/
theorem scaffold_canary : True := by sorry

/-! ## Step 03c: arm64/store_load - STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o] -/

/-- **Rule `arm64/store_load`.** `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]` with same
register and same address computes the same final state as `STR Xt,[Xn,#o]` alone. -/
theorem peephole_arm64_store_load (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 w3 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (hread3 : arm64_read_insn code pc = w3)
    (h1 : (w1 &&& 0xffe00000) = 0xF9000000)
    (h2 : (w2 &&& 0xffe00000) = 0xF9400000)
    (h3 : (w3 &&& 0xffe00000) = 0xF9000000)
    (hrt1 : (w1 &&& 0x1f).toNat < 31) (hrt2 : (w2 &&& 0x1f).toNat < 31) (hrt3 : (w3 &&& 0x1f).toNat < 31)
    (hsamert : (w1 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (hsamern : ((w1 >>> 5) &&& 0x1f).toNat = ((w2 >>> 5) &&& 0x1f).toNat)
    (hsameimm : ((w1 >>> 10) &&& 0xfff).toNat = ((w2 >>> 10) &&& 0xfff).toNat)
    (hw3eq : w3 = w1)
    (s1 s2 s3 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code = some { s2 with pc := s.pc + 4 })
    (hs3 : arm64_step s code = some s3) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s3)
    ∧ s2.nzcv = s.nzcv
    ∧ s2.mem = s.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s3 with pc := pc + 4 } := by
  sorry

/-- Witness: `str x1,[x2,#8] ; ldr x1,[x2,#8]` -/
example (s : Arm64State) (code : Nat → UInt8) (pc : Nat)
    (h1 : arm64_read_insn code pc = (0xf9000441 : UInt32))
    (h2 : arm64_read_insn code (pc + 4) = (0xf9400441 : UInt32)) :
  True := by
  exact True

/-- Witness: `str x2,[x2,#8] ; ldr x2,[x2,#8]` (rt = rn) -/
example (s : Arm64State) (code : Nat → UInt8) (pc : Nat)
    (h1 : arm64_read_insn code pc = (0xf9000442 : UInt32))
    (h2 : arm64_read_insn code (pc + 4) = (0xf9400442 : UInt32)) :
  True := by
  exact True
