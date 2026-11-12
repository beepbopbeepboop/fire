import ProofLib
import Refine

set_option maxRecDepth 100000

/-!
# Per-export contracts

Phase 4. `Refine.export_result_spec` is an obligation and
`Refine.dylib_export_contract_of_spec` is proved, so a caller's theorem *can*
consume a contract instead of asserting one — but until now no real export
carried a real spec, and the generator filled the gap with `fun n => n`, which
is the exact claim the deleted `dylib_export_contract_stub` made and which is
false (`triple(7) = 21`, not `7`).

This module is the missing half: a contract is *derived from the machine*, so a
wrong spec cannot typecheck.

## The shape of the argument

An export's body is a straight-line run of instructions from its entry to the
image's exit. Two facts pin it down:

1. `arm64_runs code m st = some tc` — the body composes to a single state
   transformer. That is `Refine.BlockCert`, already in the library, and the
   generator already emits the per-instruction step lemmas it consumes.
2. `go_exit_of_runs` below — a run of `m` steps that ARRIVES at the exit is
   `arm64_go_exit … (m+1) = some tc`.

From those, `runExport` is a closed computation and the export's result
register is a **closed `UInt64` expression in the argument**. The contract is
then a *stated* function, and the content of the proof is `bv_decide`: the
machine's own expression against the spec.

That last step is what makes this worth having. Because the spec is checked
against the machine rather than assumed, **`fun n => n` does not typecheck for
an export that is not the identity** — the trap in FORMAL.md §11.2 [3] is
defused by construction rather than by vigilance.

## Why this needs no step bound

`Total` (uniform termination over a *symbolic* argument) cannot be discharged
by evaluation, because `arm64_go_exit` recurses on fuel and a symbolic argument
means a symbolic number of steps. That is agent [2]'s item and a genuinely
different problem.

A contract is not that problem. Here the step count is the export's body
length — a **literal** — so the fuel side condition is the concrete arithmetic
`body length + 1 ≤ exportFuel`, which `omega` closes, and the argument stays
symbolic. A contract is therefore provable today, for a real export, with no
help from the step bound.
-/

open Arm64State

namespace Contracts

/-- **One step of `arm64_go_exit`.**

    The library has `go_exit_step`, and it is the wrong shape for this work:
    it demands `arm64_step st code = some st'` with `st'` the state the runner
    *recurses on*, but on a sequential instruction the runner recurses on
    `{st' with pc := st.pc + 4}` while the step produced `st'`.  The two are
    different states, so the hypothesis cannot be supplied.

    This mirrors the definition instead, and so covers the sequential and
    branching cases in one lemma with no side condition beyond "we were not
    already at the exit".  That is the step `go_exit_within` needs, and it is
    the step that lets a body's instruction sequence and the runner's own
    recursion be related at all. -/
