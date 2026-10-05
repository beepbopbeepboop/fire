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

theorem arm64_set_reg_mem' (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).mem = s.mem := by
  unfold arm64_set_reg; split <;> rfl

theorem arm64_set_reg_pc' (i : Nat) (s : Arm64State) (v : UInt64) :
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
`arm64_reg` below 31; and the operand is `imm12` alone with the `sh` bit NOT
read — which is the model/hardware gap the `sh = 0` side condition exists to
avoid leaning on.

The conclusion is stated in the model's OWN terms (`arm64_reg_or_sp`,
`imm12` unsubstituted) so that the proof is the decode chain and nothing else;
the rules below rewrite those two terms with `arm64_reg_or_sp_of_lt` and their
`imm` hypotheses. -/

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
            + UInt64.ofNat ((w >>> 10) &&& 0xfff).toNat)) := by
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
  rw [himm, hs] at hstep
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
  · rw [ht]; exact arm64_set_reg_mem' _ s _
  · rw [arm64_steps_one_seq _ _ _ hs (by rw [ht, arm64_set_reg_pc', hpc])]
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
  rw [hi, hs1] at hstep1
  have hs1' : s1 = arm64_set_reg (w1 &&& 0x1f).toNat s
      (arm64_reg_or_sp (w1 >>> 5 &&& 0x1f).toNat s + UInt64.ofNat i) :=
    Option.some.inj hstep1
  simp only [arm64_reg_or_sp_of_lt _ s hrn1] at hs1'
  have hstep2 := arm64_step_add_imm64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2
    rfl hread2 h2 (by omega)
  rw [hj] at hstep2
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
  rw [hfuse, hs3] at hstep3
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
  have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc']
  have hpc3 : s3.pc = s.pc := by rw [hs3', arm64_set_reg_pc']
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
    rw [arm64_set_reg_mem'] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_mem'])
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
  rw [himm1, hs1] at hstep1
  have hs1' : s1 = arm64_set_reg (w1 &&& 0x1f).toNat s
      (arm64_reg (w1 >>> 5 &&& 0x1f).toNat s) := by
    have e := Option.some.inj hstep1
    simp only [arm64_reg_or_sp_of_lt _ s hrn1, u64_add_ofNat_zero_r] at e
    exact e
  have hstep2 := arm64_step_add_imm64 { s1 with pc := s.pc + 4 } code (s.pc + 4) w2
    rfl hread2 h2 (by omega)
  rw [himm2] at hstep2
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
  rw [himm3, hs3] at hstep3
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
  have hpc1 : s1.pc = s.pc := by rw [hs1', arm64_set_reg_pc']
  have hpc3 : s3.pc = s.pc := by rw [hs3', arm64_set_reg_pc']
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · rw [hs3']
    exact arm64_set_reg_reg_eq _ _ _ hrd2
  · intro k hk hne
    rw [hs3']
    exact arm64_reg_set_reg_other k (w2 &&& 0x1f).toNat _ _ hk hne
  · rw [hs3', arm64_set_reg_nzcv]
  · rw [hs3', arm64_set_reg_mem']
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
    rw [arm64_set_reg_mem'] at e
    exact e.symm.trans (by rw [hs1', arm64_set_reg_mem'])
  · rw [arm64_steps_two_seq _ _ _ _ hs1 hpc1 hpair]
    simp [hpc]
  · rw [arm64_steps_one_seq _ _ _ hs3 hpc3]
    simp [hpc]
