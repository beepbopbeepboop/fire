# plan/step-12c: Lean contract for `strlen` as the program's answer (extern contract)
Class: mid      Size: M      Depends: 12a, 12b, 01a, 01b      Blocks: none
Source: `bugs/FORMAL_string_value_model.md` "Extern-result contract" (step-12b memo); `lib/ProofLib.lean:977-978` (`strlen` stub); `formal/arm64_proof_gen.py:12109,12260`.

## Current state (measured 2026-11-05)
- After 12a, `len(<string the image holds>)` is folded to a numeral in the proof model for known strings; any other string `len` is refused (no fabricated value). The post-extern theorem `*_post_extern_given_callee_returns` is suppressed for `strlen` via `RESULT_BEARING_EXTERNS` in the generator (see 12a). What is not yet provable is "the program returns len(s)" end-to-end when `strlen` is the callee whose result is the program's answer, because there is no contract stating `x0 = f(args)` with the image's text.
- `lib/ProofLib.strlen` remains the constant-zero stub (do not edit per S4). The design is in the "Extern-result contract" section of `bugs/FORMAL_string_value_model.md`.

## Decisions (from memo)
- Add an axiom-free `structure ExternContract` in `lib/Scaffold.lean` (`pre`: registers/memory at BL; `post`: `x0 = f(args)`, all callee-saved registers and SP preserved, memory unchanged). Instantiate for `strlen` with `f` = length of NUL-terminated byte run at argument address read from the IMAGE's text (`Nat -> UInt8` + `cstring_at mem addr n`). Restate the post-extern theorem with `x0 = n` where `n` is the numeral from 12a; proof `by sorry`; add ledger row in `formal/proof_gaps.py::SCAFFOLD_HOLES`.
- Do **not** change `ProofLib.strlen` to take image text (rejected on cost/S4).
- Only claim this for strings whose bytes are in the image (ASCII and wave-9 folded non-ASCII cases consistent with `formal/model/strings.py` TEXT ENCODING). Not claimed for run-time/computed/extern-result strings.

## Work order
1. **`lib/Scaffold.lean`**: add `ExternContract` structure and a `strlen` instance/theorem(s) as specified in the memo. Proofs `by sorry`. Follow S1 (only Scaffold gets scaffold sorrys). Import `ProofLib`, `X86`, `Peephole` as needed; do not import Scaffold elsewhere.
2. **`formal/proof_gaps.py`**: add entries to `SCAFFOLD_HOLES` for the new declaration names (step number 12c, reason, kind). Update census expectations as needed.
3. **Generator changes**: in `formal/arm64_proof_gen.py` at the `RESULT_BEARING_EXTERNS` guard (from 12a), emit the restated post-extern theorem using the new contract for `strlen`. Check `formal/x86_64_proof_gen.py` for parity; add support if it emits similar theorems.
4. **Tests**: add/update tests in `test_formal_call_proof_gen.py` and ensure `test_formal_proof_gaps.py` passes with the new ledger entries. Update `test_formal_admitted.py` pins only if `AXIOM_CLOSURE` changes (read new measurement).
5. **Verify pins**: run the commands from the memo.

## Do NOT
- Do not edit `lib/ProofLib.lean` or `lib/X86.lean`.
- Do not put `sorry` in `lib/Peephole.lean` or other library modules.
- Do not claim the contract for run-time strings.
- Do not widen beyond `strlen` unless explicitly justified.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend x86_64
```

## Done when
- [ ] `ExternContract` and `strlen` contract theorem(s) exist in `lib/Scaffold.lean` with `by sorry`
- [ ] `formal/proof_gaps.py::SCAFFOLD_HOLES` updated and `test_formal_proof_gaps.py` passes
- [ ] Generator emits restated post-extern theorem for `strlen` under the contract (arm64; x86-64 parity checked)
- [ ] Tests updated and passing
- [ ] `test_formal_admitted.py` pins updated if needed (measured, not widened blindly)

## If stuck
Write measurements and exact failing names into the step notes and stop. Do not fabricate proofs.