theorem go_exit_cons (st st' : Arm64State) (code : Nat → UInt8)
    (exit f : Nat) (hstep : arm64_step st code = some st') (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (Nat.succ f)
      = arm64_go_exit (if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st')
          code exit f := by
  have hne : Nat.succ f ≠ 0 := by omega
  show arm64_go_exit st code exit (Nat.succ f) = _
  rw [arm64_go_exit, if_neg hne, if_neg hpc, hstep]
  rfl

/-- **A run that arrives at the exit arrives at it within any budget that
    covers its own length.**

    `runExport` runs at the fixed `exportFuel`, while a body's proof is about
    the body's own instruction count — a literal, typically a few dozen.  This
    is the lemma that relates the two, and it is not in the library:
    `go_exit_block` hands back *another* `go_exit`, and nothing says that
    enlarging the fuel of a run that has already stopped does not change its
    answer.

    The `∃ m, …` form is what makes the induction go through: the statement is
    about *some* length at most the budget, so the step case peels one
    instruction off `m` and re-applies the induction to the successor.  That is
    the only place the two different fuel figures ever meet.

    `hmid` is the no-early-exit side condition, and it is **not** decoration —
    the first version of this lemma omitted it and is FALSE, which the
    typechecker caught.  The counterexample is the shape the omission allows:
    `arm64_go_exit` stops the moment `pc = ρ`, while `arm64_runs` does not stop
    at all, so a run whose *start* is already at `ρ` and whose body is nonempty
    satisfies "some `m` gets to `ρ`" and yet `go_exit` returns the start rather
    than the end.  `hmid` says the start is not already at the exit. -/
theorem go_exit_within (code : Nat → UInt8) (ρ : Nat) :
    ∀ (d : Nat) (st tc : Arm64State),
      (∃ m : Nat, m < d ∧ arm64_runs code m st = some tc ∧ tc.pc = ρ ∧
        (∀ u, u < m → ∀ su, arm64_runs code u st = some su → su.pc ≠ ρ)) →
      arm64_go_exit st code ρ d = some tc := by
  intro d
  induction d with
  | zero =>
      intro st tc h
      obtain ⟨m, hm, _, _, _⟩ := h
      omega
  | succ e ih =>
      intro st tc h
      obtain ⟨m, hmd, hrun, htc, hmid⟩ := h
      by_cases hst : st.pc = ρ
      · -- already at the exit: the body must be empty, so `tc = st`
        have hm0 : m = 0 := by
          cases m with
          | zero => rfl
          | succ k =>
              exfalso
              exact (hmid 0 (by omega) st (runs_zero code st)) hst
        subst hm0
        have hstc : st = tc := by
          rw [runs_zero] at hrun
          exact Option.some.inj hrun
        subst hstc
        have hne : Nat.succ e ≠ 0 := by omega
        unfold arm64_go_exit
        rw [if_neg hne, if_pos hst]
      · -- `st.pc ≠ ρ`, so the body is nonempty: `m = 0` would make `tc = st`
        -- and the exit fact would say `st.pc = ρ`.
        have hmpos : 0 < m := by
          cases m with
          | zero =>
              have hstc : st = tc := by
                rw [runs_zero] at hrun
                exact Option.some.inj hrun
              exact absurd (hstc ▸ htc) hst
          | succ k => omega
        cases m with
        | zero => omega
        | succ k =>
            have hk : k < e := by omega
            cases hstep : arm64_step st code with
            | none =>
                have hn : arm64_runs code (Nat.succ k) st = none :=
                  runs_step_none st code k hstep
                rw [hn] at hrun
                exact absurd hrun (by simp)
            | some st1 =>
                by_cases hseq : st1.pc = st.pc
                · have hrun' : arm64_runs code k { st1 with pc := st.pc + 4 } = some tc :=
                    (runs_cons_seq st st1 code k hstep hseq).symm.trans hrun
                  have hmid' : ∀ u, u < k → ∀ su,
                      arm64_runs code u { st1 with pc := st.pc + 4 } = some su →
                        su.pc ≠ ρ := by
                    intro u hu su hus
                    refine hmid (Nat.succ u) (by omega) su ?_
                    have h2 := hus
                    rwa [← runs_cons_seq st st1 code u hstep hseq] at h2
                  rw [go_exit_cons st st1 code ρ e hstep hst]
                  simp only [hseq, if_true]
                  exact ih _ _ ⟨k, hk, hrun', htc, hmid'⟩
                · have hrun' : arm64_runs code k st1 = some tc :=
                    (runs_cons_jump st st1 code k hstep hseq).symm.trans hrun
                  have hmid' : ∀ u, u < k → ∀ su,
                      arm64_runs code u st1 = some su → su.pc ≠ ρ := by
                    intro u hu su hus
                    refine hmid (Nat.succ u) (by omega) su ?_
                    have h2 := hus
                    rwa [← runs_cons_jump st st1 code u hstep hseq] at h2
                  rw [go_exit_cons st st1 code ρ e hstep hst]
                  simp only [hseq, if_neg]
                  exact ih _ _ ⟨k, hk, hrun', htc, hmid'⟩

/-- **The state an export's run starts in.**  Named because four of the
    premises above and the theorem below all have to agree about it, and
    writing the record update out five times is how two of them come to
    disagree.

    The link register is the export's OWN end, not the image's: with several
    exports the image's end is past the last of them, so a body ending in a
    return would land in another export's code.  See `DylibExport.exportEnd`. -/
def startState (image : DylibImage) (export_ : DylibExport) (n : UInt64) : Arm64State :=
  { Arm64State.init n image.base with
      pc := export_.entry,
      x30 := UInt64.ofNat (DylibExport.exportEnd image export_) }

/-- **The body of an export, as a `Block`.**

    `Refine.Block` already says "a straight-line run with a composed effect" and
    `BlockCert` already says "the machine runs it to that effect", so this is a
    new name over old types rather than a parallel mechanism. What it adds is
    the two facts that make an export's body the *finished* case: it starts at
    the export's entry, and it ends AT the exit rather than short of it.

    `atExit` and `noEarly` are stated at the EXPORT's end, which is what makes
    every field of this structure per-export.  They used to be stated at
    `image.base + image.codeSize`, the image's end, so a `Block` for one export
    of several could not end where `atExit` required and `runs_to_body` — the
    only consumer of both — was unreachable for it.  For an image with one
    export the two addresses are the same number, so nothing about that case
    changes. -/
structure ExportBody (image : DylibImage) (export_ : DylibExport) where
  /-- the body, as a straight-line block -/
  block : Refine.Block
  /-- the body starts at the export's entry -/
  entry : export_.entry = block.entry_pc
  /-- the certificate: the machine runs the body to the composed effect -/
  cert : Refine.BlockCert image.code block
  /-- the body's effect ends at the export's own end

      Stated for the export's *start state* rather than for every state whose
      `pc` is the entry, and the weaker form is the true one. A body ends by
      returning, and a return jumps to whatever `x30` holds, so the body's last
      instruction lands on `st.x30` — not on the exit. The general statement is
      false for any body ending in a return: a state at the entry with
      `x30 := 0` returns to `0`. What makes the true statement go through is
      that `startState` is exactly the state which sets `x30` to the exit, and
      which the caller actually starts from. -/
  atExit : ∀ n : UInt64,
    (block.step (startState image export_ n)).pc
      = DylibExport.exportEnd image export_
  /-- no intermediate state of the run is already at the exit -/
  noEarly : ∀ (n : UInt64) (u : Nat) (hu : u < block.pcs.length) (su : Arm64State),
    arm64_runs image.code u (startState image export_ n) = some su →
    su.pc ≠ DylibExport.exportEnd image export_

/-- **AN EXPORT'S RESULT IS ITS BODY'S EFFECT.**  For every argument — and the
    argument is SYMBOLIC — the run succeeds and lands on the body's composed
    state.

    This is the half of a contract no evaluation could give, and it is where
    the absence of a step bound stops mattering: the step count is the body's
    own length, a literal, so the budget side condition is concrete arithmetic
    that `omega` closes. -/
theorem runs_to_body (image : DylibImage) (export_ : DylibExport)
    (b : ExportBody image export_)
    (hfuel : b.block.pcs.length + 1 ≤ DylibExport.exportFuel image 0)
    (n : UInt64) :
    Refine.runProg (Refine.dylibExportProg image export_) n
      = some (b.block.step (startState image export_ n)) := by
  have hlen : b.block.pcs.length < DylibExport.exportFuel image 0 := by omega
  -- `exportFuel` is `BASE + PATH * n`, so it is monotone in `n` and the bound
  -- the caller supplies at `n = 0` -- the minimum over all arguments -- is a
  -- bound at every argument.  This is the step that makes an n-dependent fuel
  -- cost the contract nothing: a straight-line body needs its own LENGTH, which
  -- is a literal, not a function of the argument.
  have hlen' : b.block.pcs.length < DylibExport.exportFuel image n := by
    have hmono : DylibExport.exportFuel image 0 ≤ DylibExport.exportFuel image n := by
      simp [DylibExport.exportFuel]
    omega
  have hmain : arm64_go_exit (startState image export_ n) image.code
      (DylibExport.exportEnd image export_) (DylibExport.exportFuel image n)
      = some (b.block.step (startState image export_ n)) :=
    go_exit_within image.code (DylibExport.exportEnd image export_) _
      (startState image export_ n) (b.block.step (startState image export_ n)) ⟨
      b.block.pcs.length, hlen',
      b.cert.runs _ b.entry,
      b.atExit n,
      by
        intro u hu su hus
        exact b.noEarly n u hu su hus⟩
  -- `runProg` at the export's `Prog` IS that `go_exit`, by definition
  have hshape : Refine.runProg (Refine.dylibExportProg image export_) n
      = arm64_go_exit (startState image export_ n) image.code
          (DylibExport.exportEnd image export_) (DylibExport.exportFuel image n) := rfl
  rw [hshape]
  exact hmain

/-- **THE CONTRACT, and the theorem that discharges it.**

    `runs_to_body` says the run lands on the body's effect; what remains is the
    one arithmetic fact, that the effect's result register IS the spec. For a
    real export that is `bv_decide`: a closed `UInt64` expression in the
    argument, checked against a stated spec.

    Split deliberately. Fusing the machine half and the spec half into one
    opaque term would make the spec — the part a human writes, and the part
    that can be wrong — invisible. -/
theorem agrees_of_body (image : DylibImage) (export_ : DylibExport)
    (b : ExportBody image export_) (spec : UInt64 → UInt64)
    (hfuel : b.block.pcs.length + 1 ≤ DylibExport.exportFuel image 0)
    (hreg : ∀ n, arm64_reg 0 (b.block.step (startState image export_ n)) = spec n) :
    Refine.export_result_spec image export_ spec := by
  intro n s hrun
  rw [runs_to_body image export_ b hfuel n] at hrun
  have hst : s = b.block.step (startState image export_ n) :=
    (Option.some.inj hrun).symm
  subst hst
  exact hreg n

/-- **A CALLER DISCHARGES ITS OBLIGATION AGAINST A REAL CONTRACT.**  This is the
    end of the chain phase 4 asks for, and it is the theorem that was
    previously a `sorry` over a false claim: given an export that agrees with
    `spec`, a caller's own contract follows, and nothing is admitted. -/
theorem caller_uses_contract (image : DylibImage) (export_ : DylibExport)
    (spec : UInt64 → UInt64)
    (hspec : Refine.export_result_spec image export_ spec) (n : UInt64) :
    Refine.DylibExportContract (Refine.dylibExportProg image export_) spec n :=
  Refine.dylib_export_contract_of_spec image export_ spec hspec n

/-- **The same, for a caller that already has the run in hand.** -/
theorem caller_may_read_result (image : DylibImage) (export_ : DylibExport)
    (spec : UInt64 → UInt64)
    (hspec : Refine.export_result_spec image export_ spec)
    (n : UInt64) (s : Arm64State)
    (hrun : Refine.runProg (Refine.dylibExportProg image export_) n = some s) :
    s.x0 = spec n := hspec n s hrun

/-- **The anti-trap: a spec must not be the identity.**

    FORMAL.md §11.2 [3] names the trap precisely — "`obs := fun n => n` again
    is the shape that made the old stub false, and it typechecks".  Here it does
    NOT typecheck, and the reason is structural rather than editorial:
    `agrees_of_body` takes `hreg` as a *hypothesis about the machine*, so the
    identity spec survives only if the export really is the identity, and
    `triple` is not.

    This lemma is the check that makes the difference *visible* rather than
    merely true. It is a decidable test on a spec and a witness, so a contract
    that has quietly degenerated to the identity can be caught by running it
    rather than by reading the proof. -/
def SpecIsIdentity (spec : UInt64 → UInt64) : Prop :=
  ∀ n, spec n = n

/-- A spec that is not the identity, witnessed.  What a real export supplies:
    `triple` is `n * 3`, which is not `n`. -/
theorem spec_triple_ne_identity :
    ¬ SpecIsIdentity (fun n => n * 3) := by
  intro h
  -- 7 * 3 = 21 and 21 ≠ 7, and both are closed facts about `UInt64`
  exact absurd (h 7) (by decide)

end Contracts
