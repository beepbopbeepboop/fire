# 749 `native_decide`/`bv_decide` sites put `Lean.ofReduceBool` in every theorem's closure, and §7's inventory had no row for it

**Status 2026-10-04 (`work/formal21-5`): item 2 is DONE, and item 1 is DONE for
the half a text census can decide — the 749 sites are now attributed to the 56
THEOREMS that carry them, out of 493 declarations, and the per-tactic split says
which of them have a kernel-checked spelling standing next to them. What is left
is item 1's transitive half (`#print axioms`, a Lean run) and items 3–4, and
§"What landed" names the eight theorems item 3 should start from.** Read that
before "The exact next step", which is the plan as it was written.

**Status: the census part is DONE.** The audit of 2026-10-04
(`bugs/FORMAL_trust_audit_2026-10-04.md` §`lib/*.lean`) counted the sites and put
them in FORMAL.md §7's trust inventory as row 10. What was left is the
measurement this worker could not make: which theorems actually reach the axiom,
and the plan to shrink the number.

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

## What landed: the sites, attributed to theorems

`formal/admitted.py::library_trust_by_declaration` is item 2 of "The exact next
step" — the other direction from `library_trust`, which reports lines. It walks
each `lib/*.lean` again and asks **which declaration each site is inside**, which
is the question that makes the number actionable: a file-level ceiling says "749
in `ProofLib`" and a per-theorem one says "59 of them are in `work_step_movk`".

    $ python3 -c "
    import sys; sys.path.insert(0, '.')
    from formal import admitted as A
    for l in A.library_trust_by_declaration_lines(A.lean_dir('.'), top=4): print(l)"
    Contracts: 1 declaration(s) with a hit; spec_triple_ne_identity@332 [axiom_tactic=1 (native_decide=1)]
    ProofLib: 52 declaration(s) with a hit; work_step_movk@4518 [axiom_tactic=59 (native_decide=2,bv_decide=57)]; …
    X86: 3 declaration(s) with a hit; mem_read_bytes_write_same@2452 [axiom_tactic=2 (bv_decide=2)]; …

**What it measures, on this tree:**

| | |
|---|---|
| sites, unchanged | **749** (66 `native_decide`, 683 `bv_decide`) |
| declarations in `lib/` | **493** (`ProofLib` 286, `X86` 174, `Refine` 25, `work` 20, `Contracts` 8) |
| declarations carrying at least one site | **56** — 11 % of them, carrying 100 % of the sites |
| sites in no declaration | **0** — no top-level tactic script, no head `_LEAN_DECL_RE` misses |
| median theorem that carries any | **8 sites**; the largest is `work_step_movk` at 59 |
| theorems with exactly one site | **19** — 2.5 % of the sites, 34 % of the theorems |
| …of those, the single site is a `native_decide` | **8** — and those are item 3's list |

The distribution is the finding rather than the total: **56 theorems hold the
whole census and 223 of the 749 sites (30 %) are in five of them**
(`work_step_movk` 59, `work_step_movz` 53, `work_step_svc` 38, `work_step_br` 37,
`work_step_orn` 36) — which are the `∀ w, … ≠ …` bit-pattern lemmas `bv_decide`
exists for. **Item 3's advice to replace the cheap sites first is right and its
scope is now exact**, because the per-tactic split separates the two populations
that look identical in a count of 749:

* **19 theorems with one site**, of which **ten are the `arm64_flag_*` family**
  (`_eq`, `_ne`, `_ge`, `_gt`, `_le`, `_lt` and their `_s` signed forms), and
  every one of those is `simp only [arm64_matches_condition, arm64_subs_flags];
  bv_decide` — a bit-pattern fact with no kernel-checked spelling short of
  writing the arithmetic out. **These are the ones to leave**, which is what the
  original item 3 said about the `bv_decide` population and now has names.
* **8 theorems with one site that is a `native_decide`**, and these are the
  shortlist: `Semantics_refutable`, `backward_branch_in_image`,
  `backward_branch_run_none`, `work_step_mov`, `toNat_sub_one`, `toNat_sub_two`
  (`ProofLib`), `lowMask_eight` (`X86`), `spec_triple_ne_identity`
  (`Contracts`). `toNat_sub_one` is the shape the original item 3 described —
  `have hpos : 1 ≤ n.toNat := …; omega` with a `rw` and a `calc` around it —
  where the arithmetic is closed and `decide`/`norm_num`/`omega` plausibly
  reaches it. **Nobody has run Lean on any of the eight**, so "plausibly" is the
  honest word: that is item 1's transitive measurement and it is the next step.

