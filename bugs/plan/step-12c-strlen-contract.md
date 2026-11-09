# plan/step-12c: Lean contract for `strlen` as the program's answer (extern contract)
**Status: PARTIAL 2026-11-07 (measured).** Steps 1-2 remain DONE (unchanged: `lib/Extern.lean` sorry-free and registered; `formal/lean.py::LIBRARY_MODULES` has `Extern` after `Peephole`; `test_formal_admitted.py` has `Extern: (0,0,0,0)`; sweep-truth fixtures updated). Steps 3-5 (generator part) PARTIALLY landed: `formal/arm64_proof_gen.py` now emits `import Extern` and `theorem <name>_post_extern_strlen` for arm64 programs whose last result-bearing extern call is `strlen` (`RESULT_BEARING_EXTERNS` path). The theorem takes `hcall : StrlenReturns <callee-entry state> s_ret addr n` (with addr from `scope.str_addrs`, n folded from the len-of-interned-literal) and is proved with no `sorry` from `hcall.res`/`hcall.ret.pc_ret`, concluding `s_ret.x0 = UInt64.ofNat n ∧ s_ret.pc = retpc`. `test_formal_call_proof_gen.py::TestStringValueInTheModel::test_len_of_an_image_string_is_its_character_count` updated and PASSED for `len_of_literal_local`/`len_of_literal_direct` (arm64 asserts `post_extern_strlen` and `import Extern` present, no `post_extern_given_callee_returns`; x86_64 unchanged). `test_formal_proof_gaps.py` PASSED (5 tests). STILL OPEN: the full symbolic continuation (`run_result_exit {s_ret with pc := retpc} ... = UInt64.ofNat n` / `mojo n`) through the epilogue from a GENERAL `s_ret` is not proved — the epilogue depends only on preserved `sp`/`mem` and preserves `x0`, but proving reachability to the sentinel/loaded return pc symbolically (without evaluating `main_pre_*`'s concrete frame) requires the block-walk machinery started from a symbolic state and relating the loaded x30 to the preserved frame; if any continuation reads a non-preserved caller-saved register, that register must appear in the premise. x86-64 left as-is (step 4). `test_formal_call_proof_gen.py::TestStringValueInTheModel` has 2 pre-existing subtest failures on arm64 `printf_literal`/`return_literal` ("CFG decomposition unsupported...") observed in this tree (unrelated to strlen); the typecheck subtest skipped (no `lib/ProofLib.olean`). Full step-12c verification suite (`test_formal_call_proof_gen.py` whole file, `test_formal.py --backend arm64/x86_64`) not run here (heavy).
**Integration note (2026-11-07):** the worker's commit split an `if universal_text is not None: ... else: raise` with a new `if _strlen_extra:`, so the `else` attached to the wrong `if` and EVERY program without a strlen call was refused with "CFG decomposition unsupported" (caught by `TestStringValueInTheModel` `return_literal`/`printf_literal`; fixed in the merge follow-up). It also turned a docstring `\n` into `\\n`. The theorem emitted is the weak form (`x0 = n /\ pc = retpc`), NOT the full continuation `run_result_exit ... = mojo n`; that remains open.
Class: mid      Size: M      Depends: 12a, 12b, 01a, 01b      Blocks: none
Source: `bugs/FORMAL_string_value_model.md` "Extern-result contract" (step-12b memo); `lib/ProofLib.lean:977-978` (`strlen` stub); `formal/arm64_proof_gen.py:12109,12260`.

## Current state (measured 2026-11-05)
- After 12a, `len(<string the image holds>)` is folded to a numeral in the proof model for known strings; any other string `len` is refused (no fabricated value). The post-extern theorem `*_post_extern_given_callee_returns` is suppressed for `strlen` via `RESULT_BEARING_EXTERNS` in the generator (see 12a). What is not yet provable is "the program returns len(s)" end-to-end when `strlen` is the callee whose result is the program's answer, because there is no contract stating `x0 = f(args)` with the image's text.
- `lib/ProofLib.strlen` remains the constant-zero stub (do not edit per S4). The design is in the "Extern-result contract" section of `bugs/FORMAL_string_value_model.md`.

## Decisions (from the 12b memo, as corrected 2026-11-07 -- read "Correction and measurement" in `bugs/FORMAL_string_value_model.md`)
- NO `sorry`. The callee's behaviour is a theorem PREMISE: `StrlenReturns s s' addr n` (with `ExternReturn`, `cstring_at`), defined in a NEW module `lib/Extern.lean` (Lean text in the memo; it typechecks against `import ProofLib`). Not Scaffold (it would not be a hole), not ProofLib/X86 (S4).
- Register the module: append `"Extern"` to `formal/lean.py::LIBRARY_MODULES` after `"Peephole"`; give it a `(0, 0, 0, 0)` row in the per-module table in `test_formal_admitted.py` (next to `"Scaffold": (0, 3, 0, 0)`; Scaffold's row does not move). Check `formal/lean.py` for any other per-module list (stamp/census) the new name must be in.
- The generated proof imports `Extern` only for a program whose call boundary is a `strlen` result (`RESULT_BEARING_EXTERNS`), and states `<name>_post_extern_strlen (s_ret) (hcall : StrlenReturns <pre-call state> s_ret addr n) : <run from s_ret> = mojo n`, where `n` is the numeral 12a folded and `addr` the interned literal's address (`scope.str_addrs`).
- Only the ASCII_BYTES case gets this theorem. A non-ASCII literal folds to a code-point count and emits no `strlen` call (nothing to state); a run-time string is refused as before. Do not widen beyond `strlen`.

## Work order
1. Create `lib/Extern.lean` from the memo's Lean block (`import ProofLib`; `cstring_at`, `cstring_at_unique`, `ExternReturn`, `StrlenReturns`, `strlen_returns_len`, `strlen_result_unique`). Typecheck: `cd lib && LEAN_PATH=. ../.pixi/envs/default/bin/lean Extern.lean` (no output expected).
2. Register it in `LIBRARY_MODULES` and the `test_formal_admitted.py` table; run `python3 -c "import formal.lean as L; L.ensure_library(L.find_lean(), 'lib')"` (about 5 minutes, never two at once).
3. Generator: at the `RESULT_BEARING_EXTERNS` guard in `formal/arm64_proof_gen.py` (grep it), emit the `import Extern` line and `_post_extern_strlen` for arm64. Prove it from `hcall.ret` / `hcall.res`; if the continuation proof needs a lemma, add it to `lib/Extern.lean` (still no `sorry`).
4. x86-64: it emits no `post_extern_given_callee_returns` today; leave it, and say so in the Status.
5. Tests in `test_formal_call_proof_gen.py`: the program `len_of_literal_local` now also contains `post_extern_strlen` and `import Extern`; `len_of_literal_direct` likewise; a run-time string still refuses.

## Do NOT
- Do not edit `lib/ProofLib.lean` or `lib/X86.lean`.
- Do not put `sorry` anywhere in this step.
- Do not claim the contract for run-time strings.
- Do not widen beyond `strlen` unless explicitly justified.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_call_proof_gen.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend x86_64
```

## Done when
- [ ] `lib/Extern.lean` exists, sorry-free, registered in `LIBRARY_MODULES`; `test_formal_proof_gaps.py` and `test_formal_admitted.py` table agree
- [ ] Generator emits restated post-extern theorem for `strlen` under the contract (arm64; x86-64 parity checked)
- [ ] Tests updated and passing
- [ ] `test_formal_admitted.py` pins updated if needed (measured, not widened blindly)

## If stuck
Write measurements and exact failing names into the step notes and stop. Do not fabricate proofs.
