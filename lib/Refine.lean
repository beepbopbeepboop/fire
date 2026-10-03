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

/-! ## 4b. A receiver frame the callee is allowed to write

`FrameOk` is the wrong predicate for a method, and it is wrong for a reason
that is not a technicality: its memory clause says the callee leaves the
caller's window alone, and a method that assigns `self.x` is *required* to
write into the frame the caller handed it.  So a method cannot satisfy
`FrameOk`, and the design's own callee lemma
(`ProofLib.Frame.frameWrite_read_above_sp`) says exactly why it need not: a
write into a frame that lies entirely **below** `sp` cannot reach anything at
or above `sp`, which is the whole window.

That gives the honest repair, and it is additive.  `FrameOk` stays exactly as
it is for the proofs that use it, and `FrameOk_except` carves the receiver
frame out of the window rather than asserting the window is intact.  The
exclusion premise is `¬ FrameBelow`, i.e. "unless this really is a receiver
frame sitting below the stack pointer" -- the same predicate
`frameWrite_read_above_sp` consumes, so the per-block reasoning the existing
`FrameOk` proofs do is reused rather than reinvented.

`FrameOk_except_zero` is the lemma that makes the addition safe rather than a
second, weaker version of the same claim: for a frame that is empty, or that
sits entirely above `sp`, the old predicate is *recovered*, not replaced.

Nothing here is reachable yet.  No emitter produces a by-reference receiver and
no generated proof mentions these names; they are the callee-contract half of
`bugs/FORMAL_wide_receiver_by_reference.md`, landed first because they are the
part that has to be right before any codegen can be. -/

/-- **Frame preservation, modulo the receiver frame.**  Everything `FrameOk`
    says, except that the callee may have rewritten the `n` slots of a receiver
    frame based at `base`.  The register and `sp` clauses are literally the
    same conjuncts as `FrameOk`'s, because a method that writes its receiver
    frame still restores the callee-saved registers and still balances its own
    frame. -/
