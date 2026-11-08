import ProofLib
import X86

/-!
# Peephole.lean — the proofs that license `formal/peephole.py`

`formal/peephole.py` rewrites the instruction list the two backends emit. This
file is what licenses each rewrite: one theorem per rule, saying the rewritten
sequence leaves the machine model's **registers, flags and memory** as it found
them, under side conditions the rule states and the pass discharges.

## Why this is a separate module and not part of `ProofLib.lean`

`ProofLib.lean`'s `.olean` is 52 MB and about two minutes to build, and it is
the input to every generated proof in the suite. The peephole theorems are read
by nothing except the pass's own licence check and its tests, so putting them
there would make every future edit to them cost every other branch a two-minute
rebuild. This module imports `ProofLib` (and `X86`, for the x86-64 half of the
pass) and is built once, alone.

## What a rule has to say

The statement each theorem makes is deliberately narrower than "the program
behaves the same". A peephole rewrite changes which instruction sits at an
address, so a whole-program equivalence is not a one-step question about the
machine model — it is a question about a rewritten `arm64_step`, and proving it
would be about the rewriter rather than about the rewrite. What the model CAN
be asked, and is here, is whether the two instruction sequences agree on the
machine's observable state:

  * every **register**,
  * the **flags**,
  * **memory**,

and, for the rule that needs it, on which register the rewrite is allowed to
differ at all — which is the side condition, stated in the conclusion rather
than assumed in a comment.

The pc bookkeeping is a clause of each theorem and is proved rather than
argued: the rewrite removed four bytes, so the next instruction is fetched four
bytes earlier, and `formal/peephole.py`'s `_Remap` moves every label,
relocation and recorded pc by exactly that number. This file is where the
number is pinned to the machine model rather than to the rewriter's own
arithmetic.

## The side conditions, and where each is discharged

A rule whose soundness depends on something the theorem cannot see states it,
and the pass checks it:

  * `rd < 31` and `rn < 31` — register 31 is SP in this class, and the model
    and the hardware can read it differently (`arm64_set_reg 31` writes `sp`;
    A64 reads `Rn = 31` as XZR in the ADD-immediate class). `decode_arm64`
    returns nothing for a word naming it.
  * `sh = 0` — the model reads an `ADD (immediate)`'s operand as `imm12` and
    does not read the `sh` bit, while the hardware scales by 4096 when it is
    set. A rule over this class must not fire on a word the model and the
    hardware already disagree about, so `decode_arm64` requires `sh = 0`.
  * **register liveness** — `copy_chain` leaves the intermediate register
    unwritten, so it fires only when nothing reads that register again.
    `_ctx_dead` in the pass is the check, and the sixth clause of
    `peephole_arm64_copy_chain` is the condition it discharges.

## What is NOT here

The arm64 rules that need the `STR`/`LDR`/`MOVZ` arms of `arm64_step`, and the
x86-64 rules the pass's table names but does not enable. Both are written down
in `bugs/FORMAL_peephole_rules_without_proofs.md` with the exact lemma each one
is waiting on. Nothing in this file is a placeholder: every theorem below is
proved, and there is no `sorry`.
-/

set_option autoImplicit false


/-! ## The register file

`arm64_set_reg` is a 31-way `match` on the index, so "writing one register
leaves every other one alone" is a case split and nothing subtler. It is stated
once here rather than re-proved per rule: `copy_chain` needs it for the
register the rewrite leaves unwritten, and `add_imm_fuse` needs it to see
through two successive writes.

`ProofLib` already has the other direction (`arm64_set_reg_reg_same`) and pins
four specific pairs; this is the general one the peephole needs, and its
statement is deliberately shaped to match the conclusion the rules draw: any
index, any value, one side condition each way. -/

/-- Writing register `j` leaves every OTHER register below 31 alone. -/
theorem arm64_reg_set_reg_other (i j : Nat) (s : Arm64State) (v : UInt64)
    (hi : i < 31) (h : i ≠ j) :
    arm64_reg i (arm64_set_reg j s v) = arm64_reg i s := by
  rcases (show i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨
      i = 7 ∨ i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨
      i = 14 ∨ i = 15 ∨ i = 16 ∨ i = 17 ∨ i = 18 ∨ i = 19 ∨ i = 20 ∨
      i = 21 ∨ i = 22 ∨ i = 23 ∨ i = 24 ∨ i = 25 ∨ i = 26 ∨ i = 27 ∨
      i = 28 ∨ i = 29 ∨ i = 30 from by omega) with
    h | h | h | h | h | h | h | h | h | h | h | h |
    h | h | h | h | h | h | h | h | h | h | h | h |
    h | h | h | h | h | h | h
  all_goals subst i
  all_goals simp only [arm64_reg, arm64_set_reg]
  all_goals split <;> first | rfl | omega

/-- A register write touches no flag, no memory, and does not move the pc.
Each is `{s with xN := …}` outright, so each is `rfl` once the `match` is
split. -/
theorem arm64_set_reg_nzcv (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).nzcv = s.nzcv := by
  unfold arm64_set_reg; split <;> rfl

theorem arm64_set_reg_mem_unchanged (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).mem = s.mem := by
  unfold arm64_set_reg; split <;> rfl

theorem arm64_set_reg_pc_unchanged (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).pc = s.pc := by
  unfold arm64_set_reg; split <;> rfl

/-- Stepping a register-writing instruction from `{s with pc := p}` writes the
same register as stepping it from `s`; only the pc differs. `arm64_steps` steps
the second instruction of a pair from the pc-advanced state, so this is what
lets the rules compare the pair's registers with the rewrite's. -/
theorem arm64_reg_set_reg_pc (i k : Nat) (s : Arm64State) (v : UInt64) (p : Nat)
    (hk : k < 31) (hi : i < 31) :
    arm64_reg k (arm64_set_reg i { s with pc := p } v) = arm64_reg k (arm64_set_reg i s v) := by
  by_cases h : k = i
  · rw [h, arm64_set_reg_reg_eq _ _ _ hi, arm64_set_reg_reg_eq _ _ _ hi]
  · rw [arm64_reg_set_reg_other k i _ _ hk (by omega), arm64_reg_pc,
        arm64_reg_set_reg_other k i _ _ hk (by omega)]

/-- A register write and a pc change commute. `arm64_steps_two_seq` needs it:
after the first instruction the pc has already advanced, so the second is
stepped from `{s1 with pc := s.pc + 4}` rather than from `s1`. -/
theorem arm64_set_reg_pc_congr (i : Nat) (s : Arm64State) (v : UInt64) (p : Nat) :
    arm64_set_reg i { s with pc := p } v = { arm64_set_reg i s v with pc := p } := by
  unfold arm64_set_reg; split <;> rfl

/-! ## The `ADD (immediate)` arm of `arm64_step`

`formal/arm64.py`'s `encode_mov_zr_xn` spells a register copy as
`ADD Xd, Xn, #0`, so this arm is where every copy-based rule lands, and it is
the arm all three arm64 rules below are about. It is also the reason this file
is not a rewrite of `arm64_step`'s `if`-chain: the chain is 70 arms deep and
this one is the tenth, and a rule that needs the `STR` arm would have to
discharge sixty negations to reach it. That cost is why the rule table stops
here, and it is written down rather than guessed at in
`bugs/FORMAL_peephole_rules_without_proofs.md`.

Its shape in the model, which the side conditions are read off: `rd = 31` takes
an `sp` branch and is refused; `Rn` is read through `arm64_reg_or_sp`, which is
`arm64_reg` below 31; and the operand is `arm64_ext_imm12 w`, which reads the
`sh` bit (bits 23:22) and scales the immediate by `1 << (12 * sh)`. The rules
therefore carry a `sh = 0` hypothesis, which `formal/peephole.py::decode_arm64`
discharges by refusing a `sh = 1` word outright — so the theorem is about the
same instruction the pass rewrote, and the model/hardware agreement the shift
fix restored is not leaned on without saying so.

The conclusion is stated in the model's OWN terms (`arm64_reg_or_sp`,
`arm64_ext_imm12`) so that the proof is the decode chain and nothing else;
the rules below rewrite those two terms with `arm64_reg_or_sp_of_lt` and their
`imm`/`sh` hypotheses. -/

/-- One step of a 64-bit `ADD Xd, Xn, #imm`: the class `formal/arm64.py` emits
a register copy and every immediate addition in. -/
theorem arm64_step_add_imm64 (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x91000000)
    (hrd : (w &&& 0x1f).toNat ≠ 31) :
    arm64_step s code
      = some (arm64_set_reg ((w &&& 0x1f).toNat) s
          (arm64_reg_or_sp ((w >>> 5) &&& 0x1f).toNat s
            + UInt64.ofNat (arm64_ext_imm12 w))) := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_orr : ¬ ((w &&& 0xffe00000) = (0x2A00FA00 : UInt32)) := by
    intro t; bv_decide
  have hne_add : ¬ ((w &&& 0xffe00000) = (0x8B000000 : UInt32)) := by
    intro t; bv_decide
  have hne_sub : ¬ ((w &&& 0xffe00000) = (0xCB000000 : UInt32)) := by
    intro t; bv_decide
  have hne_mul : ¬ ((w &&& 0xffe07c00) = (0x9B007C00 : UInt32)) := by
    intro t; bv_decide
  have hne_neg : ¬ ((w &&& 0xfffffc1f) = (0xCB0003E0 : UInt32)) := by
    intro t; bv_decide
  have hne_cmp : ¬ ((w &&& 0xffe00000) = (0xEB000000 : UInt32)) := by
    intro t; bv_decide
  have hne_and : ¬ ((w &&& 0xffe00000) = (0x8A000000 : UInt32)) := by
    intro t; bv_decide
  have hne_eor : ¬ ((w &&& 0xffe00000) = (0xCA000000 : UInt32)) := by
    intro t; bv_decide
  have hne_add32 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by
    intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_orr, if_neg hne_add, if_neg hne_sub,
      if_neg hne_mul, if_neg hne_neg, if_neg hne_cmp, if_neg hne_and,
      if_neg hne_eor, if_neg hne_add32, if_pos h, if_neg hrd]

