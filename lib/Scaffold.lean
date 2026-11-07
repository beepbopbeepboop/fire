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

/-- Scaffold: write-back contract for a by-reference one-field mutator (single exit).
    Depth bound is a hypothesis, not an axiom. The cell is in the caller's frame. -/
theorem scaffold_cell_writeback_one_exit
    (s s' : Arm64State) (p : UInt64)
    (h_cell : True) :
    True := by sorry

/-- Scaffold: write-back contract for a by-reference one-field mutator (multiple exits).
    Per-exit obligation is scaffolded as a hole pending proof. Depth bound is a hypothesis. -/
theorem scaffold_cell_writeback_multi_exit
    (s s' : Arm64State) (p : UInt64)
    (h_cell : True) :
    True := by sorry
