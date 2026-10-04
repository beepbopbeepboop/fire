# 749 `native_decide`/`bv_decide` sites put `Lean.ofReduceBool` in every theorem's closure, and §7's inventory had no row for it

**Status: OPEN, and the census part is DONE.** The audit of 2026-10-04
(`bugs/FORMAL_trust_audit_2026-10-04.md` §`lib/*.lean`) counted the sites and put
them in FORMAL.md §7's trust inventory as row 10. What is left is the measurement
this worker could not make: which theorems actually reach the axiom, and the plan
to shrink the number.

Claim: `sweep20:admitted-audit`. Not any `formal19` doc.

## What I ran

```
$ python3 -c "
import sys; sys.path.insert(0, '.')
from formal import admitted as A
for line in A.library_trust_lines(A.lean_dir('.')): print(line)"
Contracts: axiom_tactic=1 at 336
ProofLib: axiom_tactic=744 at 1198,1227,2223,2224,2225,2226,+738
X86: axiom_tactic=4 at 2336,2383,2385,2407
```

## What I saw

- **0** `axiom`/`opaque` declarations and **0** `sorry` in all five `lib/`
  modules — so FORMAL.md §7's "no Lean `axiom` and no `opaque` anywhere;
  everything is assumed in the `sorry` sense" is true of the SOURCE TEXT.
- **749** proof sites closed by `native_decide` (64 in `ProofLib`) or `bv_decide`
  (680 in `ProofLib`, plus 1 in `Contracts` and 4 in `X86`). Neither goes through
  the kernel: both compile a decision procedure and run it, so the proof term
  reaches Lean's `Lean.ofReduceBool` and `#print axioms` reports it. `OPUS.md` §1
  already says this about a generated theorem ("plus the project's usual
  `native_decide`/`bv_decide` step-lemma axioms") — §7's inventory, which is the
  document whose whole job is "what a proof currently rests on", had no row.

## Why it is not a hole

Neither tactic can prove a **false** statement: it evaluates the goal's decision
procedure and answers `True` only when the evaluation says so. What they move is
where the trust sits — from the kernel to the generated C code and the C compiler —
and that is why a machine simulation with millions of steps finishes at all.
Every other `sorry` in this project is a hole over a claim somebody might have got
wrong; this is not.

So the fix is not to remove them. It is to (a) count them, which is now done and
pinned, and (b) shrink them where the kernel can afford it.

## The exact next step

1. **Measure the closure, which the text census cannot.** The one measurement
   this worker did not run, because a light worker does not launch Lean:

   ```
   cat > .tmp/ax.lean <<'EOF'
   import ProofLib
   open ProofLib
   #print axioms step_lemmas_sound
   #print axioms eval_eq_mojo
   #print axioms dylib_export_contract
   EOF
   python3 tools/memslot.py --gb 8 --label axiomcensus -- \
       lake env lean .tmp/ax.lean
   ```

   (the three names are guesses at theorems that are certainly proved with
   `native_decide`/`bv_decide` — pick real ones with
   `grep -n "native_decide\|bv_decide" lib/ProofLib.lean | head`. The point is the
   `#print axioms` lines, not the names.) Expected output: `propext`,
   `Classical.choice`, `Quot.sound`, `Lean.ofReduceBool`. **`Lean.ofReduceBool`
   appearing is the confirmation; a theorem WITHOUT it is the interesting result**
   and means a site can be replaced by a kernel-checked proof.

2. **Attribute the 749 to theorems rather than to sites.**
   `library_trust` reports LINES, deliberately, because a count with no location
   is a number nobody can act on. The next step is the other direction: for each
   top-level `theorem`/`lemma` in `lib/`, the number of axiom-carrying tactic
   sites in its own proof, so the ceiling can be lowered per theorem rather than
   per file.

3. **Replace the cheap sites first.** The 64 `native_decide` in `ProofLib` are
   mostly `(by native_decide)` on closed `UInt64`/`Nat` arithmetic
   (`have h1 : (1 : UInt64).toNat = 1 := by native_decide`, `exact absurd h_opc (by
   native_decide)`) — a `decide` or `rfl` closes those, and they are 8% of the
   count. The 680 `bv_decide` are the `∀ w, … ≠ …` bit-pattern lemmas, where
   `bv_decide` is the right tool and `decide` is often out of its depth; those are
   the ones to leave.

4. **Keep the ceiling honest.** `test_formal_admitted.py`'s `LIBRARY_TRUST` pins
   749 as a CEILING, failing when it rises and reporting it when it falls. Land a
   replacement with the ceiling lowered and the commit saying which sites went;
   that is the `expect=`-discipline direction, and it is the only thing that makes
   the number mean something over time.

## What this is not

Not a soundness bug, not a false theorem, and not a reason to distrust a green
proof about machine semantics — the semantic-model layer is proved, and the
`native_decide` sites are its arithmetic. It is an inventory gap in the document
whose purpose is to have none.