**Two invariants the attribution is pinned on**, both in
`test_formal_admitted.py`'s new PURE check
(`test_the_census_is_attributed_to_theorems_not_only_to_lines`, 20/20 with it):

* the per-declaration counts **SUM** to the file-level count, per module and per
  kind, so an attribution that loses a site reports a smaller plausible number
  and one that invents one reports a bigger — neither is visible without it.
  Measured as a pin: an attribution that dropped every site after line 5000
  reports `675 attributed against 744` and fails;
* the per-tactic split **sums** to each theorem's site count, which is what says
  the split (`native_decide` vs `bv_decide`) did not drift from the total;
* no site is in no theorem, and the two ceilings — 19 one-site theorems and 8
  of them `native_decide`-only — are ceilings rather than equalities, so a
  replacement lowers them and a regression raises them.

**What this does NOT establish**, and it is the half that needs Lean: a theorem
with no site of its own can still reach `Lean.ofReduceBool` through a CALLEE it
uses. So 56 is an upper bound on the theorems that reach the axiom and a *lower*
bound on the count of sites, not a measurement of the closure. That is exactly
what `#print axioms` decides and what item 1 is for.

## What is still missing, and the exact next step

1. ~~**Attribute the 749 to theorems rather than to sites.**~~ **DONE** —
   `library_trust_by_declaration`, and the measurement is in "What landed"
   above: **56 theorems of 493, with 8 named as the replaceable shortlist.**
   This item is moved to the top of the list because item 3 is now decided by it
   rather than guessed at.

2. **Measure the closure, which the text census cannot.** The one measurement
   this worker did not run, because a light worker does not launch Lean:

   ```
   cat > .tmp/ax.lean <<'EOF'
   import ProofLib
   open ProofLib
   #print axioms toNat_sub_one
   #print axioms Semantics_refutable
   #print axioms work_step_movk
   #print axioms step_lemmas_sound
   #print axioms eval_eq_mojo
   #print axioms dylib_export_contract
   EOF
   python3 tools/memslot.py --gb 8 --label axiomcensus -- \
       lake env lean .tmp/ax.lean
   ```

   **Every Lean run goes through `formal/lean.py::run_lean`**, which is what
   enforces the wall and CPU bounds; `lake env lean` above is the shape of the
   command, not an instruction to launch `lean` directly. The names are no longer
   guesses: the first three are on the shortlist "What landed" names
   (`toNat_sub_one`, `Semantics_refutable`) and the biggest theorem
   (`work_step_movk`), and the last three are the theorems whose closure matters
   most — the end-to-end soundness statement, the AST bridge and the dylib
   contract. Get the names from
   `formal/admitted.py::library_trust_by_declaration_lines` rather than from a
   grep. Expected output: `propext`, `Classical.choice`, `Quot.sound`,
   `Lean.ofReduceBool`. **`Lean.ofReduceBool` appearing is the confirmation; a
   theorem WITHOUT it is the interesting result** — and the interesting result is
   expected for at least some of the 437 declarations that carry no site, because
   a site reached through a CALLEE is still an axiom in the closure. That is the
   half the attribution cannot do, and it is why this item is still open.

3. **Replace the cheap sites first**, and the list is now exact rather than a
   population: the eight theorems in "What landed" whose single site is a
   `native_decide`. `toNat_sub_one` is the shape this item always described
   (`have hpos : 1 ≤ n.toNat := …; omega` inside a `rw`/`calc`), where the
   arithmetic is closed. The 683 `bv_decide` sites are the `∀ w, … ≠ …` bit-pattern
   lemmas, `bv_decide` is the right tool there, and ten of the 19 one-site
   theorems are the `arm64_flag_*` family — **those are the ones to leave**, now
   by name rather than by class.

4. **Keep the ceiling honest.** `test_formal_admitted.py`'s `LIBRARY_TRUST` pins
   749 as a CEILING, failing when it rises and reporting it when it falls, and
   this round added the per-theorem ceilings beside it (19 one-site theorems, 8
   of them `native_decide`-only). Land a replacement with the ceilings lowered
   and the commit saying which sites went; that is the `expect=`-discipline
   direction, and it is the only thing that makes the number mean something over
   time.

## What this is not

Not a soundness bug, not a false theorem, and not a reason to distrust a green
proof about machine semantics — the semantic-model layer is proved, and the
`native_decide` sites are its arithmetic. It is an inventory gap in the document
whose purpose is to have none.