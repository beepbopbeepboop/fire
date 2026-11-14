import ProofLib
import IEEE754
set_option maxRecDepth 10000

open IEEE754

/-!
# ProofLibSteps3: `work_step_*` routing lemmas (work_step_tst .. work_step_smulh)

Shard 3 of 8. The `work_step_*` theorems (one per `arm64_step` arm) depend
only on `ProofLib`'s definitions and never on each other, and they are where
almost all of the library's elaboration time goes (about 2,500 `bv_decide`
calls, ~85 minutes in one file against ~100 seconds for everything else). Split
into shards that import only `ProofLib` they build in parallel
(`formal/lean.py::ensure_library`). `ProofLibSteps` re-exports all of them, so a
proof that wants the lemmas writes `import ProofLibSteps`.
-/

set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_tst`. -/
theorem work_step_tst (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xea000000) :
    arm64_step s code = some { s with nzcv := arm64_logic_flags (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s &&& arm64_shifted_reg w s (((w >>> 16) &&& 0x1f).toNat)) } := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = (0x2a00fa00 : UInt32)) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = (0x8b000000 : UInt32)) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = (0xcb000000 : UInt32)) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = (0x9b007c00 : UInt32)) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = (0xcb0003e0 : UInt32)) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = (0xeb000000 : UInt32)) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = (0x8a000000 : UInt32)) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = (0xca000000 : UInt32)) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = (0x91000000 : UInt32)) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = (0x51000000 : UInt32)) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = (0xd1000000 : UInt32)) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = (0xf1000000 : UInt32)) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = (0x14000000 : UInt32)) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = (0x94000000 : UInt32)) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = (0xb4000000 : UInt32)) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = (0xb5000000 : UInt32)) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = (0x54000000 : UInt32)) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = (0x36000000 : UInt32)) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = (0x37000000 : UInt32)) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = (0xf9400000 : UInt32)) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = (0xb9000000 : UInt32)) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = (0x90000000 : UInt32)) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = (0xa9800000 : UInt32)) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = (0xa8c00000 : UInt32)) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = (0x52800000 : UInt32)) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = (0xd2800000 : UInt32)) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = (0xaa000000 : UInt32)) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = (0xf2800000 : UInt32)) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = (0x72800000 : UInt32)) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = (0x12800000 : UInt32)) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = (0x92800000 : UInt32)) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = (0x9a9f07e0 : UInt32)) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = (0xf9000000 : UInt32)) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = (0xa9400000 : UInt32)) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = (0xaa200000 : UInt32)) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = (0xd61f0000 : UInt32)) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = (0xd4000001 : UInt32)) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = (0x13001c00 : UInt32)) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = (0x13003c00 : UInt32)) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = (0x93407c00 : UInt32)) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = (0x92401c00 : UInt32)) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = (0x92403c00 : UInt32)) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = (0x92407c00 : UInt32)) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00800 : UInt32)) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00c00 : UInt32)) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02000 : UInt32)) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02400 : UInt32)) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02800 : UInt32)) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = (0x9b008000 : UInt32)) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = (0xd340fc00 : UInt32)) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = (0x9340fc00 : UInt32)) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = (0xd3400000 : UInt32)) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = (0x39400000 : UInt32)) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = (0x39000000 : UInt32)) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = (0x79400000 : UInt32)) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = (0x79000000 : UInt32)) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = (0x39800000 : UInt32)) := by intro t; bv_decide
  have hne_59 : ¬ ((w &&& 0xffd00000) = (0x79800000 : UInt32)) := by intro t; bv_decide
  have hne_60 : ¬ ((w &&& 0xffd00000) = (0xb9800000 : UInt32)) := by intro t; bv_decide
  have hne_61 : ¬ ((w &&& 0xffd00000) = (0xb9400000 : UInt32)) := by intro t; bv_decide
  have hne_62 : ¬ ((w &&& 0xffe0fc00) = (0xf8606800 : UInt32)) := by intro t; bv_decide
  have hne_63 : ¬ ((w &&& 0xffe0fc00) = (0xf8206800 : UInt32)) := by intro t; bv_decide
  have hne_64 : ¬ ((w &&& 0xffe0fc00) = (0x38206800 : UInt32)) := by intro t; bv_decide
  have hne_65 : ¬ ((w &&& 0xffe00c00) = (0xf8400000 : UInt32)) := by intro t; bv_decide
  have hne_66 : ¬ ((w &&& 0xffe00000) = (0xab000000 : UInt32)) := by intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_neg hne_59, if_neg hne_60, if_neg hne_61, if_neg hne_62, if_neg hne_63, if_neg hne_64, if_neg hne_65, if_neg hne_66, if_pos h]

set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_ldur`. -/
theorem work_step_ldur (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00c00) = 0xf8400000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem (if (((w >>> 12) &&& 0x1ff).toNat) ≥ 256 then (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((512 - (((w >>> 12) &&& 0x1ff).toNat))) else (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 12) &&& 0x1ff).toNat)).toNat)) := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = (0x2a00fa00 : UInt32)) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = (0x8b000000 : UInt32)) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = (0xcb000000 : UInt32)) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = (0x9b007c00 : UInt32)) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = (0xcb0003e0 : UInt32)) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = (0xeb000000 : UInt32)) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = (0x8a000000 : UInt32)) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = (0xca000000 : UInt32)) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = (0x91000000 : UInt32)) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = (0x51000000 : UInt32)) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = (0xd1000000 : UInt32)) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = (0xf1000000 : UInt32)) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = (0x14000000 : UInt32)) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = (0x94000000 : UInt32)) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = (0xb4000000 : UInt32)) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = (0xb5000000 : UInt32)) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = (0x54000000 : UInt32)) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = (0x36000000 : UInt32)) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = (0x37000000 : UInt32)) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = (0xf9400000 : UInt32)) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = (0xb9000000 : UInt32)) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = (0x90000000 : UInt32)) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = (0xa9800000 : UInt32)) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = (0xa8c00000 : UInt32)) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = (0x52800000 : UInt32)) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = (0xd2800000 : UInt32)) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = (0xaa000000 : UInt32)) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = (0xf2800000 : UInt32)) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = (0x72800000 : UInt32)) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = (0x12800000 : UInt32)) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = (0x92800000 : UInt32)) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = (0x9a9f07e0 : UInt32)) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = (0xf9000000 : UInt32)) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = (0xa9400000 : UInt32)) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = (0xaa200000 : UInt32)) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = (0xd61f0000 : UInt32)) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = (0xd4000001 : UInt32)) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = (0x13001c00 : UInt32)) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = (0x13003c00 : UInt32)) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = (0x93407c00 : UInt32)) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = (0x92401c00 : UInt32)) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = (0x92403c00 : UInt32)) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = (0x92407c00 : UInt32)) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00800 : UInt32)) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00c00 : UInt32)) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02000 : UInt32)) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02400 : UInt32)) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02800 : UInt32)) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = (0x9b008000 : UInt32)) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = (0xd340fc00 : UInt32)) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = (0x9340fc00 : UInt32)) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = (0xd3400000 : UInt32)) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = (0x39400000 : UInt32)) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = (0x39000000 : UInt32)) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = (0x79400000 : UInt32)) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = (0x79000000 : UInt32)) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = (0x39800000 : UInt32)) := by intro t; bv_decide
  have hne_59 : ¬ ((w &&& 0xffd00000) = (0x79800000 : UInt32)) := by intro t; bv_decide
  have hne_60 : ¬ ((w &&& 0xffd00000) = (0xb9800000 : UInt32)) := by intro t; bv_decide
  have hne_61 : ¬ ((w &&& 0xffd00000) = (0xb9400000 : UInt32)) := by intro t; bv_decide
  have hne_62 : ¬ ((w &&& 0xffe0fc00) = (0xf8606800 : UInt32)) := by intro t; bv_decide
  have hne_63 : ¬ ((w &&& 0xffe0fc00) = (0xf8206800 : UInt32)) := by intro t; bv_decide
  have hne_64 : ¬ ((w &&& 0xffe0fc00) = (0x38206800 : UInt32)) := by intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_neg hne_59, if_neg hne_60, if_neg hne_61, if_neg hne_62, if_neg hne_63, if_neg hne_64, if_pos h]
  rfl


