import ProofLib
import IEEE754
set_option maxRecDepth 10000

open IEEE754

/-!
# ProofLibSteps1: `work_step_*` routing lemmas (work_step_ret .. work_step_movk)

Shard 1 of 8. The `work_step_*` theorems (one per `arm64_step` arm) depend
only on `ProofLib`'s definitions and never on each other, and they are where
almost all of the library's elaboration time goes (about 2,500 `bv_decide`
calls, ~85 minutes in one file against ~100 seconds for everything else). Split
into shards that import only `ProofLib` they build in parallel
(`formal/lean.py::ensure_library`). `ProofLibSteps` re-exports all of them, so a
proof that wants the lemmas writes `import ProofLibSteps`.
-/

/-- Per-instruction step: `work_step_ret`. -/
theorem work_step_ret (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : w = (0xd65f03c0 : UInt32)) :
    arm64_step s code = some { s with pc := s.x30.toNat } := by
  unfold arm64_step
  rw [hpc, hread]
  rw [if_pos h]

/-- Per-instruction step: `work_step_mov`. -/
theorem work_step_mov (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x2a00fa00) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  rw [if_neg hne_ret, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_reg`. -/
theorem work_step_add_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x8b000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s + arm64_shifted_reg w s (((w >>> 16) &&& 0x1f).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_reg`. -/
theorem work_step_sub_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xcb000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s - arm64_shifted_reg w s (((w >>> 16) &&& 0x1f).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_mul`. -/
theorem work_step_mul (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe07c00) = 0x9b007c00) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s * arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_neg`. -/
theorem work_step_neg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xfffffc1f) = 0xcb0003e0) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (-(arm64_reg (((w >>> 16) &&& 0x1f).toNat) s))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_cmp_reg`. -/
theorem work_step_cmp_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xeb000000) :
arm64_step s code = some { (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s - arm64_shifted_reg w s (((w >>> 16) &&& 0x1f).toNat))) with
      nzcv := arm64_subs_flags (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) (arm64_shifted_reg w s (((w >>> 16) &&& 0x1f).toNat)) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_and`. -/
theorem work_step_and (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x8a000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s &&& arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_eor`. -/
theorem work_step_eor (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xca000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s ^^^ arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_imm32`. -/
theorem work_step_add_imm32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x11000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s + UInt64.ofNat (arm64_ext_imm12 w))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_imm64`. -/
theorem work_step_add_imm64 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x91000000) :
    arm64_step s code = (if ((w &&& 0x1f).toNat) = 31 then some { s with sp := (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (arm64_ext_imm12 w) } else some (arm64_set_reg ((w &&& 0x1f).toNat) s ((arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (arm64_ext_imm12 w)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_imm32`. -/
theorem work_step_sub_imm32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x51000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s - UInt64.ofNat (arm64_ext_imm12 w))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_imm64`. -/
theorem work_step_sub_imm64 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xd1000000) :
    arm64_step s code = (if ((w &&& 0x1f).toNat) = 31 then some { s with sp := (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat (arm64_ext_imm12 w) } else some (arm64_set_reg ((w &&& 0x1f).toNat) s ((arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat (arm64_ext_imm12 w)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_cmp_imm`. -/
theorem work_step_cmp_imm (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xf1000000) :
    arm64_step s code = some { s with nzcv := arm64_subs_flags (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) (UInt64.ofNat (arm64_ext_imm12 w)) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_ldr_uoff`.

    `LDR Xt, [Xn, #imm]` (0xF9400000): `Xt := mem64[Xn + imm]`, and NOTHING
    else moves -- in particular `sp` does not, which is the whole point.  The
    base is the instruction's `Rn`, not `SP`.

    Named `_uoff` (unsigned offset) to match the A64 encoding, which is the
    name `formal/arm64_proof_gen.py`'s `_WORK_STEP` table dispatches on. -/
theorem work_step_ldr_uoff (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xf9400000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem
      ((arm64_reg_or_sp ((w >>> 5) &&& 0x1f).toNat) s
        + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_str_uoff32`.

    `STR Wt, [Xn, #imm]` (0xB9000000): `mem32[Xn + imm*4] := Wt`, and nothing
    else moves -- in particular neither `Rt` nor `sp`.  The base is the
    instruction's `Rn`, and the scale is 4 not 8 because this is the 32-bit
    form.  This replaces `work_step_ldr_post`, which asserted a post-index
    *load* from `SP`; see the `arm64_step` case it routes to. -/
theorem work_step_str_uoff32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xb9000000) :
    arm64_step s code = some { s with
      mem := mem_write_u32 s.mem
        ((arm64_reg_or_sp ((w >>> 5) &&& 0x1f).toNat) s
          + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 4)).toNat
        (arm64_reg ((w &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_adrp`. -/
theorem work_step_adrp (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0x9f000000) = 0x90000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat pc - (UInt64.ofNat pc) % (4096 : UInt64) + (if ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat) ≥ 2^20 then UInt64.ofNat ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat) - UInt64.ofNat (2^21) else UInt64.ofNat ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat)) * (4096 : UInt64))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_stp`. -/
theorem work_step_stp (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffc00000) = 0xa9800000) :
    arm64_step s code = some { s with sp := (if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)), mem := mem_write_u64 (mem_write_u64 s.mem (if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)).toNat (arm64_reg ((w &&& 0x1f).toNat) s)) ((if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)) + 8).toNat (arm64_reg (((w >>> 10) &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_ldp_post`. -/
theorem work_step_ldp_post (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffc00000) = 0xa8c00000) :
    arm64_step s code = some { (arm64_set_reg (((w >>> 10) &&& 0x1f).toNat) (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s).toNat)) (mem_read_u64 s.mem ((arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + 8).toNat)) with sp := (arm64_reg_or_sp (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movz`. -/
theorem work_step_movz (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x52800000 ∨ (w &&& 0xffe00000) = 0xd2800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat (((w >>> 5) &&& 0xffff).toNat))) := by
  rcases h with h | h
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
    have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
    have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_orr`. -/
theorem work_step_orr (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xaa000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s ||| arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movk`. -/
theorem work_step_movk (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xf2800000 ∨ (w &&& 0xff800000) = 0x72800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s
      (movk_insert (arm64_reg ((w &&& 0x1f).toNat) s)
        (UInt64.ofNat (((w >>> 5) &&& 0xffff).toNat))
        (UInt64.ofNat ((((w >>> 21) &&& 0x3).toNat) * 16)))) := by
  rcases h with h | h
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
    have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
    have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
    have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
    have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    have hne_tbz : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
    have hne_tbnz : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_pos h, if_neg hne_bcond, if_neg hne_tbz, if_neg hne_tbnz]; try dsimp; try rfl; try simp
