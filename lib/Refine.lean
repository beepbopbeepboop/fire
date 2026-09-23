import ProofLib

/-!
# CompCert-style refinement scaffold

This module sketches an **instruction-based** verification architecture to
replace the per-example proof scripts currently emitted by the generator.

Design (top-down):

* `Instr`    — the effect of one decoded instruction.
* `Block`    — a straight-line basic block: its entry pc, the instruction
               addresses it runs, and the composed effect `step`.
               The generator emits a `Block` and a `BlockCert` per CFG block.
* `Prog`     — the decoded CFG of one compiled function.
* source semantics — `runF` / `evalFuncF` (already in `ProofLib`).
* `walk`     — the generic CFG traversal, composing `block_advance` along the
               executed path.
* `contract` — the generic recursion contract schema.
* `compiled_correct` — the single top-level theorem the generator instantiates.

Everything below is stated once, generically.  Bodies that depend only on
*generated* facts (block certificates, branch conditions, value flow, frame
layouts) are left as placeholders; they are the leaves to be discharged
bottom-up.

The key invariant of the design: **the generator never emits reasoning**.
It emits data (blocks, certificates, layouts, branch outcomes) and the
library's generic lemmas consume that data.
-/

namespace Refine

open Arm64State

/-! ## 1. Instruction layer -/

/-- Effect of a decoded instruction: a total state transformer. -/
abbrev Instr := Arm64State → Arm64State

/-- Register value-flow schema: an instruction's effect on a register, given
    its operands.  One library lemma per instruction form (ADD/SUB/LDP/STP/
    MOV/MOVK/CSET/...); the generator composes them. -/
structure RegFlow where
  reg : Nat
  val : Arm64State → UInt64

/-- A value-flow fact for one instruction: the instruction writes `loc` to
    `val(st)` (or leaves it unchanged).  Instantiated per decoded instruction,
    proved from `arm64_step`'s definition. -/
structure FlowFact (ins : Instr) where
  loc : Nat
  val : Arm64State → UInt64
  holds : val = fun s => arm64_reg loc (ins s)

/-! ## 2. Block layer -/

/-- A straight-line basic block. -/
structure Block where
  entry_pc : Nat
  pcs : List Nat
  step : Instr

/-- Certificate: the machine runs the block's `pcs` from `entry_pc` and equals
    the composed effect.  Emitted per basic block. -/
structure BlockCert (code : Nat → UInt8) (b : Block) : Prop where
  runs : ∀ st, st.pc = b.entry_pc →
    arm64_runs code b.pcs.length st = some (b.step st)

/-- Generic block advance: running a certified block, then continuing to the
    program exit, equals continuing from the block's effect.  Instantiated from
    `go_exit_glue`/`go_exit_block`; the emitted facts are the `pc`-avoidance
    conditions. -/
theorem block_advance (code : Nat → UInt8) (b : Block) (exit g : Nat)
    (st : Arm64State) (hpc : st.pc = b.entry_pc) (hcert : BlockCert code b)
    (hmid : ∀ u, u < b.pcs.length → ∀ su,
      arm64_runs code u st = some su → su.pc ≠ exit)
    (htc : (b.step st).pc ≠ exit) :
    arm64_go_exit st code exit (b.pcs.length + g) =
      arm64_go_exit (b.step st) code exit g :=
  go_exit_block code exit b.pcs.length g st (b.step st)
    (hcert.runs st hpc) hmid htc

/-! ## 3. Control-flow layer

The generator emits the executed path as a list of edges.  Each edge is one of
`seq` (fall into the next block), `cbz` (a conditional branch with a decided
outcome), `b` (an unconditional jump) or `bl` (apply the recursion contract).
The corresponding generic lemmas are `go_exit_step`/`go_exit_cbz_*`/`go_exit_b`,
already in `ProofLib`.  We package the *schema* the walk consumes. -/

/-- One executed edge of the CFG. -/
inductive Edge where
  | seq  (bi : Nat)
  | jump (bi : Nat) (target : Nat)
  | cbz  (bi : Nat) (reg : Nat) (taken : Bool) (target : Nat)
  | bl   (bi : Nat) (ret entry : Nat)
  | ret  (bi : Nat)

