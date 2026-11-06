import ProofLib
import IEEE754
set_option maxRecDepth 10000

open IEEE754

/-!
# ProofLibSteps7: `work_step_*` routing lemmas (work_step_strb .. work_step_ldrsw)

Shard 7 of 8. The `work_step_*` theorems (one per `arm64_step` arm) depend
only on `ProofLib`'s definitions and never on each other, and they are where
almost all of the library's elaboration time goes (about 2,500 `bv_decide`
calls, ~85 minutes in one file against ~100 seconds for everything else). Split
into shards that import only `ProofLib` they build in parallel
(`formal/lean.py::ensure_library`). `ProofLibSteps` re-exports all of them, so a
proof that wants the lemmas writes `import ProofLibSteps`.
-/

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 55 of them, the 55 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_strb (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0x39000000) :
    arm64_step s code = some { s with mem := mem_write_u8 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat)).toNat (arm64_reg ((w &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldrh`.

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 56 of them, the 56 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_ldrh (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0x79400000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u16 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 2)).toNat)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = 0x39000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_strh`.

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 57 of them, the 57 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_strh (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0x79000000) :
    arm64_step s code = some { s with mem := mem_write_u16 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 2)).toNat (arm64_reg ((w &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = 0x39000000) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = 0x79400000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldrsb`.

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 58 of them, the 58 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_ldrsb (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0x39800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (t8s (mem_read_u8 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat)).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = 0x39000000) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = 0x79400000) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = 0x79000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldrsh`.

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 59 of them, the 59 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_ldrsh (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0x79800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (t16s (mem_read_u16 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 2)).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = 0x39000000) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = 0x79400000) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = 0x79000000) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = 0x39800000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldrsw`.

    One of the twelve narrower/unscaled access forms APPENDED to `arm64_step`;
    the comment above them there says why they sit at the END of the chain rather
    than in the architectural position.  This lemma is the half of that decision
    which is visible: it states the `¬` fact for **every** branch before this
    one — 60 of them, the 60 earlier arms plus the equality test — and each is
    a `bv_decide` over the hypothesis `h` and all 2^32 words of `w`.  So these
    lemmas ARE the measurement that no earlier branch claims these words:
    they would not typecheck if one did. -/
theorem work_step_ldrsw (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffd00000) = 0xb9800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (t32s (mem_read_u32 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 4)).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = 0x2A00FA00) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = 0x36000000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = 0x37000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = 0xF9400000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = 0xB9000000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = 0xA9800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = 0xA8C00000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0xF9000000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = 0xA9400000) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = 0xAA200000) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = 0xD61F0000) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = 0xD4000001) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = 0x13001c00) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = 0x13003c00) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = 0x93407c00) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = 0x92401c00) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = 0x92403c00) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = 0x92407c00) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00800) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = 0x9ac00c00) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02000) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02400) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = 0x9ac02800) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = 0x9b008000) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = 0xd340fc00) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = 0x9340fc00) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = 0xd3400000) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = 0x39400000) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = 0x39000000) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = 0x79400000) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = 0x79000000) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = 0x39800000) := by intro t; bv_decide
  have hne_59 : ¬ ((w &&& 0xffd00000) = 0x79800000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_neg hne_59, if_pos h]; try dsimp; try rfl; try simp
set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldr_uoff32`.