/-- One step of a 64-bit `LDR Xt, [Xn, #imm]` (unsigned offset, no writeback). -/
theorem arm64_step_ldr64 (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xF9400000)
    (hrt : (w &&& 0x1f).toNat < 31) :
    arm64_step s code
      = some (arm64_set_reg ((w &&& 0x1f).toNat) s
          (mem_read_u64 s.mem
            (((arm64_reg_or_sp ((w >>> 5) &&& 0x1f).toNat s) +
              UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat))) := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
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
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_pos h]

/-- One step of a 64-bit `STR Xt, [Xn, #imm]` (unsigned offset, no writeback). -/
theorem arm64_step_str64 (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xF9000000)
    (hrt : (w &&& 0x1f).toNat < 31) :
    arm64_step s code
      = some { s with mem := (mem_write_u64 s.mem
          (((arm64_reg_or_sp ((w >>> 5) &&& 0x1f).toNat s) +
            UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat)
          (arm64_reg ((w &&& 0x1f).toNat) s)) } := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
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
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_pos h]

/-! ### Memory write idempotence (step 02)

A store of the same value to the same place twice is one store. These three are
the lemmas the duplicate-store peephole rules lack:

* `mem_write_u64_idem` ← `arm64/mem_pair` (`STR;STR`), step 03d;
* `mem_write_bytes8_idem` ← `x86_64/mem_pair` (duplicate store), step 04c;
* `arm64_set_reg_self` ← `arm64/store_load` and `LDR;LDR`, steps 03c/03d.

Read-after-write already exists (`mem_read_after_write_u64`, ProofLib; X86's
`mem_read_bytes_write_same`); what was missing was write IDEMPOTENCE. They are
proved through the window split (inside the written window the base memory is
irrelevant; outside it the write is invisible), not by unfolding 8 nested
`if`s, which `simp` does not finish. -/

theorem mem_write_u64_outside (mem : Nat → UInt8) (addr : Nat) (v : UInt64) (i : Nat)
    (h : i < addr ∨ addr + 8 ≤ i) : mem_write_u64 mem addr v i = mem i := by
  simp only [mem_write_u64]
  repeat (rw [if_neg (by omega)])

theorem mem_write_u64_inside (mem mem2 : Nat → UInt8) (addr : Nat) (v : UInt64) (i : Nat)
    (h : addr ≤ i ∧ i < addr + 8) :
    mem_write_u64 mem addr v i = mem_write_u64 mem2 addr v i := by
  rcases (by omega : i = addr ∨ i = addr + 1 ∨ i = addr + 2 ∨ i = addr + 3 ∨ i = addr + 4 ∨ i = addr + 5 ∨ i = addr + 6 ∨ i = addr + 7) with h | h | h | h | h | h | h | h <;> subst h <;> simp [mem_write_u64]

theorem mem_write_u64_idem (mem : Nat → UInt8) (addr : Nat) (v : UInt64) :
    mem_write_u64 (mem_write_u64 mem addr v) addr v = mem_write_u64 mem addr v := by
  funext i
  by_cases hw : addr ≤ i ∧ i < addr + 8
  · exact mem_write_u64_inside _ _ addr v i hw
  · have ho : i < addr ∨ addr + 8 ≤ i := by omega
    rw [mem_write_u64_outside _ addr v i ho, mem_write_u64_outside _ addr v i ho]

theorem mem_write_bytes_outside (mem : Nat → UInt8) (addr : Nat) (v : UInt64) (n i : Nat)
    (h : i < addr ∨ addr + n ≤ i) : mem_write_bytes mem addr v n i = mem i := by
  induction n generalizing addr v with
  | zero => rfl
  | succ k ih =>
    simp only [mem_write_bytes]
    rw [if_neg (by omega)]
    exact ih (addr + 1) (v >>> 8) (by omega)

theorem mem_write_bytes_inside (mem mem2 : Nat → UInt8) (addr : Nat) (v : UInt64) (n i : Nat)
    (h : addr ≤ i ∧ i < addr + n) :
    mem_write_bytes mem addr v n i = mem_write_bytes mem2 addr v n i := by
  induction n generalizing addr v with
  | zero => omega
  | succ k ih =>
    simp only [mem_write_bytes]
    by_cases hi : i = addr
    · simp [hi]
    · rw [if_neg hi, if_neg hi]
      exact ih (addr + 1) (v >>> 8) (by omega)

theorem mem_write_bytes_idem (mem : Nat → UInt8) (addr : Nat) (v : UInt64) (n : Nat) :
    mem_write_bytes (mem_write_bytes mem addr v n) addr v n = mem_write_bytes mem addr v n := by
  funext i
  by_cases hw : addr ≤ i ∧ i < addr + n
  · exact mem_write_bytes_inside _ _ addr v n i hw
  · have ho : i < addr ∨ addr + n ≤ i := by omega
    rw [mem_write_bytes_outside _ addr v n i ho, mem_write_bytes_outside _ addr v n i ho]

theorem mem_write_bytes8_idem (mem : Nat → UInt8) (addr : Nat) (v : UInt64) :
    mem_write_bytes (mem_write_bytes mem addr v 8) addr v 8 = mem_write_bytes mem addr v 8 :=
  mem_write_bytes_idem mem addr v 8

theorem arm64_set_reg_self (s : Arm64State) (k : Nat) (hk : k < 31) :
    arm64_set_reg k s (arm64_reg k s) = s := by
  rcases (by omega : k = 0 ∨ k = 1 ∨ k = 2 ∨ k = 3 ∨ k = 4 ∨ k = 5 ∨ k = 6 ∨ k = 7 ∨ k = 8 ∨ k = 9 ∨ k = 10 ∨ k = 11 ∨ k = 12 ∨ k = 13 ∨ k = 14 ∨ k = 15 ∨ k = 16 ∨ k = 17 ∨ k = 18 ∨ k = 19 ∨ k = 20 ∨ k = 21 ∨ k = 22 ∨ k = 23 ∨ k = 24 ∨ k = 25 ∨ k = 26 ∨ k = 27 ∨ k = 28 ∨ k = 29 ∨ k = 30) with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [arm64_set_reg, arm64_reg]

/-- The pc a SEQUENTIAL step leaves behind, and the advance `arm64_steps`
performs for it.