set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_stur`. -/
theorem work_step_stur (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00c00) = 0xf8000000) :
    arm64_step s code = some { s with mem := mem_write_u64 s.mem (if (((w >>> 12) &&& 0x1ff).toNat) ≥ 256 then (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((512 - (((w >>> 12) &&& 0x1ff).toNat))) else (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 12) &&& 0x1ff).toNat)).toNat (arm64_reg ((w &&& 0x1f).toNat) s) } := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = (0x2a00fa00 : UInt32)) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = (0x8b000000 : UInt32)) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = (0xcb000000 : UInt32)) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = (0x9b007c00 : UInt32)) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = (0xcb0003e0 : UInt32)) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = (0xeb000000 : UInt32)) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = (0x8a000000 : UInt32)) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = (0xca000000 : UInt32)) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = (0x91000000 : UInt32)) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = (0x51000000 : UInt32)) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = (0xd1000000 : UInt32)) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = (0xf1000000 : UInt32)) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = (0x14000000 : UInt32)) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = (0x94000000 : UInt32)) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = (0xb4000000 : UInt32)) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = (0xb5000000 : UInt32)) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = (0x54000000 : UInt32)) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = (0x36000000 : UInt32)) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = (0x37000000 : UInt32)) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = (0xf9400000 : UInt32)) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = (0xb9000000 : UInt32)) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = (0x90000000 : UInt32)) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = (0xa9800000 : UInt32)) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = (0xa8c00000 : UInt32)) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = (0x52800000 : UInt32)) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = (0xd2800000 : UInt32)) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = (0xaa000000 : UInt32)) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = (0xf2800000 : UInt32)) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = (0x72800000 : UInt32)) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = (0x12800000 : UInt32)) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = (0x92800000 : UInt32)) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = (0x9a9f07e0 : UInt32)) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = (0xf9000000 : UInt32)) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = (0xa9400000 : UInt32)) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = (0xaa200000 : UInt32)) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = (0xd61f0000 : UInt32)) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = (0xd4000001 : UInt32)) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = (0x13001c00 : UInt32)) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = (0x13003c00 : UInt32)) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = (0x93407c00 : UInt32)) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = (0x92401c00 : UInt32)) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = (0x92403c00 : UInt32)) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = (0x92407c00 : UInt32)) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00800 : UInt32)) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00c00 : UInt32)) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02000 : UInt32)) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02400 : UInt32)) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02800 : UInt32)) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = (0x9b008000 : UInt32)) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = (0xd340fc00 : UInt32)) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = (0x9340fc00 : UInt32)) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = (0xd3400000 : UInt32)) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = (0x39400000 : UInt32)) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = (0x39000000 : UInt32)) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = (0x79400000 : UInt32)) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = (0x79000000 : UInt32)) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = (0x39800000 : UInt32)) := by intro t; bv_decide
  have hne_59 : ¬ ((w &&& 0xffd00000) = (0x79800000 : UInt32)) := by intro t; bv_decide
  have hne_60 : ¬ ((w &&& 0xffd00000) = (0xb9800000 : UInt32)) := by intro t; bv_decide
  have hne_61 : ¬ ((w &&& 0xffd00000) = (0xb9400000 : UInt32)) := by intro t; bv_decide
  have hne_62 : ¬ ((w &&& 0xffe0fc00) = (0xf8606800 : UInt32)) := by intro t; bv_decide
  have hne_63 : ¬ ((w &&& 0xffe0fc00) = (0xf8206800 : UInt32)) := by intro t; bv_decide
  have hne_64 : ¬ ((w &&& 0xffe0fc00) = (0x38206800 : UInt32)) := by intro t; bv_decide
  have hne_65 : ¬ ((w &&& 0xffe00c00) = (0xf8400000 : UInt32)) := by intro t; bv_decide
  have hne_66 : ¬ ((w &&& 0xffe00000) = (0xab000000 : UInt32)) := by intro t; bv_decide
  have hne_67 : ¬ ((w &&& 0xffe00000) = (0xea000000 : UInt32)) := by intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_neg hne_59, if_neg hne_60, if_neg hne_61, if_neg hne_62, if_neg hne_63, if_neg hne_64, if_neg hne_65, if_neg hne_66, if_neg hne_67, if_pos h]
  rfl


set_option maxHeartbeats 4000000 in
/-- Per-instruction step: `work_step_smulh`. -/
theorem work_step_smulh (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe07c00) = 0x9b407c00) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s
      (smulh64 (arm64_reg ((w >>> 5) &&& 0x1f).toNat s)
        (arm64_reg ((w >>> 16) &&& 0x1f).toNat s))) := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = (0x2a00fa00 : UInt32)) := by intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = (0x8b000000 : UInt32)) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = (0xcb000000 : UInt32)) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = (0x9b007c00 : UInt32)) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = (0xcb0003e0 : UInt32)) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = (0xeb000000 : UInt32)) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = (0x8a000000 : UInt32)) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = (0xca000000 : UInt32)) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = (0x91000000 : UInt32)) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = (0x51000000 : UInt32)) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = (0xd1000000 : UInt32)) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = (0xf1000000 : UInt32)) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = (0x14000000 : UInt32)) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = (0x94000000 : UInt32)) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = (0xb4000000 : UInt32)) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = (0xb5000000 : UInt32)) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = (0x54000000 : UInt32)) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = (0x36000000 : UInt32)) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = (0x37000000 : UInt32)) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = (0xf9400000 : UInt32)) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = (0xb9000000 : UInt32)) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = (0x90000000 : UInt32)) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = (0xa9800000 : UInt32)) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = (0xa8c00000 : UInt32)) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = (0x52800000 : UInt32)) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xffe00000) = (0xd2800000 : UInt32)) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xffe00000) = (0xaa000000 : UInt32)) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xff800000) = (0xf2800000 : UInt32)) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xff800000) = (0x72800000 : UInt32)) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffe00000) = (0x12800000 : UInt32)) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = (0x92800000 : UInt32)) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffff0fe0) = (0x9a9f07e0 : UInt32)) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = (0xf9000000 : UInt32)) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xffc00000) = (0xa9400000 : UInt32)) := by intro t; bv_decide
  have hne_36 : ¬ ((w &&& 0xffe0fc00) = (0xaa200000 : UInt32)) := by intro t; bv_decide
  have hne_37 : ¬ ((w &&& 0xfffffc1f) = (0xd61f0000 : UInt32)) := by intro t; bv_decide
  have hne_38 : ¬ ((w &&& 0xffe0001f) = (0xd4000001 : UInt32)) := by intro t; bv_decide
  have hne_39 : ¬ ((w &&& 0xffe0fc00) = (0x13001c00 : UInt32)) := by intro t; bv_decide
  have hne_40 : ¬ ((w &&& 0xffe0fc00) = (0x13003c00 : UInt32)) := by intro t; bv_decide
  have hne_41 : ¬ ((w &&& 0xffe0fc00) = (0x93407c00 : UInt32)) := by intro t; bv_decide
  have hne_42 : ¬ ((w &&& 0xffc0fc00) = (0x92401c00 : UInt32)) := by intro t; bv_decide
  have hne_43 : ¬ ((w &&& 0xffc0fc00) = (0x92403c00 : UInt32)) := by intro t; bv_decide
  have hne_44 : ¬ ((w &&& 0xffc0fc00) = (0x92407c00 : UInt32)) := by intro t; bv_decide
  have hne_45 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00800 : UInt32)) := by intro t; bv_decide
  have hne_46 : ¬ ((w &&& 0xffe0fc00) = (0x9ac00c00 : UInt32)) := by intro t; bv_decide
  have hne_47 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02000 : UInt32)) := by intro t; bv_decide
  have hne_48 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02400 : UInt32)) := by intro t; bv_decide
  have hne_49 : ¬ ((w &&& 0xffe0fc00) = (0x9ac02800 : UInt32)) := by intro t; bv_decide
  have hne_50 : ¬ ((w &&& 0xffe08000) = (0x9b008000 : UInt32)) := by intro t; bv_decide
  have hne_51 : ¬ ((w &&& 0xffc0fc00) = (0xd340fc00 : UInt32)) := by intro t; bv_decide
  have hne_52 : ¬ ((w &&& 0xffc0fc00) = (0x9340fc00 : UInt32)) := by intro t; bv_decide
  have hne_53 : ¬ ((w &&& 0xffc00000) = (0xd3400000 : UInt32)) := by intro t; bv_decide
  have hne_54 : ¬ ((w &&& 0xffd00000) = (0x39400000 : UInt32)) := by intro t; bv_decide
  have hne_55 : ¬ ((w &&& 0xffd00000) = (0x39000000 : UInt32)) := by intro t; bv_decide
  have hne_56 : ¬ ((w &&& 0xffd00000) = (0x79400000 : UInt32)) := by intro t; bv_decide
  have hne_57 : ¬ ((w &&& 0xffd00000) = (0x79000000 : UInt32)) := by intro t; bv_decide
  have hne_58 : ¬ ((w &&& 0xffd00000) = (0x39800000 : UInt32)) := by intro t; bv_decide
  have hne_59 : ¬ ((w &&& 0xffd00000) = (0x79800000 : UInt32)) := by intro t; bv_decide
  have hne_60 : ¬ ((w &&& 0xffd00000) = (0xb9800000 : UInt32)) := by intro t; bv_decide
  have hne_61 : ¬ ((w &&& 0xffd00000) = (0xb9400000 : UInt32)) := by intro t; bv_decide
  have hne_62 : ¬ ((w &&& 0xffe0fc00) = (0xf8606800 : UInt32)) := by intro t; bv_decide
  have hne_63 : ¬ ((w &&& 0xffe0fc00) = (0xf8206800 : UInt32)) := by intro t; bv_decide
  have hne_64 : ¬ ((w &&& 0xffe0fc00) = (0x38206800 : UInt32)) := by intro t; bv_decide
  have hne_65 : ¬ ((w &&& 0xffe00c00) = (0xf8400000 : UInt32)) := by intro t; bv_decide
  have hne_66 : ¬ ((w &&& 0xffe00000) = (0xab000000 : UInt32)) := by intro t; bv_decide
  have hne_67 : ¬ ((w &&& 0xffe00000) = (0xea000000 : UInt32)) := by intro t; bv_decide
  have hne_68 : ¬ ((w &&& 0xffe00c00) = (0xf8000000 : UInt32)) := by intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_neg hne_36, if_neg hne_37, if_neg hne_38, if_neg hne_39, if_neg hne_40, if_neg hne_41, if_neg hne_42, if_neg hne_43, if_neg hne_44, if_neg hne_45, if_neg hne_46, if_neg hne_47, if_neg hne_48, if_neg hne_49, if_neg hne_50, if_neg hne_51, if_neg hne_52, if_neg hne_53, if_neg hne_54, if_neg hne_55, if_neg hne_56, if_neg hne_57, if_neg hne_58, if_neg hne_59, if_neg hne_60, if_neg hne_61, if_neg hne_62, if_neg hne_63, if_neg hne_64, if_neg hne_65, if_neg hne_66, if_neg hne_67, if_neg hne_68, if_pos h]