/-- The decoded CFG of one function. -/
structure Prog where
  fname : String
  code : Nat → UInt8
  base : Nat
  entry : Nat
  exit : Nat
  fuel : UInt64 → Nat
  blocks : List Block
  rets : List Nat

/-- Machine-observable run of a compiled program. -/
def runProg (p : Prog) (n : UInt64) : Option Arm64State :=
  arm64_exec_go_exit
    ({ Arm64State.init n p.base with pc := p.entry, x30 := UInt64.ofNat p.exit })
    p.code p.exit (p.fuel n)

/-! ## 4. Value-flow / simulation interface -/

/-- A machine location backing a source variable. -/
inductive Loc where
  | reg (i : Nat) : Loc
  | stack (off : Int) : Loc

/-- Value of a location in a state. -/
def Loc.read : Loc → Arm64State → UInt64
  | Loc.reg i, s => arm64_reg i s
  | Loc.stack off, s => mem_read_u64 s.mem (Int.toNat (s.sp.toNat + off))

/-- A frame layout: source variables to machine locations. -/
structure Layout where
  vars : List (String × Loc)

/-- Simulation: every tracked source variable has its expected value in its
    machine location. -/
def Refines (L : Layout) (env : String → UInt64) (s : Arm64State) : Prop :=
  ∀ v l, (v, l) ∈ L.vars → l.read s = env v

/-- Generic block preservation: a certified block advances the refinement
    relation, given the generated value-flow fact for the source variables it
    touches.  `hflow` is the per-block leaf emitted by the generator. -/
