# plan/step-01a: `lib/Scaffold.lean` — the one home of scaffold `sorry`
**Status: DONE 2026-11-06 (measured).** `lib/Scaffold.lean` holds the only 12 `sorry`s (`lib/` builds clean (`ensure_library`, 2026-11-06)); `test_formal_proof_gaps.py` 5/5 (ledger rows == `library_census`); `test_formal_doc_truth.py` allows holes only in Scaffold.

Class: mid      Size: M      Depends: 00a      Blocks: every step that adds a theorem with a hole
Source: `doc/finish-formal.md` Shared mechanics S1, S2, S4.

## Current state (measured; verified 2026-11-05)
- `lib/*.lean` contains no real `sorry` (only the word, in comments: `lib/ProofLib.lean` ~8434, `lib/Refine.lean` ~911). The first draft's "two `ProofLib` sorries at ~4510" do not exist.
- `formal/lean.py:153` `LIBRARY_MODULES = ("IEEE754","ProofLib","X86","work","Refine","Contracts","Peephole","Specs")`; build/census loops at lean.py:1223, 1264, 1550, 1790, 1985 iterate it.
- Every member must be uniform: `test_formal_sweep_truth.py:2596` asserts `set(SOURCES) == set(LIBRARY_MODULES)`; :2738 asserts each module names its imports at its top; `test_formal_axioms.py:85` has its OWN copy of the tuple; `test_formal_admitted.py` has per-module tables (`AXIOM_CLOSURE` ~1489-1509, a `(0,0,N,N)` tally table ~1270-1290); `test_formal_axiom_closure_pinned.py` pins `AXIOM_CLOSURE`.
- `lib/Peephole.lean` imports `ProofLib`, `X86`; nothing imports `Peephole`.

## Decisions already made
- New module `lib/Scaffold.lean`: `import ProofLib`, `import X86`, `import Peephole`. Imported by NOTHING. Appended LAST to `LIBRARY_MODULES`.
- It starts with ONE canary theorem `scaffold_canary : True := by sorry` whose ledger row (step-01b) says "positive control for the census; delete when the first real scaffold lands". Reason: a census that has never seen a hole proves nothing (see the trap in `formal/lean.py::library_census`'s docstring: an up-to-date `.olean` makes `lean` print nothing).
- Do NOT edit `lib/ProofLib.lean`, `lib/X86.lean` or `lib/Peephole.lean` in this step (S4: any edit rebuilds the olean and invalidates cached proof verdicts).
- `Scaffold` may also contain PROVED helper lemmas used only by scaffold theorems; promotion moves them.

## Work order
1. Create `lib/Scaffold.lean` with: a header comment (copy the tone of `lib/Peephole.lean`'s) stating: the ONLY file in `lib/` allowed to contain `sorry`; ledger = `formal/proof_gaps.py::SCAFFOLD_HOLES`; promotion procedure (prove it, move the theorem to its home module, delete the ledger row); and `set_option autoImplicit false`. Then the canary theorem.
2. `formal/lean.py:153`: append `"Scaffold"` to `LIBRARY_MODULES` (last). Read lines ~1223-1290 and ~1550, 1790, 1985 and the build-order logic around :609-627 to confirm the module's `import` lines are discovered automatically; fix only what breaks.
3. `test_formal_axioms.py:85`: add `"Scaffold"` to its tuple.
4. `test_formal_sweep_truth.py`: find `SOURCES` (grep `SOURCES =`) and every per-module table at ~2528-2760; add `Scaffold` rows exactly as the others (its imports are `ProofLib`, `X86`, `Peephole`).
5. `test_formal_admitted.py`: run the narrow tests first (Verification) and read each failure; add the `Scaffold` rows (`AXIOM_CLOSURE` and the tally table) **from the measured output**, not by guess. The canary reaches `sorryAx`, so its row has a nonzero "reaches" column; record it with a comment `# step-01a: scaffold canary`. Update `test_formal_axiom_closure_pinned.py` with the same measured tuple.
6. Build the library once through `formal/lean.py` (the tests do it; do not call `lean` yourself).

## Do NOT
- Do not put Scaffold in `import` position of any other module (a hole would then propagate into generated proofs).
- Do not widen an existing ceiling/pin to make a test pass; add the new row from a measurement.
- Do not launch `lean` directly (`run_lean` carries the memory/wall bounds).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_axioms.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_axiom_closure_pinned.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_sweep_truth.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
```
(Lean-heavy; if a file is too slow, run it alone and note the time.)

## Done when
- [ ] `lib/Scaffold.lean` exists with the header and the canary; last in `LIBRARY_MODULES`
- [ ] all five commands above pass; no pre-existing row changed value
- [ ] `python3 -c "import formal.lean as L; print(L.LIBRARY_MODULES[-1])"` prints `Scaffold`

## If stuck
If a test insists on a property Scaffold cannot have (e.g. "every module is imported by another"), STOP; write the exact failing assertion into this file's section "Blocked" and report. Do not special-case the test.