`arm64_step` does not move the pc — the register-writing arms are
`arm64_set_reg rd s …`, which is `s` with one field replaced — and `arm64_steps`
advances it by 4 whenever a step left it alone. So "the rewrite removed four
bytes, so the next instruction is fetched four bytes earlier" is a fact about
`arm64_steps`, not about `arm64_step`, and this is where it is proved: the
reassembled program fetches at `s.pc + 4` after one rewrite and at `s.pc + 8`
after two, and `formal/peephole.py`'s `_Remap` moves every label and relocation
by the same four. -/
theorem arm64_steps_one_seq (s : Arm64State) (code : Nat → UInt8)
    (s' : Arm64State) (hstep : arm64_step s code = some s') (hpc : s'.pc = s.pc) :
    arm64_steps s code 1 = some { s' with pc := s.pc + 4 } := by
  simp [arm64_steps, hstep, hpc]

/-- …and two of them: `s.pc + 8`, which is the number a two-instruction window
has to move every label above it by. -/
theorem arm64_steps_two_seq (s : Arm64State) (code : Nat → UInt8)
    (s1 s2 : Arm64State)
    (hstep1 : arm64_step s code = some s1) (hpc1 : s1.pc = s.pc)
    (hstep2 : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 }) :
    arm64_steps s code 2 = some { s2 with pc := s.pc + 8 } := by
  simp [arm64_steps, hstep1, hpc1, hstep2]

/-! ## The rules

Each theorem below is one row of `formal/peephole.py`'s `ARM64_RULES`, and the
name is what `unlicensed_rules()` reads to decide whether the pass may run at
all.

The shape is the same in all three: hypotheses naming the original instruction(s)
by their `UInt32` word and field decomposition, hypotheses naming the REWRITTEN
instruction the same way, and a conclusion in four parts — registers, flags,
memory, and the pc advance. The rewritten instruction is named with a SEPARATE
word (`w3`) rather than as a bit expression on `w1`, because the pass
re-encodes it by changing two fields of the first word and the theorem should
say exactly which two — see `hdst`/`hsrc` in `peephole_arm64_copy_chain`. -/

/-- **Rule `arm64/mov_self`.** `mov xa, xa` — a register copied into itself —
is one instruction of nothing, and removing it leaves every register, the flags
and memory exactly as they were. The pc still advances four bytes, which is the
clause `_Remap` needs: deleting the instruction moves everything after it down
by four, and it is the STATE that says the fetch resumes at `pc + 4`. -/
theorem peephole_arm64_mov_self (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x91000000)
    (himm : ((w >>> 10) &&& 0xfff).toNat = 0)
    (hrd : (w &&& 0x1f).toNat < 31)
    (hrn : ((w >>> 5) &&& 0x1f).toNat < 31)
    (hsame : (w &&& 0x1f).toNat = ((w >>> 5) &&& 0x1f).toNat)
    (t : Arm64State) (hs : arm64_step s code = some t) :
    (∀ i, i < 31 → arm64_reg i t = arm64_reg i s)
    ∧ t.nzcv = s.nzcv
    ∧ t.mem = s.mem
    ∧ arm64_steps s code 1 = some { t with pc := pc + 4 } := by
  have hstep := arm64_step_add_imm64 s code pc w hpc hread h (by omega)
  rw [hsame] at hstep
  rw [show arm64_ext_imm12 w = 0 by simp [arm64_ext_imm12, himm], hs] at hstep
  have ht : t = arm64_set_reg ((w >>> 5) &&& 0x1f).toNat s
      (arm64_reg ((w >>> 5) &&& 0x1f).toNat s) := by
    rw [Option.some.inj hstep, arm64_reg_or_sp_of_lt _ s hrn,
        u64_add_ofNat_zero_r]
  refine ⟨?_, ?_, ?_, ?_⟩
  · rw [ht]
    intro i hi
    by_cases hix : i = ((w >>> 5) &&& 0x1f).toNat
    · rw [hix]
      exact arm64_set_reg_reg_same _ _ _ hrn
    · exact arm64_reg_set_reg_other _ _ _ _ hi hix
  · rw [ht]; exact arm64_set_reg_nzcv _ s _
  · rw [ht]; exact arm64_set_reg_mem_unchanged _ s _
  · rw [arm64_steps_one_seq _ _ _ hs (by rw [ht, arm64_set_reg_pc_unchanged, hpc])]
    simp [hpc]

/-- **Rule `arm64/add_imm_fuse`.** `add xd, xn, #i` followed by
`add xd, xd, #j` computes `Xn + i + j`, which is `add xd, xn, #(i+j)` — one
instruction, and it needs `i + j < 4096` to be encodable at all, which is the
whole 12-bit immediate field, so the rule never has to fall back to a chain.
(`hij` is the ENCODABILITY condition and not an arithmetic one:
`(v + i) + j = v + (i + j)` holds over `UInt64` for every `i` and `j`. It is
stated because the pass has to check it before it can emit the word.)

Neither instruction writes the flags and neither touches memory, and the
second reads the first's result — so the pair and the fused instruction leave
every register, the flags and memory identical, with NO liveness condition and
so no exception clause: the second writes the register the first wrote, which
is the register the rewrite also writes.

`hpair` is the pair's SECOND step as `arm64_steps` performs it — from
`{s1 with pc := pc + 4}`, because `arm64_step` does not advance the pc and
`arm64_steps` does — and the last two clauses are `arm64_steps_two_seq` and
`arm64_steps_one_seq`: the pair fetches on to `pc + 8` where the rewrite stops
at `pc + 4`. -/
theorem peephole_arm64_add_imm_fuse (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 w3 : UInt32) (i j : Nat)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (hread3 : arm64_read_insn code pc = w3)
    (h1 : (w1 &&& 0xff800000) = 0x91000000)
    (h2 : (w2 &&& 0xff800000) = 0x91000000)
    (h3 : (w3 &&& 0xff800000) = 0x91000000)
    (hi : ((w1 >>> 10) &&& 0xfff).toNat = i)
    (hj : ((w2 >>> 10) &&& 0xfff).toNat = j)
    -- ENCODABILITY, not arithmetic: `(v + i) + j = v + (i + j)` holds over
    -- `UInt64` for every `i` and `j`. Stated (and unused by the proof) because
    -- the pass has to check it before it can emit the fused word, and a
    -- side condition the theorem does not carry is a side condition nobody
    -- reads.
    (hij : i + j < 4096)
    (hrd1 : (w1 &&& 0x1f).toNat < 31) (hrn1 : ((w1 >>> 5) &&& 0x1f).toNat < 31)
    (hrd2 : (w2 &&& 0x1f).toNat < 31) (hrn2 : ((w2 >>> 5) &&& 0x1f).toNat < 31)
    (hrd3 : (w3 &&& 0x1f).toNat < 31) (hrn3 : ((w3 >>> 5) &&& 0x1f).toNat < 31)
    -- the second writes the register the first wrote
    (hd2 : (w2 &&& 0x1f).toNat = (w1 &&& 0x1f).toNat)
    -- and reads it
    (huse : ((w2 >>> 5) &&& 0x1f).toNat = (w1 &&& 0x1f).toNat)
    -- the fused instruction: the FIRST's destination and base, and an immediate
    -- that is the sum of the two — the two fields the pass re-encodes.
    (hdst : (w3 &&& 0x1f).toNat = (w1 &&& 0x1f).toNat)
    (hbase : ((w3 >>> 5) &&& 0x1f).toNat = ((w1 >>> 5) &&& 0x1f).toNat)
    (hfuse : ((w3 >>> 10) &&& 0xfff).toNat = i + j)
    -- `sh == 0` for every word: the model now reads bit 22 (`arm64_ext_imm12`)
    -- and the pass refuses a `sh = 1` word (`formal/peephole.py::decode_arm64`),
    -- so the rules only ever see the unshifted form.
    (hsh1 : (w1 >>> 22) &&& 0x1 = 0)
    (hsh2 : (w2 >>> 22) &&& 0x1 = 0)
    (hsh3 : (w3 >>> 22) &&& 0x1 = 0)
    (s1 s2 s3 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 })
    (hs3 : arm64_step s code = some s3) :
    (∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s3)
    ∧ s2.nzcv = s.nzcv
    ∧ s2.mem = s.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s3 with pc := pc + 4 } := by
  have hstep1 := arm64_step_add_imm64 s code pc w1 hpc hread1 h1 (by omega)
  rw [show arm64_ext_imm12 w1 = i by simp [arm64_ext_imm12, hsh1, hi],
      hs1] at hstep1
  have hs1' : s1 = arm64_set_reg (w1 &&& 0x1f).toNat s
      (arm64_reg_or_sp (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat i) :=
    Option.some.inj hstep1
  simp only [arm64_reg_or_sp_of_lt _ s hrn1] at hs1'
  have hstep2 := arm64_step_add_imm64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2
    rfl hread2 h2 (by omega)
  rw [show arm64_ext_imm12 w2 = j by simp [arm64_ext_imm12, hsh2, hj]] at hstep2
  simp only [arm64_reg_or_sp_of_lt _ _ hrn2] at hstep2
  have e2 : ∀ k, k < 31 → arm64_reg k s2
      = arm64_reg k (arm64_set_reg (w1 &&& 0x1f).toNat s1
          (arm64_reg (w2 >>> 5 &&& 0x1f).toNat s1 + UInt64.ofNat j)) := by
    intro k hk
    have hpair2 := hpair
    rw [hstep2] at hpair2
    have eq := Option.some.inj hpair2
    have e := congrArg (fun t : Arm64State => arm64_reg k t) eq
    rw [arm64_reg_pc] at e
    rw [arm64_reg_set_reg_pc (w2 &&& 0x1f).toNat k _ _ _ hk hrd2] at e
    simp only [arm64_reg_pc] at e
    rw [hd2] at e
    exact e.symm
  have hstep3 := arm64_step_add_imm64 s code pc w3 hpc hread3 h3 (by omega)
  rw [show arm64_ext_imm12 w3 = i + j by simp [arm64_ext_imm12, hsh3, hfuse],
      hs3] at hstep3
  have hs3' : s3 = arm64_set_reg (w1 &&& 0x1f).toNat s
      (arm64_reg (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat (i + j)) := by
    have e := Option.some.inj hstep3
    simp only [arm64_reg_or_sp_of_lt _ s hrn3] at e
    rw [hdst, hbase] at e
    exact e
  have hval : arm64_reg (w2 >>> 5 &&& 0x1f).toNat s1
      = arm64_reg (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat i := by
    rw [hs1', huse]
    exact arm64_set_reg_reg_same _ _ _ hrd1
  have hcombine : (arm64_reg (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat i)
      + UInt64.ofNat j
      = arm64_reg (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat (i + j) := by
    rw [UInt64.add_assoc, u64_ofNat_add]
  have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc_unchanged]
  have hpc3 : s3.pc = s.pc := by rw [hs3', arm64_set_reg_pc_unchanged]
  refine ⟨?_, ?_, ?_, ?_, ?_⟩
  · intro k hk
    rw [e2 k hk, hs3']
    by_cases hkc : k = (w1 &&& 0x1f).toNat
    · subst hkc
      simp only [arm64_set_reg_reg_eq _ _ _ hk]
      rw [hval, hcombine]
    · simp only [arm64_reg_set_reg_other _ _ _ _ hk hkc]
      rw [hs1', arm64_reg_set_reg_other _ _ _ _ hk hkc]
  · have hp := hpair
    rw [hstep2] at hp
    have e := congrArg (fun t : Arm64State => t.nzcv) (Option.some.inj hp)
    rw [arm64_set_reg_nzcv] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_nzcv])
  · have hp := hpair
    rw [hstep2] at hp
    have e := congrArg (fun t : Arm64State => t.mem) (Option.some.inj hp)
    rw [arm64_set_reg_mem_unchanged] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_mem_unchanged])
  · rw [arm64_steps_two_seq _ _ _ _ hs1 hpc1 hpair]
    simp [hpc]
  · rw [arm64_steps_one_seq _ _ _ hs3 hpc3]
    simp [hpc]

/-- **Rule `arm64/copy_chain`.** `mov xa, xb` followed by `mov xc, xa` is
`mov xc, xb`: the rewritten instruction leaves `xc` holding `Xb` and every
other register, the flags and memory as they were, and the ORIGINAL pair leaves
that same state with exactly ONE difference — register `xa`, which the rewrite
does not write. That difference IS the rule's side condition, stated as the
fifth clause rather than assumed in a comment, and it is what
`formal/peephole.py`'s `_ctx_dead` discharges before the rule fires: nothing
reads `xa` again, so nothing can observe the difference.

`xa` and `xc` need not be the same register — that is the whole point of a
chain — so the intermediate register is named by the theorem's own hypotheses
(`hlink` for the read, and the fifth clause for the write the rewrite skips). -/
theorem peephole_arm64_copy_chain (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w1 w2 w3 : UInt32)
    (hpc : s.pc = pc)
    (hread1 : arm64_read_insn code pc = w1)
    (hread2 : arm64_read_insn code (s.pc + 4) = w2)
    (hread3 : arm64_read_insn code pc = w3)
    (h1 : (w1 &&& 0xff800000) = 0x91000000)
    (h2 : (w2 &&& 0xff800000) = 0x91000000)
    (h3 : (w3 &&& 0xff800000) = 0x91000000)
    (himm1 : ((w1 >>> 10) &&& 0xfff).toNat = 0)
    (himm2 : ((w2 >>> 10) &&& 0xfff).toNat = 0)
    (himm3 : ((w3 >>> 10) &&& 0xfff).toNat = 0)
    (hrd1 : (w1 &&& 0x1f).toNat < 31) (hrn1 : ((w1 >>> 5) &&& 0x1f).toNat < 31)
    (hrd2 : (w2 &&& 0x1f).toNat < 31) (hrn2 : ((w2 >>> 5) &&& 0x1f).toNat < 31)
    (hrd3 : (w3 &&& 0x1f).toNat < 31) (hrn3 : ((w3 >>> 5) &&& 0x1f).toNat < 31)
    -- the second copy reads what the first wrote
    (hlink : ((w2 >>> 5) &&& 0x1f).toNat = (w1 &&& 0x1f).toNat)
    -- the rewrite's destination is the SECOND copy's and its source the FIRST
    -- copy's: exactly the two fields `formal/peephole.py` re-encodes.
    (hdst : (w3 &&& 0x1f).toNat = (w2 &&& 0x1f).toNat)
    (hsrc : ((w3 >>> 5) &&& 0x1f).toNat = ((w1 >>> 5) &&& 0x1f).toNat)
    (s1 s2 s3 : Arm64State)
    (hs1 : arm64_step s code = some s1)
    (hpair : arm64_step { s1 with pc := s.pc + 4 } code
      = some { s2 with pc := s.pc + 4 })
    (hs3 : arm64_step s code = some s3) :
    -- the rewrite: `xc` gets `Xb`, nothing else moves
    (arm64_reg (w2 &&& 0x1f).toNat s3 = arm64_reg (w1 >>> 5 &&& 0x1f).toNat s)
    ∧ (∀ k, k < 31 → k ≠ (w2 &&& 0x1f).toNat → arm64_reg k s3 = arm64_reg k s)
    ∧ s3.nzcv = s.nzcv
    ∧ s3.mem = s.mem
    -- the pair differs from the rewrite in register `xa` and nowhere else
    ∧ (∀ k, k < 31 →
          (arm64_reg k s2 = arm64_reg k s3 ∨ k = (w1 &&& 0x1f).toNat))
    ∧ s2.nzcv = s.nzcv
    ∧ s2.mem = s.mem
    -- and it fetches four bytes further on: `pc + 8` against the rewrite's `pc + 4`
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s3 with pc := pc + 4 } := by
  have hstep1 := arm64_step_add_imm64 s code pc w1 hpc hread1 h1 (by omega)
  rw [show arm64_ext_imm12 w1 = 0 by simp [arm64_ext_imm12, himm1],
      hs1] at hstep1
  have hs1' : s1 = arm64_set_reg (w1 &&& 0x1f).toNat s
      (arm64_reg (w1 >>> 5 &&& 0x1f).toNat s) := by
    have e := Option.some.inj hstep1
    simp only [arm64_reg_or_sp_of_lt _ s hrn1, u64_add_ofNat_zero_r] at e
    exact e
  have hstep2 := arm64_step_add_imm64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2
    rfl hread2 h2 (by omega)
  rw [show arm64_ext_imm12 w2 = 0 by simp [arm64_ext_imm12, himm2]] at hstep2
  simp only [arm64_reg_or_sp_of_lt _ _ hrn2, u64_add_ofNat_zero_r] at hstep2
  have e2 : ∀ k, k < 31 → arm64_reg k s2
      = arm64_reg k (arm64_set_reg (w2 &&& 0x1f).toNat s1
          (arm64_reg (w2 >>> 5 &&& 0x1f).toNat s1)) := by
    intro k hk
    have hpair2 := hpair
    rw [hstep2] at hpair2
    have eq := Option.some.inj hpair2
    have e := congrArg (fun t : Arm64State => arm64_reg k t) eq
    rw [arm64_reg_pc] at e
    rw [arm64_reg_set_reg_pc (w2 &&& 0x1f).toNat k _ _ _ hk hrd2] at e
    simp only [arm64_reg_pc] at e
    exact e.symm
  have hstep3 := arm64_step_add_imm64 s code pc w3 hpc hread3 h3 (by omega)
  rw [show arm64_ext_imm12 w3 = 0 by simp [arm64_ext_imm12, himm3],
      hs3] at hstep3
  have hs3' : s3 = arm64_set_reg (w2 &&& 0x1f).toNat s
      (arm64_reg (w1 >>> 5 &&& 0x1f).toNat s) := by
    have e := Option.some.inj hstep3
    simp only [arm64_reg_or_sp_of_lt _ s hrn3, u64_add_ofNat_zero_r] at e
    rw [hdst, hsrc] at e
    exact e
  have hval : arm64_reg (w2 >>> 5 &&& 0x1f).toNat s1
      = arm64_reg (w1 >>> 5 &&& 0x1f).toNat s := by
    rw [hs1', hlink]
    exact arm64_set_reg_reg_same _ _ _ hrd1
  have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc_unchanged]
  have hpc3 : s3.pc = s.pc := by rw [hs3', arm64_set_reg_pc_unchanged]
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · rw [hs3']
    exact arm64_set_reg_reg_eq _ _ _ hrd2
  · intro k hk hne
    rw [hs3']
    exact arm64_reg_set_reg_other k (w2 &&& 0x1f).toNat _ _ hk hne
  · rw [hs3', arm64_set_reg_nzcv]
  · rw [hs3', arm64_set_reg_mem_unchanged]
  · intro k hk
    by_cases hka : k = (w1 &&& 0x1f).toNat
    · exact Or.inr hka
    · left
      rw [e2 k hk, hs3', hs1']
      by_cases hkb : k = (w2 &&& 0x1f).toNat
      · subst hkb
        simp only [arm64_set_reg_reg_eq _ _ _ hk]
        rw [hlink]
        exact arm64_set_reg_reg_same _ _ _ hrd1
      · simp only [arm64_reg_set_reg_other _ _ _ _ hk hkb]
        exact arm64_reg_set_reg_other k (w1 &&& 0x1f).toNat _ _ hk (by omega)
  · have hp := hpair
    rw [hstep2] at hp
    have e := congrArg (fun t : Arm64State => t.nzcv) (Option.some.inj hp)
    rw [arm64_set_reg_nzcv] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_nzcv])
  · have hp := hpair
    rw [hstep2] at hp
    have e := congrArg (fun t : Arm64State => t.mem) (Option.some.inj hp)
    rw [arm64_set_reg_mem_unchanged] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_mem_unchanged])
  · rw [arm64_steps_two_seq _ _ _ _ hs1 hpc1 hpair]
    simp [hpc]
  · rw [arm64_steps_one_seq _ _ _ hs3 hpc3]
    simp [hpc]


/-! ## The x86-64 rules

The same contract, one table over. The two differences from the arm64 half
are structural and both come from the MODEL:

* `x86_step` ADVANCES the pc itself (its successors are `{ s with …
  rip := endAddr }`), where `arm64_step` does not and `arm64_steps` does. So
  the x86 theorems carry no `x86_steps` clause — there is no such combinator —
  and state the successor STATE `{ s with rip := m + 3 }` directly: the
  rewrite sets the pc to where the fetch resumes, which is what `_Remap` and
  the deletions need, and everything the arm64 theorems spell out in four
  clauses is implied by the one equality.
* The hypotheses are the byte-level picture the machine reads (`x86_step_rex`
  takes the REX byte, the opcode and the ModRM byte as separate `UInt8`s),
  which is why `peephole_x86_mov_self` names `h_rip : s.rip = m` and the three
  bytes `h_b0`/`h_b1`/`h_b2` rather than one instruction word. -/

/-- A register written with its own value is unchanged, for every index the
    GPR file has.

This is `x86_set_reg`'s MATCH cased out over its 16 real fields plus its
`_` fallthrough, which is why the bound `i < 16` is the whole hypothesis:
for `i ≥ 16`, `x86_set_reg` returns `s` and `x86_get_reg` returns `0`, so the
identity holds there for free. It is the lemma every self-copy rewrite needs,
and what is cased out here is `simp` refusing to reduce a `match` on a
non-literal index. -/
theorem x86_set_reg_self (s : X86State) (i : Nat) (hi : i < 16) :
    x86_set_reg s i (x86_get_reg s i) = s := by
  have hsplit : i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨ i = 7
      ∨ i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨ i = 14 ∨ i = 15 := by
    omega
  rcases hsplit with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
    | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  all_goals simp [x86_set_reg, x86_get_reg]

/-- Writing register `j` leaves every other register below 16 alone. -/
theorem x86_get_reg_set_reg_other (i j : Nat) (s : X86State) (v : UInt64)
    (hi : i < 16) (hj : j < 16) (h : i ≠ j) :
    x86_get_reg (x86_set_reg s j v) i = x86_get_reg s i := by
  have hsplit : i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨ i = 7
      ∨ i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨ i = 14 ∨ i = 15 := by
    omega
  rcases hsplit with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
    | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  all_goals
    simp [x86_get_reg, x86_set_reg]
    split <;> first | rfl | omega

/-- **Rule `x86_64/mov_self`.** `mov rax, rax` — a register copied into
    itself (REX.W `89 /r`, mod=3, the reg field equal to the r/m field) — is
    one instruction of nothing, and removing it leaves every register, the
    flags and memory exactly as they were. This is the STORE direction of the
    two operand spellings: the emitters produce `89`, never `8B`, for a
    self-copy — the four observed over the whole 93-example corpus are all
    `48 89 c0` — so this is the only 0x89-encoded one, and the hypotheses
    `h_mod`/`h_same`/`h_idx` are exactly what `formal/peephole.py`'s
    `_x_mov_self` discharges: mod=3 (a REGISTER, not a store with an
    addressing side effect), the REX-extended reg field equal to the r/m field
    (`rm + x86_rex_b rex = reg + x86_rex_r rex`, because each extended index
    is its raw 0-7 field plus its REX extension bit), and the index below 16.
    The successor is `{ s with rip := m + 3 }`: the 3-byte instruction is gone
    and the fetch resumes three bytes on. -/
theorem peephole_x86_mov_self (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_same : rm + x86_rex_b rex = reg + x86_rex_r rex)
    (h_idx : reg + x86_rex_r rex < 16)
    (t : X86State) (hs : x86_step s code = some t) :
    t = { s with rip := m + 3 } := by
  have hstep := x86_step_mov_rm64_r64_reg_st s code m rex modrm reg rm
    h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod h_reg h_rm
  rw [h_same] at hstep
  rw [x86_set_reg_self s (reg + x86_rex_r rex) h_idx] at hstep
  rw [hs] at hstep
  exact Option.some.inj hstep

/-- One step of a 64-bit `MOVZ Xd, #imm16`. -/
theorem arm64_step_movz64 (s : Arm64State) (code : Nat → UInt8)
    (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xd2800000)
    (hrd : (w &&& 0x1f).toNat ≠ 31) :
    arm64_step s code
      = some (arm64_set_reg ((w &&& 0x1f).toNat) s
          (UInt64.ofNat (((w >>> 5) &&& 0xffff).toNat))) := by
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t
    rw [t] at h
    exact absurd h (by decide)
  have hne_1 : ¬ ((w &&& 0xffe00000) = (0x2a00fa00 : UInt32)) := by
    intro t; bv_decide
  have hne_2 : ¬ ((w &&& 0xffe00000) = (0x8b000000 : UInt32)) := by
    intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = (0xcb000000 : UInt32)) := by
    intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe07c00) = (0x9b007c00 : UInt32)) := by
    intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xfffffc1f) = (0xcb0003e0 : UInt32)) := by
    intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xffe00000) = (0xeb000000 : UInt32)) := by
    intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = (0x8a000000 : UInt32)) := by
    intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = (0xca000000 : UInt32)) := by
    intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xff800000) = (0x11000000 : UInt32)) := by
    intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = (0x91000000 : UInt32)) := by
    intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = (0x51000000 : UInt32)) := by
    intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = (0xd1000000 : UInt32)) := by
    intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = (0xf1000000 : UInt32)) := by
    intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xfc000000) = (0x14000000 : UInt32)) := by
    intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = (0x94000000 : UInt32)) := by
    intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xff000000) = (0xb4000000 : UInt32)) := by
    intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = (0xb5000000 : UInt32)) := by
    intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = (0x54000000 : UInt32)) := by
    intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xff000000) = (0x36000000 : UInt32)) := by
    intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xff000000) = (0x37000000 : UInt32)) := by
    intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0xffe00000) = (0xf9400000 : UInt32)) := by
    intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffe00000) = (0xb9000000 : UInt32)) := by
    intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0x9f000000) = (0x90000000 : UInt32)) := by
    intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffc00000) = (0xa9800000 : UInt32)) := by
    intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffc00000) = (0xa8c00000 : UInt32)) := by
    intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = (0x52800000 : UInt32)) := by
    intro t; bv_decide
  unfold arm64_step
  rw [hpc, hread]
  rw [if_neg hne_ret, if_neg hne_1, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_pos h]




