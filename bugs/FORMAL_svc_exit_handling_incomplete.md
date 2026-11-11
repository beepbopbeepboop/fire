# FORMAL: `svc` exit handling is not structurally complete

Status: OPEN. Filed 2026-11-11. Parent: `FORMAL_wrong_spec_accepted_since_overflow_traps.md`.

## Symptom

On an overflowing input the Lean model falls through the overflow trap block and returns a value the real program never
produces. The machine stops at the exit `svc`; the model does not. Every `svc` is modelled as a no-op, so there is no
exit at all. The wrong spec is therefore admitted only as a `sorry`, and the teeth check cannot reject it.

## What is in place

- `lib/ProofLib.lean`, the `0xD4000001` arm of `arm64_step`: a staged split. `x16 = 1` gives `none`; otherwise `some
  { s with pc := s.pc + 4 }`. This is NOT on master. It is in `git stash` entry `svc-model-wip` on the archive branch
  (with `lib/ProofLibSteps2.lean` and `formal/arm64_proof_gen.py`). Both Lean files typecheck with it.
- `lib/ProofLibSteps2.lean`: `work_step_svc` states the x16 `if`; `work_step_svc_exit` and `work_step_svc_write` are its
  two corollaries (staged, same stash).
- `formal/arm64_proof_gen.py` (staged): SVC right-hand side at `_step_rhs` idx 35 and `_step_rhs_generic` idx 35 is the x16
  `if`. Committed on master: none of this.
- The emitter always sets x16 before an `svc`: `movz x16, #1 ; svc #0x80` for exit (`formal/arm64_codegen.py`
  `_emit_exit`, `2148-2157`, `3251-3331`) and `movz x16, #4` for write (`8852-8883`, and the trap block at `2217-2266`).

## What is NOT in place structurally

1. **The generator's step lemmas are per-encoding, not per-state.** `_WORK_STEP` maps the SVC encoding to one lemma,
   `work_step_svc`. The exit/write choice depends on x16, which is machine state, so one encoding cannot select between
   two lemmas.
2. **Static x16 is not threaded to the svc.** `_step_rhs(w, idx)` takes the word only. Its nine call sites never see the
   preceding `movz`. The reg-16 chain in `_emit_reg_chain` (`formal/arm64_proof_gen.py`, around line 6600) computes
   `arm64_reg 16` through a block, so the static value is available there, but nothing passes it to the svc step.
3. **No hypothesis for the dynamic case.** When x16 is not statically known, the write form needs `arm64_reg 16 s ≠ 1`.
   The generated theorems have no slot for that hypothesis, and nothing says where it is discharged or assumed.
4. **Block termination is decided by encoding.** `_is_svc` and `_trap_terminating` treat every `svc` tail as a bounded stop.
   With write as a return, a write `svc` in the middle of a trap block must not end the block.
5. **`x0` is not modelled after a write.** `SYS_write` returns the byte count in `x0`. Nothing marks a read of `x0` after a
   continuing `svc` as outside the model, so such a path is silently believed.

## What we want to know

- For each `svc` in an image, is x16 statically 1, statically 4, or dynamic? (Measure over the example corpus and the
  overflow trap blocks; a dynamic one is a finding, not a default.)
- Does any path read `x0` after a write `svc`? (Should be none in emitted code; check.)
- With the staged model, does the default-path proof check once the dynamic case is assumed?

## Design

- **Model (Lean):** `svc` is x16-discriminating. Exit is `none`; write is `pc + 4`. This is the true semantics and does not
  change.
- **Generator, static case:** an `svc` whose x16 is determined by the preceding `movz` (through the reg-16 chain) gets
  the exit or write lemma, with its `hx` discharged from the chain. An exit `svc` ends the path; the return path after
  it needs nothing beyond the `svc` itself.
- **Generator, dynamic case:** the write form is assumed, not proved. The assumption is a named hypothesis
  (`svc_write_assumed`) on the generated theorem, so every caller of the dylib contract sees it. A dynamic `svc` with no
  such assumption available is refused, not guessed.
- **Termination:** `_is_svc` is replaced by a predicate on the static exit form, so only an exit `svc` is a bounded stop.
- **x0:** a path that reads `x0` after a write `svc` is refused.

## How to fix (ordered)

1. Measure (the three questions above). Land the measurement as a test that fails on a dynamic x16 `svc` in the corpus.
2. Thread static x16 into `_step_rhs` (add an optional `svc_x16` argument, pass it from `_emit_reg_chain` and the other
   call sites). Keep the default as the write form.
3. Restore the staged split on top of step 2. Confirm the default-path proof checks.
4. Add `svc_write_assumed` to the generated theorem for dynamic sites, and make `_is_svc` the exit-only predicate.
5. Run the formal dylib test. Target: the marker's 6 failures, and the wrong-spec teeth check rejected.
6. Only then remove the `expect=` marker on formal-dylib.

Related: `FORMAL_wrong_spec_accepted_since_overflow_traps.md` (the soundness hole this closes).
