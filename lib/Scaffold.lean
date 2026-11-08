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

/-- The shape the generator's finder must establish for a method before the write-back
    contracts below apply: from `entry`, with `x0` the cell pointer and `x1` the value,
    `code` stores `x1` to `[x0]` before every RET, touches the stack only within
    `[sp - W, sp)`, and returns through `x30`.  OPAQUE on purpose: without it the
    contracts would quantify over arbitrary code and be false.  Giving it a
    definition (and a decision procedure over `code`) is the first proof obligation
    of a real discharge. -/
opaque CellSetMethod (code : Nat → UInt8) (entry exit_pc W : Nat) : Prop

/-- Scaffold: write-back contract for a by-reference one-field mutator (single exit).
    The cell is the CALLER's word, so it lies ABOVE the callee's stack window; the
    depth bound is the hypothesis `h_above` (never an axiom), and `hfit` says the
    8-byte cell does not wrap.  Conclusion: the write-back happened, and nothing
    outside the cell and the callee's window `[sp - W, sp)` changed.
    (`Frame.FrameBelow` is the wrong premise here: it is for receiver frames at the
    callee's entry `sp`, not for a cell above it.  Memo: FORMAL_known_limits §6.3.) -/
theorem scaffold_cell_writeback_one_exit
    (s s' : Arm64State) (code : Nat → UInt8) (exit_pc fuel : Nat) (p v : UInt64) (W : Nat)
    (hmeth : CellSetMethod code s.pc exit_pc W)
    (hx0 : s.x0 = p) (hx1 : s.x1 = v)
    (hfit : Frame.FrameFits p 1)
    (h_above : s.sp.toNat + W ≤ p.toNat)
    (hrun : arm64_exec_go_exit s code exit_pc fuel = some s') :
    Frame.frameRead s'.mem p 0 = v ∧
    ∀ a, (a < p.toNat ∨ p.toNat + 8 ≤ a) →
      (a < s.sp.toNat - W ∨ s.sp.toNat ≤ a) → s'.mem a = s.mem a := by sorry

/-- Scaffold: write-back contract for a by-reference one-field mutator with several
    RET sites.  The CONCLUSION is the same as the single-exit one (every RET returns
    through the same `x30`), but the proof owes one case per RET address in `rets`:
    the write-back repeats on every exit.  `hrets` records that the code's RET sites
    are exactly `rets`; no generator emits more than one RET today, so this has no
    producer yet. -/
theorem scaffold_cell_writeback_multi_exit
    (s s' : Arm64State) (code : Nat → UInt8) (exit_pc fuel : Nat) (p v : UInt64) (W : Nat)
    (rets : List Nat) (hrets : rets.length ≥ 2)
    (hmeth : CellSetMethod code s.pc exit_pc W)
    (hx0 : s.x0 = p) (hx1 : s.x1 = v)
    (hfit : Frame.FrameFits p 1)
    (h_above : s.sp.toNat + W ≤ p.toNat)
    (hrun : arm64_exec_go_exit s code exit_pc fuel = some s') :
    Frame.frameRead s'.mem p 0 = v ∧
    ∀ a, (a < p.toNat ∨ p.toNat + 8 ≤ a) →
      (a < s.sp.toNat - W ∨ s.sp.toNat ≤ a) → s'.mem a = s.mem a := by sorry