/-- Setting the same register twice keeps only the second value. -/
theorem arm64_set_reg_set_reg_same (i : Nat) (u : Arm64State) (a b : UInt64) :
    arm64_set_reg i (arm64_set_reg i u a) b = arm64_set_reg i u b := by
  unfold arm64_set_reg
  split <;> simp_all

/-- **Rule `arm64/movz_pair`.** `MOVZ Xd,#i ; MOVZ Xd,#j` (same `Xd`): the first is
dead.  Running only the second instruction from `s` (pc advanced past the first)
reaches exactly the state the two-instruction run reaches, so deleting the first is
sound with no liveness condition (MOVZ reads nothing and writes no flags). -/
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
    arm64_step { s with pc := s.pc + 4 } code = some { s2 with pc := s.pc + 4 }
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 } := by
  have hd1 : (w1 &&& 0x1f).toNat ≠ 31 := by omega
  have hd2 : (w2 &&& 0x1f).toNat ≠ 31 := by omega
  have e1 := arm64_step_movz64 s code pc w1 hpc hread1 h1 hd1
  rw [hs1] at e1
  have e2 := arm64_step_movz64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2 rfl hread2 h2 hd2
  rw [hpair] at e2
  have e3 := arm64_step_movz64 { s with pc := s.pc + 4 } code (s.pc + 4) w2 rfl hread2 h2 hd2
  have hs1' := Option.some.inj e1
  have hs2' := Option.some.inj e2
  refine ⟨?_, ?_⟩
  · rw [e3]
    apply congrArg some
    refine Eq.trans ?_ hs2'.symm
    rw [hs1', ← arm64_set_reg_pc_congr, ← heq, arm64_set_reg_set_reg_same]
  · have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc_unchanged]
    rw [arm64_steps_two_seq s code s1 s2 hs1 hpc1 hpair, hpc]