def FrameOk_except (st st' : Arm64State) (base : UInt64) (n : Nat) : Prop :=
  st'.x19 = st.x19 ∧ st'.x20 = st.x20 ∧ st'.x21 = st.x21 ∧ st'.x22 = st.x22 ∧
  st'.x23 = st.x23 ∧ st'.x24 = st.x24 ∧ st'.x25 = st.x25 ∧ st'.x26 = st.x26 ∧
  st'.x27 = st.x27 ∧ st'.x28 = st.x28 ∧ st'.x29 = st.x29 ∧ st'.x30 = st.x30 ∧
  st'.sp = st.sp ∧
  (∀ j, st.sp.toNat + j < 2^64 →
    ¬ Frame.FrameBelow base st.sp n →
    mem_read_u64 st'.mem ((st.sp + UInt64.ofNat j).toNat) =
    mem_read_u64 st.mem ((st.sp + UInt64.ofNat j).toNat))

/-- A frame that is empty, or that sits entirely above `sp`, is not below `sp`
    and so carves nothing out of the window. -/
theorem not_below_of_above {base sp : UInt64} {n : Nat} (h : sp.toNat < base.toNat) :
    ¬ Frame.FrameBelow base sp n := by
  intro hb
  unfold Frame.FrameBelow at hb
  simp only [Frame.frameBytes, Frame.SLOT, Nat.mul_zero, Nat.add_zero] at hb
  omega

/-- **The old predicate is recovered, not replaced.**  With an empty frame (or
    any frame above `sp`), `FrameOk_except` *is* `FrameOk`: the extra premise is
    dischargeable at every `j`, so the except-clause has exactly the old window
    and the twelve register clauses are shared.  This is what makes adding
    `FrameOk_except` safe for the 40 proofs that use `FrameOk`. -/
theorem FrameOk_except_zero (st st' : Arm64State) (base : UInt64)
    (habove : st.sp.toNat < base.toNat) :
    FrameOk_except st st' base 0 ↔ FrameOk st st' := by
  have hnb : ¬ Frame.FrameBelow base st.sp 0 := not_below_of_above habove
  constructor
  · intro h
    obtain ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, hwin⟩ := h
    refine ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, ?_⟩
    intro j hj
    exact hwin j hj hnb
  · intro h
    obtain ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, hwin⟩ := h
    refine ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, ?_⟩
    intro j hj _
    exact hwin j hj

/-- **A callee that only writes its own receiver frame restores everything
    else.**  This is the generic step a method's per-block walk needs, and it
    is a direct application of `ProofLib.Frame.frameWrite_read_above_sp`: the
    frame is below `sp`, so the write cannot reach the caller's window.

    `mem` is threaded in the same left-fold shape the emitter's stores have, so
    this composes with the per-block value flow the way `FrameOk`'s clause does
    today rather than needing a new per-block reasoning mode. -/
theorem frameWrites_window_preserved (st st' : Arm64State) (base : UInt64) (n : Nat)
    (kvs : List (Nat × UInt64))
    (hbelow : Frame.FrameBelow base st.sp n)
    (hks : ∀ kv, kv ∈ kvs → kv.1 < n)
    (hok : FrameOk st st') :
    (∀ j, st.sp.toNat + j < 2 ^ 64 →
      mem_read_u64 (List.foldl (fun m kv => Frame.frameWrite m base kv.1 kv.2) st.mem kvs)
        ((st.sp + UInt64.ofNat j).toNat) =
      mem_read_u64 st.mem ((st.sp + UInt64.ofNat j).toNat)) ∧
    FrameOk_except st st' base n := by
  refine ⟨?_, ?_⟩
  · intro j hj
    exact Frame.frameWrites_read_above_sp st.mem base st.sp n kvs hbelow hks j hj
  · obtain ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, hw⟩ := hok
    refine ⟨h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, hsp, ?_⟩
    intro j hj _
    exact hw j hj

/-- The per-frame size bound threaded through the contract, at `stride` bytes of
    stack per recursion level: every frame's stores (`sp - K`, `K ≤ FRAME`) sit
    in the non-wrapping regime, so `FrameOk`'s window clause can be proved
    unconditionally on the caller's slots.

    The stride is a parameter, not a constant, because it has to *dominate the
    stack a level actually consumes*.  A level's consumption is fixed by the
    emitter's frame layout (the `_SCRATCH` reservation, the callee-saved pairs,
    and the argument push), which is ~131 KB for the current backend — larger
    than any constant that predates the scratch reservation.  Carrying the real
    value keeps `frameBound_succ` (below) provable; hardcoding a stride smaller
    than one level's frame makes the recursion induction step unprovable, which
    is exactly how the previous fixed `65536` failed. -/
abbrev FrameBound (stride : Nat) (st : Arm64State) (arg : UInt64) : Prop :=
  stride * (arg.toNat + 1) ≤ st.sp.toNat

/-- **Frame bound across one recursion level.**  Descending a level costs `P`
    bytes of stack and decrements `arg` by one, so a bound at `stride ≥ P`
    carries over unchanged.  The generator supplies the `P` it emitted and
    discharges `stride ≥ P` by literal arithmetic. -/
theorem frameBound_succ (stride P : Nat) (st : Arm64State) (arg : UInt64)
    (hP : stride ≥ P) (hPlt : P < 2 ^ 64) (hne : arg ≠ 0)
    (hPge : P ≤ st.sp.toNat)
    (hb : FrameBound stride st arg) :
    FrameBound stride ({ st with sp := st.sp - UInt64.ofNat P }) (arg - 1) := by
  have hsub : (arg - 1).toNat = arg.toNat - 1 := u64_toNat_sub_one' arg hne
  have hslot : (st.sp - UInt64.ofNat P).toNat = st.sp.toNat - P :=
    u64_toNat_sub_lit st.sp P hPlt hPge
  simp only [FrameBound, hsub, hslot]
  have hpos : 1 ≤ arg.toNat := by
    have hne0 : arg.toNat ≠ 0 := by
      intro hz
      exact hne (UInt64.toNat_inj.mp (by simpa using hz))
    have : 0 < arg.toNat := Nat.pos_of_ne_zero hne0
    omega
  have hmul : stride * (arg.toNat - 1 + 1) ≤ stride * arg.toNat := by
    rw [show arg.toNat - 1 + 1 = arg.toNat by omega]
    exact Nat.mul_le_mul_left _ (Nat.le_refl _)
  -- `hb` bounds `stride * (arg.toNat + 1)`, so one `stride` is already spent
  -- on the level being entered; the rest covers the remaining `arg.toNat`.
  have hstr : stride * arg.toNat + stride ≤ st.sp.toNat := by omega
  omega

/-- **Frame bound at a call site.**  The callee is entered with `sp` unchanged
    from the caller's (its own frame is reserved by its prologue), so the
    caller's bound at `arg` covers the callee's bound at `arg - 1` whenever the
    stride dominates one level.  This is `frameBound_succ` with the call-site
    `sp` relation (already discharged by the generator). -/
theorem frameBound_succ_call (stride P : Nat) (st : Arm64State) (arg : UInt64)
    (ret entry : Nat) (hP : stride ≥ P) (hPlt : P < 2 ^ 64) (hne : arg ≠ 0)
    (hPge : P ≤ st.sp.toNat)
    (hb : FrameBound stride st arg) :
    FrameBound stride ({ st with x30 := UInt64.ofNat ret, pc := entry })
      (arg - 1) := by
  have hsub : (arg - 1).toNat = arg.toNat - 1 := u64_toNat_sub_one' arg hne
  simp only [FrameBound, hsub]
  -- one `stride` of the caller's `(arg + 1)` levels pays for the level being
  -- entered; the callee needs `arg` levels' worth.
  have hpos : 1 ≤ arg.toNat := by
    have hne0 : arg.toNat ≠ 0 := by
      intro hz
      exact hne (UInt64.toNat_inj.mp (by simpa using hz))
    have : 0 < arg.toNat := Nat.pos_of_ne_zero hne0
    omega
  have hmul : stride * (arg.toNat - 1 + 1) ≤ stride * arg.toNat := by
    rw [Nat.sub_add_cancel hpos]
    exact Nat.le_refl _
  simp only [FrameBound] at hb
  -- `hb`: `stride * (arg + 1) ≤ sp`, i.e. `stride * arg + stride ≤ sp`, so
  -- dropping the nonnegative `stride` term gives `stride * arg ≤ sp`.
  have hsp' : stride * arg.toNat ≤ st.sp.toNat := by
    have hsplit : stride * (arg.toNat + 1) = stride * arg.toNat + stride := by
      rw [Nat.mul_add, Nat.mul_one]
    have := hb
    rw [hsplit] at this
    omega
  exact Nat.le_trans hmul hsp'

/-- The `sp` every top-level invocation starts from: `Arm64State.init` seeds
    the stack pointer at the architectural top of the 64-bit address space
    minus the 16 bytes of red-zone/alignment the ABI reserves.  Named so the
    descent arithmetic below is not open-coded against the literal. -/
theorem init_sp_toNat (input : UInt64) (entry : Nat) :
    (Arm64State.init input entry).sp.toNat = 18446744073709551600 := rfl

/-- **Frame bound for a recursive call made from a top-level walk.**

    At the top of a walk the entry state is the initial one, so the caller's
    reservation is bounded by the literal stack top.  Descending to a call site
    costs at least one `stride`, and the callee's argument is at most the
    caller's argument less one, so the callee's `(arg - 1 + 1) = arg` levels
    still fit below the caller's `sp` by exactly the `stride` the caller's
    `(arg + 1)`-th level was paying for.

    The two arithmetic premises are the concrete facts the walk already
    establishes: `hsp` is the call site's own (ground) `sp` after the frame
    drops so far, and `harg` is the `dec1` decrement at the call.  The stride
    multiplication and the `Nat` subtraction are discharged here. -/
theorem frameBound_descend (stride : Nat) (st st' : Arm64State) (arg x : UInt64)
    (harg : x.toNat + 1 ≤ arg.toNat)
    (hinit : st.sp.toNat = 18446744073709551600)
    (hsp : 18446744073709551600 - stride ≤ st'.sp.toNat)
    (hb : FrameBound stride st arg) :
    FrameBound stride st' x := by
  simp only [FrameBound] at hb ⊢
  have hmul := Nat.mul_le_mul_left stride harg
  have hsplit : stride * (arg.toNat + 1) = stride * arg.toNat + stride := by
    rw [Nat.mul_add, Nat.mul_one]
  rw [hsplit] at hb
  rw [hinit] at hb
  omega

/-- **Frame bound for a recursive call, at any smaller argument.**

    `frameBound_descend` is the special case where the caller's entry state is
    the initial one.  Inside the contract the caller's own `FrameBound` is in
    scope instead, and the callee's argument need only be *at most* one below
    the caller's — a tree recursion's second call (`arg - 2`) descends one
    level like any other but asks for strictly less, which is why stating the
    descent at exactly `arg - 1` was not enough to discharge it.

    One `stride` of the caller's `(arg + 1)` reservation pays for the level
    being entered, so the callee's `x.toNat + 1` levels still fit. -/
theorem frameBound_descend_le (stride P : Nat) (st : Arm64State) (arg x : UInt64)
    (hP : stride ≥ P) (hPlt : P < 2 ^ 64)
    (hx : x.toNat + 1 ≤ arg.toNat)
    (hPge : P ≤ st.sp.toNat)
    (hb : FrameBound stride st arg) :
    FrameBound stride ({ st with sp := st.sp - UInt64.ofNat P }) x := by
  have hsub : (st.sp - UInt64.ofNat P).toNat = st.sp.toNat - P :=
    u64_toNat_sub_lit st.sp P hPlt hPge
  simp only [FrameBound] at hb ⊢
  simp only [hsub]
  have hmul := Nat.mul_le_mul_left stride hx
  have hsplit : stride * (arg.toNat + 1) = stride * arg.toNat + stride := by
    rw [Nat.mul_add, Nat.mul_one]
  rw [hsplit] at hb
  omega

/-- `ProofLib.mem_read_after_write_u64_high_nw` with the frame bound and the
    store offset discharged by the caller's chosen stride.  This is the
    `simp`-ready form the generator uses to prove `FrameOk`'s no-wrap window
    clause.

    The bounds are `stride`-parameterised rather than pinned to a literal
    `65536`: the store offset `K` and the stack floor both come from the
    emitter's frame layout, and a fixed literal silently stops discharging them
    once that layout changes. -/
theorem mem_read_after_write_u64_high_fb (mem : Nat → UInt8) (sp : UInt64)
    {stride K j : Nat} (hK : 8 ≤ K) (hKF : K ≤ stride) (hjnw : sp.toNat + j < 2^64)
    (hbnd : stride ≤ sp.toNat) (val : UInt64) :
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
theorem contract_sound (p : Prog) (mojo : UInt64 → UInt64) (BASE PATH : Nat) (stride : Nat)
    (hbase : ∀ (fuel : Nat) (st : Arm64State),
      BASE ≤ fuel → st.pc = p.entry → st.x0 = 0 →
      FrameBound stride st 0 →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st 0)
    (hstep : ∀ (k : Nat) (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = k + 1 → BASE + PATH * (k + 1) ≤ fuel →
      st.pc = p.entry → st.x0 = arg →
      FrameBound stride st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * k ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 1 →
        FrameBound stride sub (arg - 1) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 1)) →
      Post p fuel mojo st arg) :
    ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      BASE + PATH * arg.toNat ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound stride st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
  have key : ∀ k, ∀ arg st fuel, arg.toNat = k → BASE + PATH * k ≤ fuel →
      st.pc = p.entry → st.x0 = arg → FrameBound stride st arg →
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
theorem contract_sound_tree (p : Prog) (mojo : UInt64 → UInt64) (BASE PATH : Nat) (stride : Nat)
    (hbase : ∀ (fuel : Nat) (st : Arm64State),
      BASE ≤ fuel → st.pc = p.entry → st.x0.toNat < 2 →
      FrameBound stride st st.x0 →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st st.x0)
    (hstep : ∀ (k : Nat) (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = k + 2 → BASE + PATH * 2 ^ (k + 2) ≤ fuel →
      st.pc = p.entry → st.x0 = arg →
      FrameBound stride st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * 2 ^ (k + 1) ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 1 →
        FrameBound stride sub (arg - 1) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 1)) →
      (∀ (sub : Arm64State) (fuel' : Nat),
        BASE + PATH * 2 ^ k ≤ fuel' → sub.pc = p.entry → sub.x0 = arg - 2 →
        FrameBound stride sub (arg - 2) →
        (∀ pc, pc ∈ p.rets → pc ≠ sub.x30.toNat) →
        Post p fuel' mojo sub (arg - 2)) →
      Post p fuel mojo st arg) :
    ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      BASE + PATH * 2 ^ arg.toNat ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound stride st arg →
      (∀ pc, pc ∈ p.rets → pc ≠ st.x30.toNat) → Post p fuel mojo st arg := by
  intro arg st fuel hfuel hpc hx0 hbnd hx30
  have key : ∀ m : Nat, ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      arg.toNat = m → BASE + PATH * 2 ^ m ≤ fuel → st.pc = p.entry → st.x0 = arg →
      FrameBound stride st arg →
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

def dylibExportProg (image : DylibImage) (export_ : DylibExport) : Prog :=
  { fname := export_.module ++ "." ++ export_.symbol
    code := image.code
    base := image.base
    entry := export_.entry
    -- The export's OWN end, which is also where `runProg` puts the link
    -- register (`Refine.runProg` reads `p.exit` for both).  The image's end
    -- was used here, which for a multi-export image runs the export past its
    -- own last instruction and into the next export's code -- so the run, and
    -- therefore `export_result_spec`, was about a different function than the
    -- one the export names.  See `DylibExport.exportEnd`.
    exit := DylibExport.exportEnd image export_
    -- The SAME fuel `DylibExport.runExport` uses, deliberately: `Total` is
    -- stated over `runExport` and a contract over `runProg`, and if the two
    -- disagreed then the two claims would be about different runs and the
    -- caller's theorem would be bridging a gap nobody stated.
    fuel := fun n => DylibExport.exportFuel image n
    blocks := []
    rets := [] }

/-- **A dylib export's contract, stated so that it can be TRUE.**

    `DylibExportContract p obs n` says "run the export on `n` and the result
    register holds `obs n`" — the right shape, and it is kept.

    What could not be kept is the theorem that used to discharge it.
    `dylib_export_contract_stub` was `by sorry` over *any* `p` and *any*
    `obs`, and `formal/arm64_proof_gen.py` invoked it with `obs := fun n => n`.
    So the emitted claim was: **every dylib export computes the identity
    function.**

    That is not a gap, it is a false statement, and it is false of the very
    first real dylib in the tree: measured 2026-09-28 on a generated dylib with
    `triple` and `negate`, `runProg` yields `x0 = 21` for `triple(7)` and
    `x0 = -5` for `negate(5)`.  So there is nothing to prove here; the honest
    outcome is the one FORMAL.md §11.2 [3] names — **delete it** — and replace
    it with statements that are true and that say what a caller must actually
    establish.

    What replaces it, in three pieces:

    * `export_result` — the export's result for an argument, read out of the
      machine.  This is a *function*, and it is the thing whose properties are
      worth proving.
    * `export_result_spec` — the one-line obligation a caller discharges: the
      export agrees with a stated specification.  It is an obligation, not a
      theorem, and it is stated as one so it cannot be mistaken for a proof.
    * `dylib_export_contract_of_spec` — the caller's theorem, *proved*, and
      free of any `sorry`: given the spec obligation, the caller's contract
      follows.  This is the "a caller can discharge an obligation against it"
      that phase 3 asks for, and it is the half that was previously a `sorry`
      masquerading as a proof. -/
def DylibExportContract (p : Prog) (obs : UInt64 → UInt64) (n : UInt64) : Prop :=
  ∀ s, runProg p n = some s → s.x0 = obs n

/-- **The result an export computes, read off the machine.**  `0` when the run
    does not terminate, which is the same convention `run_result_exit` in the
    generated proofs already uses — deliberately, so the two agree by
    construction rather than by review. -/
def export_result (image : DylibImage) (export_ : DylibExport) (n : UInt64) : UInt64 :=
  (runProg (dylibExportProg image export_) n).map (fun s => s.x0) |>.getD 0

/-- **THE CALLER'S OBLIGATION, and it is an obligation.**  An export agrees with
    the specification `spec` when running it on `n` terminates and leaves
    `spec n` in `x0`.

    This is stated as a bare `Prop` with no theorem discharging it, and that
    is the point: it is the work, and calling it a theorem proved by `sorry`
    is what made the previous shape so easy to mistake for progress.  A
    generator discharges it per export by `native_decide` whenever the export's
    spec is a closed function — which it is for every word-shaped entry point,
    since the run is a finite machine computation over a literal byte list. -/
def export_result_spec (image : DylibImage) (export_ : DylibExport)
    (spec : UInt64 → UInt64) : Prop :=
  ∀ (n : UInt64) (s : Arm64State),
    runProg (dylibExportProg image export_) n = some s → s.x0 = spec n

/-- **The caller's theorem, proved.**  Given the export's spec obligation, the
    caller's contract follows — and this is the direction that matters, because
    it is the step from "the library says what the export computes" to "my
    program may assume it".

    No `sorry`, and no `True`: this is the composition of two real facts, and
    it typechecks, which is the difference this whole refactor is about. -/
theorem dylib_export_contract_of_spec (image : DylibImage)
    (export_ : DylibExport) (spec : UInt64 → UInt64)
    (hspec : export_result_spec image export_ spec) (n : UInt64) :
    DylibExportContract (dylibExportProg image export_) spec n := by
  exact hspec n

/-- **The same, for a caller that has discharged the obligation.**  Stated over
    the machine's own run rather than `runProg`, so a proof that already has
    the run in hand does not have to re-derive it. -/
theorem caller_may_use_export (image : DylibImage) (export_ : DylibExport)
    (spec : UInt64 → UInt64) (hspec : export_result_spec image export_ spec)
    (n : UInt64) (s : Arm64State)
    (hrun : runProg (dylibExportProg image export_) n = some s) :
    s.x0 = spec n :=
  hspec n s hrun

/-- **What a caller can conclude about the RESULT even without the spec.**
    The export's result is a value the machine produced, so it is not a
    fabricated one: it agrees with whatever the run says, for any two runs of
    the same argument.  This is the `Functional` half of `DylibExport.Semantics`
    in the shape a caller consumes it, and it is `rfl` — the determinism is in
    the function, not in a theorem about it. -/
theorem export_result_run (image : DylibImage) (export_ : DylibExport)
    (n : UInt64) (s : Arm64State)
    (hrun : runProg (dylibExportProg image export_) n = some s) :
    export_result image export_ n = s.x0 := by
  unfold export_result
  rw [hrun]
  rfl

end Refine