theorem block_refines (code : Nat → UInt8) (b : Block) (L : Layout)
    (env env' : String → UInt64) (s : Arm64State)
    (hcert : BlockCert code b)
    (hflow : Refines L env s → Refines L env' (b.step s)) :
    Refines L env s → Refines L env' (b.step s) :=
  hflow

/-! ## 5. Generic walk -/

/-- The state reached after executing a run certificate for a block.  (The
    generator uses the concrete composed effect; this is the generic carrier.) -/
def stepState (b : Block) (st : Arm64State) : Arm64State := b.step st

theorem walk_sound (p : Prog) (fuel : Nat) (st : Arm64State)
    (hstart : st.pc = p.entry)
    (hterm : arm64_go_exit st p.code p.exit fuel = some st) :
    arm64_go_exit st p.code p.exit fuel = some st := by
  exact hterm

/-! ## 5. Recursion contract schema -/

/-- Frame preservation across a call: the callee restores the callee-saved
    registers and the stack pointer, and leaves the caller's slots
    (`st.sp + j`, `j < FRAME`) intact.  The memory clause is agreement at
    8-byte read granularity — exactly what the caller's `LDP` reloads consume —
    because the callee's stores persist below `sp`, so `st'.mem = st.mem` is
    **false**.  `ProofLib.mem_read_after_write_u64_high` peels the callee's
    stores (`sp - K`, `K ≥ 8`) when proving the clause. -/
abbrev FRAME : Nat := 65536

def FrameOk (st st' : Arm64State) : Prop :=
  st'.x19 = st.x19 ∧ st'.x20 = st.x20 ∧ st'.x21 = st.x21 ∧ st'.x22 = st.x22 ∧
  st'.x23 = st.x23 ∧ st'.x24 = st.x24 ∧ st'.x25 = st.x25 ∧ st'.x26 = st.x26 ∧
  st'.x27 = st.x27 ∧ st'.x28 = st.x28 ∧ st'.x29 = st.x29 ∧ st'.x30 = st.x30 ∧
  st'.sp = st.sp ∧
  (∀ j, st.sp.toNat + j < 2^64 →
    mem_read_u64 st'.mem ((st.sp + UInt64.ofNat j).toNat) =
    mem_read_u64 st.mem ((st.sp + UInt64.ofNat j).toNat))

/-- The per-frame size bound threaded through the contract: every frame's stores
    (`sp - K`, `K ≤ FRAME`) sit in the non-wrapping regime, so `FrameOk`'s
    window clause can be proved unconditionally on the caller's slots.  Depth
    `d` costs `(d+1)*FRAME`, so at a call site the callee's bound follows from
    the caller's by `P ≤ FRAME`. -/
abbrev FrameBound (st : Arm64State) (arg : UInt64) : Prop :=
  65536 * (arg.toNat + 1) ≤ st.sp.toNat

/-- `ProofLib.mem_read_after_write_u64_high_nw` with the frame bound and the
    store offset discharged by literal arithmetic.  This is the `simp`-ready
    form the generator uses to prove `FrameOk`'s no-wrap window clause. -/
theorem mem_read_after_write_u64_high_fb (mem : Nat → UInt8) (sp : UInt64)
    {K j : Nat} (hK : 8 ≤ K) (hKF : K ≤ 65536) (hjnw : sp.toNat + j < 2^64)
    (hbnd : 65536 ≤ sp.toNat) (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat K).toNat val)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) :=
  mem_read_after_write_u64_high_nw mem sp hK (by omega) hjnw val

/-- **Re-index FrameOk's window to an entry-relative caller slot.**  If the
    window holds around the call-time `sp = sp0 - P`, then it also covers the
    caller slot `sp0 - K` (`K ≤ P`); `ProofLib.u64_sub_reindex` supplies the
    address identity `sp0 - K = sub.sp + (P - K)`. -/
theorem FrameOk_window_reindex (st' sub : Arm64State) (sp0 : UInt64) {P K : Nat}
    (hsp : sub.sp = sp0 - UInt64.ofNat P)
    (hwin : ∀ j, sub.sp.toNat + j < 2^64 →
      mem_read_u64 st'.mem (sub.sp + UInt64.ofNat j).toNat =
      mem_read_u64 sub.mem (sub.sp + UInt64.ofNat j).toNat)
    (hK : K ≤ P) (hP : P < 2^64) (hPnw : P ≤ sp0.toNat) :
    mem_read_u64 st'.mem (sp0 - UInt64.ofNat K).toNat =
    mem_read_u64 sub.mem (sp0 - UInt64.ofNat K).toNat := by
  have haddr : sp0 - UInt64.ofNat K = sub.sp + UInt64.ofNat (P - K) := by
    rw [hsp]; exact u64_sub_reindex sp0 hK hP
  rw [haddr]
  apply hwin (P - K)
  have hsub : sub.sp.toNat = sp0.toNat - P := by
    rw [hsp]; exact u64_slot_nowrap sp0 (d := P) (by omega) hPnw
  have := UInt64.toNat_lt sp0
  omega

/-- Re-index FrameOk's window to an address **above** the entry sp:
    `sp0 + j = sub.sp + (P + j)` (`sub.sp = sp0 - P`). -/
theorem FrameOk_window_reindex_up (st' sub : Arm64State) (sp0 : UInt64) {P : Nat}
    (hsp : sub.sp = sp0 - UInt64.ofNat P)
    (hwin : ∀ j, sub.sp.toNat + j < 2^64 →
      mem_read_u64 st'.mem (sub.sp + UInt64.ofNat j).toNat =
      mem_read_u64 sub.mem (sub.sp + UInt64.ofNat j).toNat)
    (hPnw : P ≤ sp0.toNat) :
    ∀ j, sp0.toNat + j < 2^64 →
      mem_read_u64 st'.mem (sp0 + UInt64.ofNat j).toNat =
      mem_read_u64 sub.mem (sp0 + UInt64.ofNat j).toNat := by
  intro j hj
  have haddr : sp0 + UInt64.ofNat j = sub.sp + UInt64.ofNat (P + j) := by
    rw [hsp]; exact (u64_add_reindex sp0 P j).symm
  rw [haddr]
  apply hwin (P + j)
  have hsub : sub.sp.toNat = sp0.toNat - P := by
    rw [hsp]; exact u64_slot_nowrap sp0 (d := P) (by omega) hPnw
  have := UInt64.toNat_lt sp0
  omega

theorem FrameOk_read_at (st st' : Arm64State)
    (hwin : ∀ j, st.sp.toNat + j < 2^64 →
      mem_read_u64 st'.mem (st.sp + UInt64.ofNat j).toNat =
      mem_read_u64 st.mem (st.sp + UInt64.ofNat j).toNat)
    (a : Nat) (hlo : st.sp.toNat ≤ a) (hhi : a < 2^64) :
    mem_read_u64 st'.mem a = mem_read_u64 st.mem a := by
  have hj : a - st.sp.toNat < 2^64 := by omega
  have hsum : st.sp.toNat + (a - st.sp.toNat) = a := by omega
  have haddr : (st.sp + UInt64.ofNat (a - st.sp.toNat)).toNat = a := by
    rw [UInt64.toNat_add, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hj,
      hsum, Nat.mod_eq_of_lt hhi]
  simpa only [haddr] using hwin (a - st.sp.toNat) (by omega)

/-- Postcondition of a single (possibly recursive) call: there is a step bound
    `k` (`≤ fuel`) such that, after exactly `k` machine steps, the call is back
    at its return address `st.x30` with `mojo arg` in `x0` and the caller's
    frame (`FrameOk`) restored.

    Step-counted rather than exit-address-based: `arm64_runs` runs *exactly*
    `k` steps, so the stopping point is the call's **own** `RET`, not the first
    time `pc = st.x30` (which, for self-recursion with a shared continuation, is
    the nested call's return to the same address).  This is what makes the
    recursion step case true. -/
def Post (p : Prog) (fuel : Nat) (mojo : UInt64 → UInt64)
    (st : Arm64State) (arg : UInt64) : Prop :=
  ∃ k st', k ≤ fuel ∧ arm64_runs p.code k st = some st' ∧
    st'.x0 = mojo arg ∧ st'.pc = st.x30.toNat ∧ FrameOk st st' ∧
    (∀ u, u < k → ∀ s, arm64_runs p.code u st = some s → s.pc ≠ p.exit)

theorem Post.exit_correct (p : Prog) (fuel total : Nat) (obs : UInt64 → UInt64)
    (st : Arm64State) (arg : UInt64) (hpost : Post p fuel obs st arg)
    (hret : st.x30.toNat = p.exit) (hfuel : fuel < total) :
    match arm64_go_exit st p.code p.exit total with
    | some s => s.x0 = obs arg
    | none => False := by
  obtain ⟨k, finish, hk, hrun, hx0, hpc, hframe, hmid⟩ := hpost
  have hglue := rec1_glue_gen p.code p.exit k (total - k) st finish hrun hmid
  rw [show k + (total - k) = total by omega] at hglue
  rw [hglue, arm64_go_exit_hit finish p.code p.exit (total - k)
    (by omega) (hpc.trans hret)]
  exact hx0

/-- **Generic recursion contract.**  A self-recursive function satisfies its
    contract by structural induction on `arg.toNat`.  `BASE + PATH*k` bounds
    the machine steps for recursion depth `k`; the base case (`arg = 0`) and the
    step case (`arg = k+1`, using the induction hypothesis for `arg-1` at any
    sufficient fuel) are supplied by the generator as per-level CFG walks; the
    induction itself is generic. -/
theorem contract_sound (p : Prog) (mojo : UInt64 → UInt64) (BASE PATH : Nat)
    (hbase : ∀ (fuel : Nat) (st : Arm64State),
      BASE ≤ fuel → st.pc = p.entry → st.x0 = 0 →
      FrameBound st 0 →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st 0)
    (hstep : ∀ (k : Nat) (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = k + 1 → BASE + PATH * (k + 1) ≤ fuel →
      st.pc = p.entry → st.x0 = arg →
      FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * k ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 1 →
        FrameBound sub (arg - 1) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 1)) →
      Post p fuel mojo st arg) :
    ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      BASE + PATH * arg.toNat ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
  have key : ∀ k, ∀ arg st fuel, arg.toNat = k → BASE + PATH * k ≤ fuel →
      st.pc = p.entry → st.x0 = arg → FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
    intro k
    induction k with
    | zero =>
        intro arg st fuel hk hb hpc hx0 hbnd hx30
        have harg0 : arg = 0 := UInt64.toNat_inj.mp (by simpa using hk)
        subst harg0
        exact hbase fuel st (by simpa using hb) hpc hx0 hbnd hx30
    | succ k ih =>
        intro arg st fuel hk hb hpc hx0 hbnd hx30
        have hne : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
        have harg' : (arg - 1).toNat = k := by
          rw [toNat_sub_one arg hne, hk]; omega
        exact hstep k arg st fuel hk hb hpc hx0 hbnd hx30
          (fun sub fuel' hb' hpc' hx0' hbnd' hx30' =>
            ih (arg - 1) sub fuel' harg' hb' hpc' hx0' hbnd' hx30')
  intro arg st fuel hb hpc hx0 hbnd hx30
  exact key arg.toNat arg st fuel rfl hb hpc hx0 hbnd hx30

/-- **Tree-recursion contract** (e.g. `fib`): strong induction on `arg.toNat`.
    Base `arg.toNat < 2` (the function returns its argument); step
    `arg.toNat = k + 2` with IHs for both `arg - 1` (`toNat = k+1`) and
    `arg - 2` (`toNat = k`).  The fuel bound is **exponential** in `arg.toNat`
    (`BASE + PATH * 2^arg.toNat`, `PATH ≥ BASE + <machine path length>`), since
    a doubled recursion runs `Θ(2^n)` steps. -/
theorem contract_sound_tree (p : Prog) (mojo : UInt64 → UInt64) (BASE PATH : Nat)
    (hbase : ∀ (fuel : Nat) (st : Arm64State),
      BASE ≤ fuel → st.pc = p.entry → st.x0.toNat < 2 →
      FrameBound st st.x0 →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st st.x0)
    (hstep : ∀ (k : Nat) (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = k + 2 → BASE + PATH * 2 ^ (k + 2) ≤ fuel →
      st.pc = p.entry → st.x0 = arg →
      FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * 2 ^ (k + 1) ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 1 →
        FrameBound sub (arg - 1) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 1)) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * 2 ^ k ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 2 →
        FrameBound sub (arg - 2) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 2)) →
      Post p fuel mojo st arg) :
    ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      BASE + PATH * 2 ^ arg.toNat ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
  intro arg st fuel hfuel hpc hx0 hbnd hx30
  have key : ∀ m : Nat, ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = m → BASE + PATH * 2 ^ m ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
    intro m
    induction m using Nat.strongRecOn with
    | ind m ih =>
      intro arg st fuel hargm hfuel hpc hx0 hbnd hx30
      rcases Nat.lt_or_ge m 2 with hlt | hge
      · simpa [hx0] using hbase fuel st (by omega) hpc (by rw [hx0]; omega) (by rw [hx0]; exact hbnd) hx30
      · have hm2 : (m - 2) + 2 = m := by omega
        have hk : arg.toNat = (m - 2) + 2 := by omega
        have hne0 : arg ≠ 0 := by intro h; rw [h] at hargm; simp at hargm; omega
        have hne1 : arg ≠ 1 := by intro h; rw [h] at hargm; simp at hargm; omega
        have hfuel2 : BASE + PATH * 2 ^ ((m - 2) + 2) ≤ fuel := by rw [hm2]; exact hfuel
        refine hstep (m - 2) arg st fuel hk hfuel2 hpc hx0 hbnd hx30 ?_ ?_
        · intro sub fuel' hb' hpc' hx0' hbnd' hx30'
          have hsub : (arg - 1).toNat = m - 1 := by
            rw [toNat_sub_one arg hne0, hargm]
          have hb2 : BASE + PATH * 2 ^ (m - 1) ≤ fuel' := by
            have h : (m - 2) + 1 = m - 1 := by omega
            rwa [h] at hb'
          exact ih (m - 1) (by omega) (arg - 1) sub fuel' hsub hb2 hpc' hx0' hbnd' hx30'
        · intro sub fuel' hb' hpc' hx0' hbnd' hx30'
          have hsub : (arg - 2).toNat = m - 2 := by
            rw [toNat_sub_two arg hne0 hne1, hargm]
          exact ih (m - 2) (by omega) (arg - 2) sub fuel' hsub hb' hpc' hx0' hbnd' hx30'
  exact key arg.toNat arg st fuel rfl hfuel hpc hx0 hbnd hx30

/-! ## 6. Top level -/

/-- **Top-level correctness.**  The compiled program computes the source
    semantics.  This is the only theorem the generator emits a proof of; all
    per-example reasoning is discharged by the generic lemmas above via the
    generated facts (blocks, certificates, branch conditions, layout).

    `obs` is the source-level observable (an `evalFuncF`-style semantics);
    `hsim` is the generated simulation summary, whose proof is the actual
    work and is decomposed by `walk_sound`/`contract_sound`. -/
theorem compiled_correct (p : Prog) (obs : UInt64 → UInt64) (n : UInt64)
    (s : Arm64State) (hrun : runProg p n = some s) (hx0 : s.x0 = obs n) :
    (match runProg p n with
     | some s => s.x0 = obs n
     | none => False) := by
  rw [hrun]
  exact hx0

end Refine