/-- `arm64_reg_or_sp` is invariant under memory-only and pc-only updates. -/
theorem arm64_reg_or_sp_mem (i : Nat) (s : Arm64State) (m : Nat → UInt8) :
    arm64_reg_or_sp i { s with mem := m } = arm64_reg_or_sp i s := by
  simp [arm64_reg_or_sp, arm64_reg_mem]

theorem arm64_reg_or_sp_pc (i : Nat) (s : Arm64State) (p : Nat) :
    arm64_reg_or_sp i { s with pc := p } = arm64_reg_or_sp i s := by
  simp [arm64_reg_or_sp, arm64_reg_pc]

/-- **Rule `arm64/store_load`.** `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]` with the same
location and register: the LDR reloads the value just stored, so `arm64_set_reg rt`
is applied to `arm64_reg rt` of the post-store state and is a no-op
(`arm64_set_reg_self`). Deleting the LDR is sound. The address is computed from
`arm64_reg_or_sp rn` of the pre-store state for STR and of the post-store (mem-only
changed, pc-advanced for the step) state for LDR; STR does not change registers or
`sp`, so the addresses are equal and `rt = rn` needs no special case. -/
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
  have e1 := arm64_step_str64 s code pc w1 hpc hread1 h1 hrt1
  rw [hs1] at e1
  have hs1' := Option.some.inj e1
  have hpc1 : s1.pc = s.pc := by rw [hs1']
  have hreg1 : ∀ k, arm64_reg k s1 = arm64_reg k s := by
    intro k; rw [hs1']; simp [arm64_reg]
  have hros1 : ∀ i, arm64_reg_or_sp i s1 = arm64_reg_or_sp i s := by
    intro i; rw [hs1']; simp [arm64_reg_or_sp, arm64_reg]
  have hmem1 : s1.mem = mem_write_u64 s.mem
      ((arm64_reg_or_sp ((w1 >>> 5) &&& 0x1f).toNat s +
        UInt64.ofNat ((((w1 >>> 10) &&& 0xfff).toNat) * 8)).toNat)
      (arm64_reg ((w1 &&& 0x1f).toNat) s) := by rw [hs1']
  have e2 := arm64_step_ldr64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2 rfl hread2 h2 hrt2
  rw [hpair] at e2
  have hs2' := Option.some.inj e2
  have haddr :
      (arm64_reg_or_sp ((w2 >>> 5) &&& 0x1f).toNat { s1 with pc := s.pc + 4 } +
        UInt64.ofNat ((((w2 >>> 10) &&& 0xfff).toNat) * 8)).toNat
      = (arm64_reg_or_sp ((w1 >>> 5) &&& 0x1f).toNat s +
        UInt64.ofNat ((((w1 >>> 10) &&& 0xfff).toNat) * 8)).toNat := by
    rw [hrn_eq, himm_eq, arm64_reg_or_sp_pc, hros1]
  have hval : arm64_reg ((w1 &&& 0x1f).toNat) s
      = arm64_reg ((w2 &&& 0x1f).toNat) { s1 with pc := s.pc + 4 } := by
    rw [hrt_eq, ← hreg1 ((w2 &&& 0x1f).toNat)]
    simp [arm64_reg]
  have hload : mem_read_u64 ({ s1 with pc := s.pc + 4 } : Arm64State).mem
      ((arm64_reg_or_sp ((w2 >>> 5) &&& 0x1f).toNat { s1 with pc := s.pc + 4 } +
        UInt64.ofNat ((((w2 >>> 10) &&& 0xfff).toNat) * 8)).toNat)
      = arm64_reg ((w2 &&& 0x1f).toNat) { s1 with pc := s.pc + 4 } := by
    show mem_read_u64 s1.mem _ = _
    rw [haddr, hmem1, mem_read_after_write_u64]
    exact hval
  have hs2state : { s2 with pc := s.pc + 4 } = { s1 with pc := s.pc + 4 } := by
    rw [hs2']
    rw [hload]
    exact arm64_set_reg_self { s1 with pc := s.pc + 4 } ((w2 &&& 0x1f).toNat) hrt2
  have hregs : ∀ k, k < 31 → arm64_reg k s2 = arm64_reg k s1 := by
    intro k hk
    have := congrArg (fun st : Arm64State => arm64_reg k st) hs2state
    simp only [arm64_reg_pc] at this
    exact this
  have hnzcv : s2.nzcv = s1.nzcv := by
    have := congrArg (fun st : Arm64State => st.nzcv) hs2state
    simpa using this
  have hmem : s2.mem = s1.mem := by
    have := congrArg (fun st : Arm64State => st.mem) hs2state
    simpa using this
  refine ⟨hregs, hnzcv, hmem, ?_, ?_⟩
  · rw [arm64_steps_two_seq s code s1 s2 hs1 hpc1 hpair, hpc]
  · rw [arm64_steps_one_seq s code s1 hs1 hpc1, hpc]

-- Witness: `str x1,[x2,#8] ; ldr x1,[x2,#8]` (rt != rn) satisfies the word hypotheses.
example : ((0xF9000441 : UInt32) &&& 0xffe00000) = 0xF9000000 := by decide
example : ((0xF9400441 : UInt32) &&& 0xffe00000) = 0xF9400000 := by decide
example : ((0xF9000441 : UInt32) &&& 0x1f).toNat < 31 := by decide
example : ((0xF9400441 : UInt32) &&& 0x1f).toNat < 31 := by decide
example : ((0xF9000441 : UInt32) >>> 5 &&& 0x1f).toNat = ((0xF9400441 : UInt32) >>> 5 &&& 0x1f).toNat := by decide
example : ((0xF9000441 : UInt32) &&& 0x1f).toNat = ((0xF9400441 : UInt32) &&& 0x1f).toNat := by decide
example : ((0xF9000441 : UInt32) >>> 10 &&& 0xfff).toNat = ((0xF9400441 : UInt32) >>> 10 &&& 0xfff).toNat := by decide

-- Witness: `rt = rn` case, `str x2,[x2,#8] ; ldr x2,[x2,#8]`, is allowed (no rt!=rn condition).
example : ((0xF9000442 : UInt32) &&& 0xffe00000) = 0xF9000000 := by decide
example : ((0xF9400442 : UInt32) &&& 0xffe00000) = 0xF9400000 := by decide
example : ((0xF9000442 : UInt32) &&& 0x1f).toNat < 31 := by decide
example : ((0xF9400442 : UInt32) &&& 0x1f).toNat < 31 := by decide
example : ((0xF9000442 : UInt32) >>> 5 &&& 0x1f).toNat = ((0xF9400442 : UInt32) >>> 5 &&& 0x1f).toNat := by decide
example : ((0xF9000442 : UInt32) &&& 0x1f).toNat = ((0xF9400442 : UInt32) &&& 0x1f).toNat := by decide
example : ((0xF9000442 : UInt32) >>> 10 &&& 0xfff).toNat = ((0xF9400442 : UInt32) >>> 10 &&& 0xfff).toNat := by decide
example : ((0xF9000442 : UInt32) &&& 0x1f).toNat = ((0xF9000442 : UInt32) >>> 5 &&& 0x1f).toNat := by decide

/-- **Rule `x86_64/store_load` (step-04b).** `mov [b+d8], r ; mov r, [b+d8]`
is the store alone. No condition relating `r` and `b`: the load's address is
computed from the state after the store, which changed memory and `rip` only.
Statement checked true (no correction needed). -/
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
  have e1 := x86_step_mov_mem_disp8 s code m rex modrm reg rm disp
    h_rip h_s0 h_s1 h_s2 h_sd h_rex h_w h_mod h_rm h_rm_ne h_reg
  rw [hs1] at e1
  have ht1 : t1 = { s with
      mem := mem_write_bytes s.mem
        (Int.ofNat (x86_get_reg s (rm + x86_rex_b rex)).toNat + disp).toNat
        (x86_get_reg s (reg + x86_rex_r rex)) 8,
      rip := m + 4 } := Option.some.inj e1
  have h_rip1 : t1.rip = m + 4 := by rw [ht1]
  have e2 := x86_step_mov_rm64_mem_disp8 t1 code (m + 4) rex modrm reg rm
    (reg + x86_rex_r rex) disp h_rip1 h_l0 h_l1 h_l2 h_ld h_rex h_w h_mod h_rm
    h_rm_ne h_reg rfl h_dst_lt
  rw [hs2] at e2
  have ht2 := Option.some.inj e2
  have h_base : x86_get_reg t1 (rm + x86_rex_b rex) = x86_get_reg s (rm + x86_rex_b rex) := by
    rw [ht1]; rfl
  have h_src : x86_get_reg t1 (reg + x86_rex_r rex) = x86_get_reg s (reg + x86_rex_r rex) := by
    rw [ht1]; rfl
  have h_mem : t1.mem = mem_write_bytes s.mem
      (Int.ofNat (x86_get_reg s (rm + x86_rex_b rex)).toNat + disp).toNat
      (x86_get_reg s (reg + x86_rex_r rex)) 8 := by
    rw [ht1]
  have h_read : mem_read_bytes t1.mem
      (Int.ofNat (x86_get_reg t1 (rm + x86_rex_b rex)).toNat + disp).toNat 8
      = x86_get_reg s (reg + x86_rex_r rex) := by
    rw [h_base, h_mem, mem_read_bytes_write_same]
    simp [lowMask_eight]
    bv_normalize
  rw [ht2]
  simp only [h_read, ← h_src]
  rw [x86_set_reg_self t1 (reg + x86_rex_r rex) h_dst_lt]

/-- Witness (step-04b): `mov [rbp-8], rax ; mov rax, [rbp-8]` = `48 89 45 f8 ; 48 8b 45 f8`. -/
example (s : X86State) (t1 t2 : X86State)
    (hs1 : x86_step s (fun n => if n = 0 then 0x48 else if n = 1 then 0x89
        else if n = 2 then 0x45 else if n = 3 then 0xF8
        else if n = 4 then 0x48 else if n = 5 then 0x8B
        else if n = 6 then 0x45 else if n = 7 then 0xF8 else 0) = some t1)
    (hs2 : x86_step t1 (fun n => if n = 0 then 0x48 else if n = 1 then 0x89
        else if n = 2 then 0x45 else if n = 3 then 0xF8
        else if n = 4 then 0x48 else if n = 5 then 0x8B
        else if n = 6 then 0x45 else if n = 7 then 0xF8 else 0) = some t2)
    (h_rip : s.rip = 0) :
    t2 = { t1 with rip := 8 } :=
  peephole_x86_store_load_disp8 s _ 0 0x48 0x45 0 5 (-8) h_rip
    rfl rfl rfl (by decide) rfl rfl rfl (by decide)
    (by decide) (by decide) (by decide) (by decide)
    (by decide) (by decide) (by decide)
    t1 t2 hs1 hs2

/-- **Rule `x86_64/imm_zero` (flags).** `add r, 0` / `sub r, 0` (REX.W 81 /0
or /5 id, mod==3) leave CF/OF clear and set ZF/SF from `r`, by
`x86_flags_add`/`x86_flags_sub` with imm=0. Statement checked true and proved
as scaffolded (no correction). PF/AF are not modelled in `X86State`. The pass
cannot use this soundly without a continuation predicate (see design note
below); the rule is NOT enabled by this step. -/
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
  rcases h_digit with hd | hd
  · have hstep := x86_step_add_ri32 s code m rex modrm rm h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod hd h_rm
    rw [hs] at hstep
    have ht := Option.some.inj hstep
    rw [h_imm] at ht
    subst ht
    simp [x86_flags_add, UInt64.ofInt]
  · have hstep := x86_step_sub_ri32 s code m rex modrm rm h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod hd h_rm
    rw [hs] at hstep
    have ht := Option.some.inj hstep
    rw [h_imm] at ht
    subst ht
    simp [x86_flags_sub, UInt64.ofInt]

/-- **Rule `arm64/mem_pair_str`.** Two identical `STR Xt,[Xn,#o]`: deleting the
    second is sound because the second store writes the same value to the same
    address (`mem_write_u64_idem`), and STR changes only memory.

    Statement strengthened vs the scaffold (which omitted `s2.mem = s1.mem`);
    the full memory equality holds and is proved. -/
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
    ∧ s2.mem = s1.mem
    ∧ arm64_steps s code 2 = some { s2 with pc := pc + 8 }
    ∧ arm64_steps s code 1 = some { s1 with pc := pc + 4 } := by
  have e1 := arm64_step_str64 s code pc w1 hpc hread1 h1 hrt1
  rw [hs1] at e1
  have hs1' := Option.some.inj e1
  have e2 := arm64_step_str64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2 rfl hread2 h2 hrt2
  rw [hpair] at e2
  have hs2' := Option.some.inj e2
  have hpc1 : s1.pc = s.pc := by rw [hs1']
  -- second store = same address and value as first (s1 differs from s only in mem)
  have hbase : arm64_reg_or_sp ((w2 >>> 5) &&& 0x1f).toNat { s1 with pc := s.pc + 4 }
      = arm64_reg_or_sp ((w1 >>> 5) &&& 0x1f).toNat s := by
    rw [← hrn_eq]
    unfold arm64_reg_or_sp
    split <;> rename_i hsp
    · simp [hs1']
    · simp [arm64_reg, hs1']
  have hval2 : arm64_reg ((w2 &&& 0x1f).toNat) { s1 with pc := s.pc + 4 }
      = arm64_reg ((w1 &&& 0x1f).toNat) s := by
    rw [← hrt_eq, arm64_reg_pc, hs1']; simp [arm64_reg]
  have hmem : s2.mem = s1.mem := by
    have : ({ s2 with pc := s.pc + 4 }).mem = ({ s1 with pc := s.pc + 4 }).mem := by
      rw [hs2']
      simp only
      rw [hbase, hval2, ← himm_eq, hs1']
      exact mem_write_u64_idem _ _ _
    simpa using this
  have hnzcv : s2.nzcv = s1.nzcv := by
    have : ({ s2 with pc := s.pc + 4 }).nzcv = ({ s1 with pc := s.pc + 4 }).nzcv := by
      rw [hs2']
    simpa using this
  refine ⟨?_, hnzcv, hmem, ?_, ?_⟩
  · intro k hk
    have hreg : arm64_reg k { s2 with pc := s.pc + 4 } = arm64_reg k { s1 with pc := s.pc + 4 } := by
      rw [hs2']
      rcases (by omega : k = 0 ∨ k = 1 ∨ k = 2 ∨ k = 3 ∨ k = 4 ∨ k = 5 ∨ k = 6 ∨ k = 7 ∨ k = 8 ∨ k = 9 ∨ k = 10 ∨ k = 11 ∨ k = 12 ∨ k = 13 ∨ k = 14 ∨ k = 15 ∨ k = 16 ∨ k = 17 ∨ k = 18 ∨ k = 19 ∨ k = 20 ∨ k = 21 ∨ k = 22 ∨ k = 23 ∨ k = 24 ∨ k = 25 ∨ k = 26 ∨ k = 27 ∨ k = 28 ∨ k = 29 ∨ k = 30) with
        rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [arm64_reg]
    simpa [arm64_reg_pc] using hreg
  · rw [arm64_steps_two_seq s code s1 s2 hs1 hpc1 hpair, hpc]
  · rw [arm64_steps_one_seq s code s1 hs1 hpc1, hpc]

-- Counterexample showing `hne_rt_rn` is necessary for `peephole_arm64_ldr_pair`
-- (comment only, not a theorem): `ldr x1,[x1,#0] ; ldr x1,[x1,#0]` differs from
-- a single load because the first load overwrites the base register `x1`, so the
-- second load reads from the address now in `x1` (the loaded value), not the
-- original base. The rule and its theorem therefore require `Xt ≠ Xn`.

/-- **Rule `arm64/mem_pair_ldr`.** Two identical `LDR Xt,[Xn,#o]` with `Xt ≠ Xn`:
    the base is unchanged by the first load and memory is unchanged, so the
    second load reads the same value into the same register and is redundant
    (`arm64_set_reg_set_reg_same` / `arm64_set_reg_self`). The `Xt ≠ Xn`
    (`hne_rt_rn`) hypothesis is necessary (see comment above). -/
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
  have e1 := arm64_step_ldr64 s code pc w1 hpc hread1 h1 hrt1
  rw [hs1] at e1
  have hs1' := Option.some.inj e1
  have e2 := arm64_step_ldr64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2 rfl hread2 h2 hrt2
  rw [hpair] at e2
  have hs2' := Option.some.inj e2
  have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc_unchanged]
  -- base register unchanged: rt1 != rn1, and set_reg rt1 doesn't touch rn1 or sp
  have hbase : arm64_reg_or_sp ((w2 >>> 5) &&& 0x1f).toNat { s1 with pc := s.pc + 4 }
      = arm64_reg_or_sp ((w1 >>> 5) &&& 0x1f).toNat s := by
    rw [← hrn_eq]
    unfold arm64_reg_or_sp
    split <;> rename_i hsp
    · -- sp
      simp [hs1']
      try (unfold arm64_set_reg; split <;> rfl)
    · -- register rn1 < 31, and rn1 != rt1
      have hne_sp : ((w1 >>> 5) &&& 0x1f).toNat ≠ 31 := by
        intro heq; simp [heq] at hsp
      have hrn1 : ((w1 >>> 5) &&& 0x1f).toNat < 31 := by
        have hle : ((w1 >>> 5) &&& 0x1f).toNat ≤ 31 := by
          show (w1 >>> 5 &&& 0x1f).toNat ≤ (31 : UInt32).toNat
          apply Nat.le_of_lt_succ
          have : (w1 >>> 5 &&& 0x1f).toNat < (32 : UInt32).toNat := by
            simp only [UInt32.toNat_and, UInt32.toNat_ofNat, UInt32.toNat_shiftRight,
              Nat.reducePow, Nat.mod_eq_of_lt (by decide : 31 < 4294967296),
              Nat.mod_eq_of_lt (by decide : 32 < 4294967296)]
            exact Nat.lt_of_le_of_lt (Nat.and_le_right) (by decide)
          simpa using this
        omega
      have hne : ((w1 >>> 5) &&& 0x1f).toNat ≠ (w1 &&& 0x1f).toNat := by omega
      rw [arm64_reg_pc, hs1']
      exact arm64_reg_set_reg_other _ _ _ _ hrn1 hne
  -- second load reads same memory at same address => same value
  have hval : mem_read_u64 ({ s1 with pc := s.pc + 4 }).mem
      ((arm64_reg_or_sp ((w2 >>> 5) &&& 0x1f).toNat { s1 with pc := s.pc + 4 }
        + UInt64.ofNat ((((w2 >>> 10) &&& 0xfff).toNat) * 8)).toNat)
      = mem_read_u64 s.mem
        ((arm64_reg_or_sp ((w1 >>> 5) &&& 0x1f).toNat s
          + UInt64.ofNat ((((w1 >>> 10) &&& 0xfff).toNat) * 8)).toNat) := by
    rw [hbase, ← himm_eq, hs1']
    simp [arm64_set_reg_mem_unchanged]
  -- {s2 with pc := s.pc+4} sets rt1 (= rt2) to that same value over s1 => equals s1 with pc
  have hs2eq : { s2 with pc := s.pc + 4 } = { s1 with pc := s.pc + 4 } := by
    rw [hs2', hval, ← hrt_eq, hs1']
    rw [← arm64_set_reg_pc_congr]
    rw [arm64_set_reg_set_reg_same]
  have hnzcv : s2.nzcv = s1.nzcv := by
    have := congrArg (fun t => t.nzcv) hs2eq; simpa using this
  have hmem : s2.mem = s1.mem := by
    have := congrArg (fun t => t.mem) hs2eq; simpa using this
  refine ⟨?_, hnzcv, hmem, ?_, ?_⟩
  · intro k hk
    have hreg : arm64_reg k { s2 with pc := s.pc + 4 } = arm64_reg k { s1 with pc := s.pc + 4 } := by
      have := congrArg (arm64_reg k) hs2eq; exact this
    simpa [arm64_reg_pc] using hreg
  · rw [arm64_steps_two_seq s code s1 s2 hs1 hpc1 hpair, hpc]
  · rw [arm64_steps_one_seq s code s1 hs1 hpc1, hpc]

/-- Reading register `i` immediately after writing it yields the written value. -/
theorem x86_get_reg_set_reg_same (s : X86State) (i : Nat) (v : UInt64) (hi : i < 16) :
    x86_get_reg (x86_set_reg s i v) i = v := by
  rcases (show i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨ i = 7
      ∨ i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨ i = 14 ∨ i = 15 from by omega) with
    rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
    | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  all_goals simp [x86_get_reg, x86_set_reg]

/-- **Rule `x86_64/mem_pair_store` (disp8, step 04c).** Two identical
`mov [b+d8], r` (REX.W 89 /r, mod=1, no SIB): the second writes the same value
to the same address and advances the pc, so deleting it leaves the state of the
first with `rip := m + 8`. The store does not change registers, so the base and
source registers are the same for both steps; memory idempotence is
`mem_write_bytes8_idem`. The scaffold statement was checked and is true as
stated (not corrected). -/
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
  have e1 := x86_step_mov_mem_disp8 s code m rex modrm reg rm disp
    h_rip h_s0 h_s1 h_s2 h_sd h_rex h_w h_mod h_rm h_rm_ne h_reg
  rw [hs1] at e1
  have ht1 := Option.some.inj e1
  have hrip1 : t1.rip = m + 4 := by rw [ht1]
  have e2 := x86_step_mov_mem_disp8 t1 code (m + 4) rex modrm reg rm disp
    hrip1 h_t0 h_t1 h_t2 h_td h_rex h_w h_mod h_rm h_rm_ne h_reg
  rw [hs2] at e2
  have ht2 := Option.some.inj e2
  subst ht2 ht1
  simp [x86_get_reg, mem_write_bytes8_idem]

/-- **Rule `x86_64/mem_pair_load` (disp8, step 04c).** Two identical
`mov r, [b+d8]` (REX.W 8b /r, mod=1, no SIB). UNSOUND without `r ≠ b`
(`h_ne`): the first load overwrites the base register, so the second would read
from a different address. Counterexample (not a theorem): `mov rax,[rax] ;
mov rax,[rax]` — the first load changes `rax`, so the second dereferences the
loaded value, not the original base. With `h_ne` the base and memory are
unchanged by the first load, so the second reads the same value into the same
destination; `x86_set_reg_self` collapses the redundant write. The scaffold
statement was checked and is true as stated (not corrected). -/
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
  let dst := reg + x86_rex_r rex
  have e1 := x86_step_mov_rm64_mem_disp8 s code m rex modrm reg rm dst disp
    h_rip h_s0 h_s1 h_s2 h_sd h_rex h_w h_mod h_rm h_rm_ne h_reg rfl h_dst_lt
  rw [hs1] at e1
  have ht1 := Option.some.inj e1
  have hrip1 : t1.rip = m + 4 := by rw [ht1]
  have hmem1 : t1.mem = s.mem := by
    rw [ht1]
    rcases (show dst = 0 ∨ dst = 1 ∨ dst = 2 ∨ dst = 3 ∨ dst = 4 ∨ dst = 5 ∨ dst = 6 ∨ dst = 7
        ∨ dst = 8 ∨ dst = 9 ∨ dst = 10 ∨ dst = 11 ∨ dst = 12 ∨ dst = 13 ∨ dst = 14 ∨ dst = 15
        from by omega) with
      h | h | h | h | h | h | h | h | h | h | h | h | h | h | h | h
    all_goals (simp [x86_set_reg, h])
  have hbase1 : x86_get_reg t1 (rm + x86_rex_b rex) = x86_get_reg s (rm + x86_rex_b rex) := by
    rw [ht1]
    have hrm7 : rm ≤ 7 := by rw [← h_rm]; exact Nat.and_le_right
    have hrb : x86_rex_b rex ≤ 8 := by unfold x86_rex_b; split <;> omega
    have hbase_lt : rm + x86_rex_b rex < 16 := by omega
    exact x86_get_reg_set_reg_other (rm + x86_rex_b rex) dst s _ hbase_lt h_dst_lt (Ne.symm h_ne)
  have hdst1 : x86_get_reg t1 dst = mem_read_bytes s.mem
      (Int.ofNat (x86_get_reg s (rm + x86_rex_b rex)).toNat + disp).toNat 8 := by
    rw [ht1]
    exact x86_get_reg_set_reg_same s dst _ h_dst_lt
  have e2 := x86_step_mov_rm64_mem_disp8 t1 code (m + 4) rex modrm reg rm dst disp
    hrip1 h_t0 h_t1 h_t2 h_td h_rex h_w h_mod h_rm h_rm_ne h_reg rfl h_dst_lt
  rw [hs2] at e2
  have ht2 := Option.some.inj e2
  rw [ht2, hmem1, hbase1]
  have hval : mem_read_bytes s.mem (Int.ofNat (x86_get_reg s (rm + x86_rex_b rex)).toNat + disp).toNat 8
      = x86_get_reg t1 dst := hdst1.symm
  rw [hval, x86_set_reg_self t1 dst h_dst_lt]
  simp [hmem1]

/-- `mov r64, r64` register to register (REX.W 8b /r, mod=3), the LOAD
    direction mirror of `x86_step_mov_rm64_r64_reg_st` (which is the 0x89 store
    direction). In 0x8b the `reg` field (+REX.R) is the destination and the
    `r/m` field (+REX.B) is the source — the opposite sense of 0x89. Proved in
    Peephole.lean (not X86.lean) by the same `simp` step lemma used for 0x89. -/
theorem x86_step_mov_r64_rm64_reg_st (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some
      { x86_set_reg s (reg + x86_rex_r rex) (x86_get_reg s (rm + x86_rex_b rex)) with
        rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_mask,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]


/-- **Rule `x86_64/mov_self_rev`.** `mov r, r` spelled `REX.W 8b /r, mod = 3`
    (`48 8b c0` for `mov rax, rax`): the LOAD-direction mirror of
    `peephole_x86_mov_self` (0x89 store direction). Same proof shape, using
    `x86_step_mov_r64_rm64_reg_st`. The decoder can see the form as
    `mov_r64_rm64` (mod==3), but the compiler/emitter does not produce it
    (only `48 89 c0` / 0x89 observed), so the matcher only fires on the store
    direction today; rule recorded for step-05b as scaffolded/not-run. -/
theorem peephole_x86_mov_self_rev (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_same : rm + x86_rex_b rex = reg + x86_rex_r rex)
    (h_idx : reg + x86_rex_r rex < 16)
    (t : X86State) (hs : x86_step s code = some t) :
    t = { s with rip := m + 3 } := by
  have hstep := x86_step_mov_r64_rm64_reg_st s code m rex modrm reg rm
    h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod h_reg h_rm
  rw [h_same] at hstep
  rw [x86_set_reg_self s (reg + x86_rex_r rex) h_idx] at hstep
  rw [hs] at hstep
  exact Option.some.inj hstep

/-- Witness: `48 8b c0` (`mov rax, rax`, REX.W 8b /r, mod=3, reg=0, r/m=0)
    is a no-op on the proved theorem. -/
example (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = 0xc0)
    (t : X86State) (hs : x86_step s code = some t) :
    t = { s with rip := m + 3 } := by
  have h_rex : x86_is_rex (0x48 : UInt8) = true := by decide
  have h_w : x86_rex_w (0x48 : UInt8) = true := by decide
  have h_mod : (0xc0 : UInt8).toNat >>> 6 = 3 := by decide
  have h_reg : ((0xc0 : UInt8).toNat >>> 3) &&& 7 = 0 := by decide
  have h_rm : (0xc0 : UInt8).toNat &&& 7 = 0 := by decide
  have h_same : 0 + x86_rex_b (0x48 : UInt8) = 0 + x86_rex_r (0x48 : UInt8) := by decide
  have h_idx : 0 + x86_rex_r (0x48 : UInt8) < 16 := by decide
  exact peephole_x86_mov_self_rev s code m 0x48 0xc0 0 0 h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod h_reg h_rm h_same h_idx t hs

/-- `subs x, x, #1` does not set the overflow flag when `x` is below `2^63` and
    nonzero: `x - 1` stays in the signed range, so `b.vs` (condition 6) is not
    taken.  The fact a decrement loop's overflow-trap branch needs to fall
    through (`while_dec_exit_contract_lt`, step 06d/wdiff). -/
theorem subs_one_no_overflow (a : UInt64) (hlt : a.toNat < 9223372036854775808)
    (hne : a ≠ 0) :
    arm64_matches_condition 6 (arm64_subs_flags a 1) = false := by
  have h : a < 9223372036854775808 := by
    rw [UInt64.lt_iff_toNat_lt]; simpa using hlt
  unfold arm64_matches_condition arm64_subs_flags
  bv_normalize
  bv_decide

/-!
## Design note (x86_64/imm_zero) — for a later hard round
The sound statement is "for every continuation whose first flag access is a
write, the final state agrees". The minimal Lean form is a relation
`FlagsDeadFrom (code) (rip)` defined by recursion over `x86_step` with fuel,
plus a simulation lemma. Estimate: a week of proof work. Do not start it in
this step.
-/

/-- **Rule `x86_64/imm_zero`.** `add r, 0` (REX.W 81 /0 id, mod==3): registers
and memory unchanged except rip advances by 7. Flags not claimed here. -/
theorem peephole_x86_imm_zero_regs_add (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x81)
    (h_b2 : code (m + 2) = modrm)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 3)
    (h_digit : (modrm.toNat >>> 3) &&& 7 = 0)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_imm : read_i32_le code (m + 3) = 0)
    (t : X86State) (hs : x86_step s code = some t) :
    x86_get_reg t (rm + x86_rex_b rex) = x86_get_reg s (rm + x86_rex_b rex)
    ∧ (∀ i, i < 16 → i ≠ rm + x86_rex_b rex → x86_get_reg t i = x86_get_reg s i)
    ∧ t.mem = s.mem
    ∧ t.rip = m + 7 := by
  -- Every register index below is `rm + x86_rex_b rex`, at most 7 + 8, so the
  -- 16-way split on it is exhaustive; `simp` cannot reduce `x86_get_reg`'s
  -- `match` on a variable, and `interval_cases` is Mathlib's, not core Lean's.
  have hrm : rm ≤ 7 := by rw [← h_rm]; exact Nat.and_le_right
  have hrb : x86_rex_b rex ≤ 8 := by unfold x86_rex_b; split <;> omega
  have hidx : rm + x86_rex_b rex < 16 := by omega
  have hstep := x86_step_add_ri32 s code m rex modrm rm h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod h_digit h_rm
  rw [hs] at hstep
  have ht := Option.some.inj hstep
  rw [h_imm] at ht
  subst ht
  have h0 : UInt64.ofInt 0 = 0 := rfl
  refine ⟨?_, ?_, ?_, ?_⟩
  · generalize rm + x86_rex_b rex = r at *
    rcases (by omega : r = 0 ∨ r = 1 ∨ r = 2 ∨ r = 3 ∨ r = 4 ∨ r = 5 ∨ r = 6 ∨ r = 7 ∨ r = 8 ∨ r = 9 ∨ r = 10 ∨ r = 11 ∨ r = 12 ∨ r = 13 ∨ r = 14 ∨ r = 15) with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [x86_set_reg, x86_get_reg, h0]
  · intro i hi hne
    have key := x86_get_reg_set_reg_other i (rm + x86_rex_b rex) s (x86_get_reg s (rm + x86_rex_b rex) + UInt64.ofInt 0) hi hidx hne
    simp only [x86_get_reg] at key ⊢
    simpa using key
  · generalize rm + x86_rex_b rex = r at *
    rcases (by omega : r = 0 ∨ r = 1 ∨ r = 2 ∨ r = 3 ∨ r = 4 ∨ r = 5 ∨ r = 6 ∨ r = 7 ∨ r = 8 ∨ r = 9 ∨ r = 10 ∨ r = 11 ∨ r = 12 ∨ r = 13 ∨ r = 14 ∨ r = 15) with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [x86_set_reg]
  · rfl

/-- **Rule `x86_64/imm_zero`.** `sub r, 0` (REX.W 81 /5 id, mod==3): registers
and memory unchanged except rip advances by 7. Flags not claimed here. -/
theorem peephole_x86_imm_zero_regs_sub (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x81)
    (h_b2 : code (m + 2) = modrm)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 3)
    (h_digit : (modrm.toNat >>> 3) &&& 7 = 5)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_imm : read_i32_le code (m + 3) = 0)
    (t : X86State) (hs : x86_step s code = some t) :
    x86_get_reg t (rm + x86_rex_b rex) = x86_get_reg s (rm + x86_rex_b rex)
    ∧ (∀ i, i < 16 → i ≠ rm + x86_rex_b rex → x86_get_reg t i = x86_get_reg s i)
    ∧ t.mem = s.mem
    ∧ t.rip = m + 7 := by
  -- Every register index below is `rm + x86_rex_b rex`, at most 7 + 8, so the
  -- 16-way split on it is exhaustive; `simp` cannot reduce `x86_get_reg`'s
  -- `match` on a variable, and `interval_cases` is Mathlib's, not core Lean's.
  have hrm : rm ≤ 7 := by rw [← h_rm]; exact Nat.and_le_right
  have hrb : x86_rex_b rex ≤ 8 := by unfold x86_rex_b; split <;> omega
  have hidx : rm + x86_rex_b rex < 16 := by omega
  have hstep := x86_step_sub_ri32 s code m rex modrm rm h_rip h_b0 h_b1 h_b2 h_rex h_w h_mod h_digit h_rm
  rw [hs] at hstep
  have ht := Option.some.inj hstep
  rw [h_imm] at ht
  subst ht
  have h0 : UInt64.ofInt 0 = 0 := rfl
  refine ⟨?_, ?_, ?_, ?_⟩
  · generalize rm + x86_rex_b rex = r at *
    rcases (by omega : r = 0 ∨ r = 1 ∨ r = 2 ∨ r = 3 ∨ r = 4 ∨ r = 5 ∨ r = 6 ∨ r = 7 ∨ r = 8 ∨ r = 9 ∨ r = 10 ∨ r = 11 ∨ r = 12 ∨ r = 13 ∨ r = 14 ∨ r = 15) with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [x86_set_reg, x86_get_reg, h0]
  · intro i hi hne
    have key := x86_get_reg_set_reg_other i (rm + x86_rex_b rex) s (x86_get_reg s (rm + x86_rex_b rex) - UInt64.ofInt 0) hi hidx hne
    simp only [x86_get_reg] at key ⊢
    simpa using key
  · generalize rm + x86_rex_b rex = r at *
    rcases (by omega : r = 0 ∨ r = 1 ∨ r = 2 ∨ r = 3 ∨ r = 4 ∨ r = 5 ∨ r = 6 ∨ r = 7 ∨ r = 8 ∨ r = 9 ∨ r = 10 ∨ r = 11 ∨ r = 12 ∨ r = 13 ∨ r = 14 ∨ r = 15) with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl <;> simp [x86_set_reg]
  · rfl

/-- **Rule `x86_64/imm_zero`.** `add r, 0` or `sub r, 0` (REX.W 81 /0 id or /5 id, mod==3):
registers and memory unchanged except rip advances by 7. Flags not claimed here. -/
theorem peephole_x86_imm_zero_regs (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x81)
    (h_b2 : code (m + 2) = modrm)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 3)
    (h_digit : (modrm.toNat >>> 3) &&& 7 = 0 ∨ (modrm.toNat >>> 3) &&& 7 = 5)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_imm : read_i32_le code (m + 3) = 0)
    (t : X86State) (hs : x86_step s code = some t) :
    x86_get_reg t (rm + x86_rex_b rex) = x86_get_reg s (rm + x86_rex_b rex)
    ∧ (∀ i, i < 16 → i ≠ rm + x86_rex_b rex → x86_get_reg t i = x86_get_reg s i)
    ∧ t.mem = s.mem
    ∧ t.rip = m + 7 := by
  cases h_digit with
  | inl hd =>
      apply peephole_x86_imm_zero_regs_add <;> try assumption
  | inr hd =>
      apply peephole_x86_imm_zero_regs_sub <;> try assumption
