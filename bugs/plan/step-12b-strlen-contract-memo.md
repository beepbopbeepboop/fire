# plan/step-12b: DECISION MEMO — the Lean contract for an extern whose result is the program's answer (`strlen`)
**Status: DONE 2026-11-07 (measured).** The memo exists in `bugs/FORMAL_string_value_model.md` ("Extern-result contract" + "Correction and measurement (2026-11-07)"): measured state (model folded to `5`, machine still `extern_strlen_step`, only `main_reaches_call_at_0x1000004bc` proved), and the decision CHANGED from a `sorry`-ed Scaffold theorem to a HYPOTHESIS structure (`StrlenReturns`/`ExternReturn`/`cstring_at`, typechecked in scratch, no `sorry`) in a new `lib/Extern.lean`. Step 12c is rewritten accordingly.
Class: hard      Size: M      Depends: 12a, 01a, 01b      Blocks: none
Source: `bugs/FORMAL_string_value_model.md` bullet at line ~801 ("closes when the model gains a `strlen`"); `lib/ProofLib.lean:977`.

## Current state (measured 2026-11-05)
- After 12a the generator never relies on `ProofLib.strlen` for a string it can name, and emits no post-extern theorem for `strlen`; what is NOT yet provable is "the program returns len(s)" end to end, because the model has no semantics for the extern call (`arm64_step` returns `none` at an address outside the image; see `_call_boundary`'s docstring, `formal/arm64_proof_gen.py:7653`).
- `ProofLib.strlen` (line 977) is a constant-zero stub still reachable from hand-written AST proofs (`ProofLib.lean:1215-1217`).

## Output of this step (design only; no code)
A committed section "Extern-result contract" in `bugs/FORMAL_string_value_model.md` Status containing, complete enough for a mid worker to execute without re-investigation:
1. The measurement that fixes the current state (the three commands that print: the proof of `len(local)` from 12a, the halt-at-call theorem name, the absence of the post-extern theorem).
2. The decision between exactly these readings, with the readings laid out and the recommendation marked: (A) an axiom-free `structure ExternContract` in `lib/Scaffold.lean` (`pre`: registers/memory at the BL; `post`: x0 = f(args), all callee-saved registers and SP preserved, memory unchanged), instantiated for `strlen` with `f` = length of the NUL-terminated byte run at the argument address read from the IMAGE's text (a `Nat -> UInt8` memory plus a `cstring_at mem addr n` predicate), the post-extern theorem restated with `x0 = n` and `n` the numeral of 12a, its proof `by sorry` and its ledger row in `formal/proof_gaps.py::SCAFFOLD_HOLES` (S1/S2 of `doc/finish-formal.md`); (B) change `ProofLib.strlen` to take the image text (rejected on cost: S4 repins).
3. Exact files/functions: `lib/Scaffold.lean` (new theorem names), `formal/proof_gaps.py` rows, the generator branch that emits the restated theorem (`formal/arm64_proof_gen.py` at the `RESULT_BEARING_EXTERNS` guard from 12a), the test rows.
4. The statement-truth check: why `x0 = n` is true on the machine for ASCII literals and for the wave-9 folded non-ASCII case (cite `formal/model/strings.py` TEXT ENCODING block), and why it is NOT claimed for a run-time string.
5. The pins that will move (`test_formal_admitted.py` `AXIOM_CLOSURE` only if Scaffold is counted; `test_formal_proof_gaps.py` ledger) and the commands.

## Do NOT
- Do not write Lean in this step. Do not add a `sorry`. Do not edit `lib/ProofLib.lean`.

## Verification
`python3 tools/dangling_doc_refs.py --ratchet` unchanged versus before (you only edited a doc).

## Done when
- [ ] the section exists in `bugs/FORMAL_string_value_model.md` with the five parts above
- [ ] a follow-up step file `bugs/plan/step-12c-strlen-contract.md` (Class mid) is written from it in the same commit

## If stuck
Write the readings you could lay out and the single missing measurement, with its command, then stop.
