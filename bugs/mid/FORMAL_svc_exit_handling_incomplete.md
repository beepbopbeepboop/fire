# FORMAL: `svc` exit handling is not structurally complete

Status: PARTIALLY LANDED 2026-11-11. Parent: the overflow-guard wrong-spec fix (the guarded contract in `formal/arm64_proof_gen.py::_dylib_contract_proof`, 2026-11-12).

**2026-11-12 (gate `reg-formal-ast-bridge-two-arg`): the default-path walk can
again cross an `svc`.** The model change in f03896fff made every compiled
function's stack-floor-guard trap block a real halt, and `_gen_run_cert` then
refused it because its last step is `none`; every universal theorem in the
corpus was refused (`def plain(a, b): return a + b` was enough). Landed here:

- `_is_svc_exit` is the exit-only structural predicate, and
  `_trap_terminating`/`_unfollowable_calls` use it, so a write `svc` tail is
  not a bounded stop.  `_svc_static_x16` now accepts both `movz x16` and
  `movz w16` (the emitter spells both).
- `_gen_run_cert` admits a static write `svc` whose `movz` is in the run and
  whose fall-through rewrites `x0` before it is read (`_reads_x0` /
  `_x0_reassigned_after_write`); exit `svc`s are still refused by it.
- `_gen_halt_cert` proves the block that DOES end in an exit `svc` halts:
  ordinary segments are run certificates, write `svc`s are
  `arm64_go_exit_step_jump_at` with their `hx` discharged from the segment's
  own x16 chain, and the final step is `none`; the theorem is applied by
  `emit_block` on a direct branch into the block.  The universal statement
  uses `none => True` when such a branch is reachable.
- `_gen_step_result_lemmas` emits `work_step_svc_exit`/`work_step_svc_write`
  under an `hx` binder for an `svc` word, selected by the static x16.

Measured: the gate job `reg-formal-ast-bridge-two-arg` passes, the two-arg
program and `def main(n: Int, m: Int): return n + m` both typecheck in Lean
(0 sorries in the generated file), and
`test_formal_call_proof_gen.TestTheStackFloorGuardReadsTheLimitInTheStartupStub`
is green again.

Landed as 574813206 (archive) and f03896fff (master): the x16-discriminating model (exit is `none`, write
continues at `pc + 4`), `work_step_svc` / `_exit` / `_write`, the svc step's right-hand side in the generator, no
`_step_ok` lemma for an svc word, and the termination obligation's comment and pin. The dylib test is PASS=23 FAIL=6,
the marker's count. Helper `_svc_static_x16` is on the archive (21b4a98cb), not yet called.

STILL OPEN: the dynamic-`svc` named hypothesis (design item 4) and the
`svc_write_assumed` slot; the dylib export paths already use their own
guarded-obligation route.  The default walk's static case is landed above:
static x16 is threaded at the application site, and a static write run
certificate carries the x0-reassignment rule.  A dynamic `svc` on a walked
path is still refused rather than guessed.

## Symptom (before 574813206)

On an overflowing input the Lean model fell through the overflow trap block and returned a value the real program never
produces. The machine stops at the exit `svc`; the model did not, because every `svc` was a no-op. The wrong spec was
admitted only as a `sorry`, and the teeth check could not reject it.

## What is in place (after 574813206 / f03896fff)

- `lib/ProofLib.lean`, the svc arm of `arm64_step`: x16 = 1 gives `none`; otherwise `some { s with pc := s.pc + 4 }`.
  The x0 return value of a write is not modelled.
- `lib/ProofLibSteps2.lean`: `work_step_svc` states the x16 `if`; `work_step_svc_exit` and `work_step_svc_write` are its
  corollaries.
- `formal/arm64_proof_gen.py`: the svc step's right-hand side at both sites is the same `if`. No `_step_ok` lemma is
  emitted for an svc word. The termination obligation's comment names the trap path.
- `formal/arm64_proof_gen.py::_svc_static_x16` (archive 21b4a98cb, master fd89c015b): reads the static x16 from the
  `movz` directly before an svc. Not called yet.
- `test_formal_dylib.py`: the termination pin is reversed (a trap halts, so termination is not a model fact). The
  no-hole check reads the Scaffold ledger.

Measured: the dylib test is PASS=23 FAIL=6, the marker's count. The six are the two wrong-spec teeth checks and four
contract checks on branchy exports, which are guarded obligations now.

Consequences of the model change (not bugs in themselves, but to know):
- `triple`'s termination (`_semantics_total`) is an obligation, not a theorem, because its overflow trap is an exit svc.
- The contract of every export with a trap path is a guarded obligation (`_spec` under `_pre`), not a proved fact.

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

Related: the overflow-guard wrong-spec fix (2026-11-12), which closed the soundness hole this doc's svc model underlies.
