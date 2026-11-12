# FORMAL: a wrong spec is accepted by Lean since integer overflow traps went in

Found 2026-11-10 by the bisect of `test_formal_dylib.py`'s "a wrong spec is rejected, not believed".

## Symptom

The check builds `def triple(n): return n * 3`, generates the dylib proof with the WRONG spec `n * 5`, and asks
Lean to check it. It must be rejected (a counterexample). On `a2135f390` and later, Lean accepts it. Its proof text
has `sorry`s.

## Measured

- Good: `096dd6e55`. The generated proof has no `sorry`. Lean: `counterexample: n = 18446744073709551615`. Image: 60 bytes.
- Bad: `a2135f390` and master. The generated proof has the export's contract as `dylib_export_0_triple_spec ... := by sorry`
  ("a body with a branch is not one function of one state"). Lean accepts. Image: 513 bytes.
- In the bad image, `triple` contains conditional branches to `triple_ovf1_t` / `triple_ovf1_k` (offsets 0x40, 0x78),
  the integer overflow trap around the multiply.

## Cause

`20d8bdba1` ("formal: refuse every integer overflow the build can decide, on both backends", 2026-10-05) makes the
multiply in `triple` a checked operation with a branch to a trap. The export is therefore not straight-line.
`formal/arm64_proof_gen.py` only builds the contract for a straight-line body. A branchy body gets the spec as an
admitted `sorry`, so there is nothing for Lean to check, and the teeth check fails.

Ruled out: the float-repr helper (`a2135f390`'s other change). `triple` never prints a float, so no helper is in the
image. A change to the last export's extent for the helper did not help, and was reverted (see the branch history).

## Next step

Teach the export's control-flow walk to treat a branch whose target is an overflow trap (a `*_ovf*_t` label that never
returns normally) as an exit that cannot be taken on a non-overflowing input, so the normal path is straight-line and the
contract is proved again. Then the wrong multiplier must be rejected with a counterexample, and the right one accepted.
Also: an exported contract that is an admitted `sorry` must not pass the teeth check. Delete this doc in the commit that fixes it.

## Correction (2026-11-11): the soundness hole is the machine model's `svc`

The cause above is only half of it. The overflow trap block is `trap:` label, the write `svc`, the exit `svc`, then the
`ok:` label (`formal/arm64_codegen.py::_emit_int_overflow_trap_block`). In the Lean model, `arm64_step` steps every
`svc` as a no-op (`lib/ProofLib.lean`, the `0xD4000001` arm: "trap; modelled as a no-op step", proved by
`work_step_svc` in `lib/ProofLibSteps2.lean`). So on an overflowing input the model falls through to `ok:` and carries on
with a result the real program never produces, while the real program stops at the exit `svc`.

That makes the model unsound on every trap path, not only the one in `triple`. The generator's "body with a branch" refusal
is the honest response to the branch; the teeth check fails because the wrong spec is only admitted as a `sorry`.

Fix, in order:
1. `lib/ProofLib.lean`: `svc` with `x16 = 1` (Darwin exit) steps to `none`, so `runProg` cannot return a final state from
   a trap. `svc` with `x16 = 4` (write) stays a no-op.
2. `lib/ProofLibSteps2.lean`: `work_step_svc` split on `x16`; the `hne_*` facts in `ProofLibSteps6..8` are unaffected.
3. `formal/arm64_proof_gen.py`: the SVC row (`5433`) and `_is_svc` (`8381`) say which svc is which.
4. Then the guarded contract: a body whose only branches are overflow traps gets the non-overflow precondition and a
   proved normal path. Until then the teeth check stays an expected failure.

Exit handling, the structural gap that remains after the Lean split: `FORMAL_svc_exit_handling_incomplete.md`.

## Status (2026-11-12): steps 1-3 are on the branch; step 4 is the open work

Landed earlier as `f03896fff` (an ancestor of this branch): the `svc` arm of `arm64_step` is x16-discriminating
(`lib/ProofLib.lean` ~2651-2658), `work_step_svc` / `_exit` / `_write` (`lib/ProofLibSteps2.lean` ~340-402), the generator's
svc step RHS at both sites, and `_is_svc` (`formal/arm64_proof_gen.py` ~8383). Re-checked by reading, not assumed.

**Measured this round** (`python3 tools/memslot.py --gb 8 --label baseline-dylib -- python3 test_formal_dylib.py -v`):
`PASS=22 FAIL=6`, exit 1. (The companion doc says 23/6; that count is stale.) The two wrong-spec cases fail with the
same message: `lean ACCEPTED` the wrong spec, because the export's contract is an admitted `sorry` obligation. The other
four failures (`several exports, and one with no derivable spec`, `an export that binds a local still gets a proved
contract`, `a conditional value is not a branch`, `the last export's walk ignores the image tail`) were NOT inspected
this round; check their messages before assuming they share this root.

**Done when:** `test_formal_dylib.py`, case "a wrong spec is rejected, not believed" (and "a wrong spec on a multi-export
image is rejected") PASS, with the CONTROL (right spec) still accepted. Then delete this doc in that commit and run
`python3 tools/dangling_doc_refs.py --ratchet`.

### Why it is not a one-line fix

- `formal/arm64_proof_gen.py::_dylib_contract_proof` (~16190) returns `""` for any body with a branch anywhere but its end
  (its docstring, ~16225). `lib/Refine.lean:59` `Block` is a single `step : Instr` over one state, so a conditional branch
  has nothing to say. The caller then emits `_spec` as `sorry` (~16720-16752).
- The guarded form already exists: `Refine.export_result_spec_under pre` (`lib/Refine.lean` ~982). But the generator
  passes `pre` as an OPAQUE `{ident}_pre`. An opaque `pre` cannot make a wrong spec fail: Lean has no concrete
  non-overflow input to exhibit. So step 4 is not just "prove the normal path"; `pre` must become the concrete guard.
- The teeth test needs PARTIAL correctness only (`runProg ... = some s → s.x0 = spec n`), not termination. The exit
  `svc` makes termination an obligation (`_semantics_total`), and that obligation is NOT on the path this test checks.
- Counterexample arithmetic: for `n * 5` against the machine's `n * 3`, `n = 1` already differs (5 vs 3), and `pre 1`
  holds for any sane guard. So a concrete `pre` is satisfiable on the counterexample.

### Decisions (with the recommendation)

1. **Shape of a branchy body.** Recommended: keep `Block` straight-line and model each conditional branch to an overflow
   trap as a hypothesis on the NORMAL path (the branch is not taken). The block is the fall-through instruction sequence
   from `entry` to `func_end`, and each trap branch contributes `¬ cond_i` to `pre`. Alternative (a two-path `Block`) is
   more general and costs more Lean; not needed for the overflow traps this doc is about.
2. **What `pre` is.** Recommended: a CONCRETE predicate, computed from the machine's branch condition at the guard's
   state (the `arm64_step` flags after the `mul`/`umulh` pair on the prefix state, with `x0 = n`). It must be a Lean
   `def`, not `opaque`, and the emitter keeps `opaque` only when no concrete guard can be derived.
3. **Where it is proved.** Recommended: a new lemma in `lib/Refine.lean` next to `block_advance`: if `pre n` holds and
   the block's `BlockCert` holds, then on the fall-through path `runProg` agrees with the composed effect. Then
   `export_result_spec_under pre` is discharged from the spec's bitvector identity, the same `bv_decide` pattern the
   existing `hreg` uses.

### Implementation plan (ordered, exact)

1. `lib/Refine.lean`: add `Block.guardedAdvance` (fall-through correctness under a list of not-taken conditions). Prove it
   from `block_advance`. No `sorry`; the Scaffold ledger is the only place a hole may live.
2. `formal/arm64_proof_gen.py::_dylib_contract_proof` (~16190): accept a body whose interior branches are all BCONDs to a
   `*_ovf*_t` trap (recognised by `_trap_terminating` / `_is_trap_bl`, ~8422, ~8474). Collect each branch's condition
   as a Lean expression over the prefix state. Keep the refusal for any other interior branch.
3. `formal/arm64_proof_gen.py` (~16720-16752): when that works, emit `def {ident}_pre : UInt64 → Prop := fun n => ...`
   concretely, and prove `{ident}_spec` with `bv_decide` over the composed effect. Keep the `opaque` + `sorry` path only
   as the fallback for a body it cannot derive.
4. Do NOT touch the `svc` model or `work_step_svc*`: they are landed and correct (see the companion doc).
5. Termination (`_semantics_total`) stays an obligation. This round does not change it.

### Tests that prove it

- `test_formal_dylib.py`: "a wrong spec is rejected, not believed" and "a wrong spec on a multi-export image is rejected"
  must PASS. Their CONTROL (the right spec) must still be accepted.
- The pin in `test_formal_dylib.py` (~756-764) that `triple`'s termination is NOT proved must still hold.
- Run only `test_formal_dylib.py` under `tools/memslot.py --gb 8`. Do not run `make check`/`gate`.

### The guard, decoded (2026-11-12, measured)

`compile_formal_dylib(['teeth.mojo'], prove=False)` on `def triple(n): return n * 3` gives a 136-byte image; `triple` is its
first 0x88 bytes (entry offset 0). The words, decoded by hand from the raw image (llvm-objdump here will not take a raw
binary blob, so this was done by reading the encodings):

| off | word | instruction | role |
|---|---|---|---|
| 0x00-0x24 | | `stp x29,x30`; `mov x29,sp`; `stp x19,x20`; `mov x19,x0`; `sub sp,#0x20`; spill x0; `mov w0,#3`; `mov x1,x0`; reload x0,x2 | prologue; x0 = n, x1 = 3 |
| 0x28 | `9b417c02` | `smulh x2, x0, x1` | high 64 bits of the signed 128-bit product |
| 0x2c | `9b017c00` | `mul x0, x0, x1` | the result (low 64 bits) |
| 0x30 | `937ffc01` | `asr x1, x0, #63` | sign-fill of the low product |
| 0x34 | `ca010042` | `eor x2, x2, x1` | x2 = smulh XOR asr63(low) |
| 0x38 | `b5000042` | `cbnz x2, 0x40` | **the trap branch**: x2 != 0 means signed overflow |
| 0x3c | `1400000f` | `b 0x78` | **an interior unconditional jump** over the trap block, to `ok:` |
| 0x40-0x74 | | trap block: `adrp`/`add` the message, `movz` fd/len/`x16=4`, `svc`; `movz w0,#0`; `bl`; `sxtw`; `movz w0,#1`; `movz x16,#1`; `svc` | `_trap_terminating` shape |
| 0x78-0x84 | | `add sp,#0x20`; `ldp x19,x20`; `ldp x29,x30`; `ret` | `ok:` tail; x0 is the product |

So the normal path is `0x00..0x38` (fall through the not-taken `cbnz`), then the `b 0x78`, then `0x78..0x84`. Two facts
the next round needs:

1. **Two interior branches, not one.** The `cbnz` at 0x38 and the `b` at 0x3c are both interior. Step 2 of the plan must
   accept the `b` as a jump to the `ok:` block (the normal path continues there), not only the `cbnz` as a not-taken
   condition. A body whose only interior branches are the overflow `cbnz` and a jump into the same normal tail is the
   shape to accept; any other interior branch is still refused.
2. **The concrete guard is `pre`.** The not-taken condition at the `cbnz` is `x2 = 0`, i.e. with `n` the input and
   `k = 3`:

       pre n := (smulh n 3) ^^^ (asr63 (n * 3)) = 0

   where `smulh` is the high 64 bits of the signed 128-bit product and `asr63 p` is `0` or `0xFFFF_FFFF_FFFF_FFFF`
   by the sign of `p`. This is exactly "`n * 3` does not overflow as a signed 64-bit value", so `pre` is satisfiable on
   the counterexample (`n = 1`, `pre 1` holds, and `1 * 5 ≠ 1 * 3`), which is what the teeth test needs.

   The expression is a `def`, built from `n`, not `opaque`. The generator derives it from the `cbnz`'s operand chain
   (`smulh`/`asr`/`eor` at 0x28-0x34) and the multiplier, so the next round can emit it without re-decoding.

**Not verified in this round:** the Lean side (`arm64_step`'s `smulh`/`asr`/`eor`/`cbnz` arms and whether `bv_decide`
closes the composed block under `pre`). Those are the next round's first measurement. Only the decode above is measured.

### Known hazards from reading the code

- Using `opaque` for `pre` makes every obligation vacuous-looking and un-refutable. That is the failure this doc exists to
  fix, so the new `pre` must be concrete, and a test must show a wrong multiplier is refuted on a non-overflow input.
- `_is_svc` treats every `svc` as a bounded stop. The companion doc's item 4 is still open, so a trap block with a write
  `svc` inside it is not handled yet.

### Landed 2026-11-12: the normal-path reader (step 2, detection only; not wired)

`formal/arm64_proof_gen.py::_overflow_normal_path(words, entry, func_end)` reads the no-trap path of an export whose
interior branches are overflow guards. It walks `_cfg_blocks` and uses `_trap_terminating` for "trap", so it means
exactly what the rest of the generator means. It returns `(pcs, guards)`: `pcs` is every instruction the normal path
executes, in execution order, and `guards` is `(cbz_pc, trap_pc)` for each guard. It returns `None` for a branch whose
taken edge is not a trap, a `BL`, a jump into a trap, a loop, or a path that falls off the extent.

Measured on the real compiled image (`compile_formal_dylib(['teeth.mojo'], prove=False)`, `base_addr` 0x100000370,
entry 0x100000370): the walk returns 20 instructions, `0x370..0x3a8`, `0x3ac`, `0x3e8..0x3f4`, and one guard
`(0x3a8, 0x3b0)`. The CFG is `cbz` at 0x3a8 (taken 0x3b0, the trap), `b` at 0x3ac to 0x3e8, `ret` at 0x3e8. Covered by
`test_formal_call_proof_gen.py::TestOverflowGuardNormalPath` (3 tests: the fall-through path, a non-trap guard
target refused, a trap that does not end the run refused). Run under `memslot --gb 8`: 3 OK.

**Not landed, and this is still a FAIL:** `test_formal_dylib.py` is unchanged at PASS=22 FAIL=6. Nothing calls the
reader yet. `_dylib_contract_proof` still refuses any non-straight-line body. Remaining steps, in order:

1. Wire the reader into `_dylib_contract_proof`. The `pcs` list is the EXECUTED path, not `entry + 4*i`, so the
   contiguity checks (`entry + m*4 == func_end`, `pcs = [entry + i*4 ...]`) must read `pcs` from the reader instead.
2. `exitpc` and `noEarly`/`atExit` are stated at `func_end`, which is also the image end for the last export. The
   normal path leaves at `ret` (0x3e8..0x3f4), not at the image end. That is the design question the Lean side must
   answer, so it is the first decision for the next round (is the exit the `ret`'s address, or a second exit fact).
3. Resolve the guard `cbz` statically as not-taken under the concrete `pre` (the decoded `smulh`/`eor`/`asr63`
   expression), instead of as an `if`, so the composed `st_i` is one function of one state.
4. Then the teeth test. Until then the wrong spec is still accepted.

### Measured 2026-11-12 (round 3): the six failures are one root, and the reader is still not wired

- `test_formal_dylib.py` baseline unchanged: PASS=22 FAIL=6, exit 1 (`memslot --gb 8`, 64 s wall).
- The four failures the step-4 notes said were NOT inspected are the same root, not separate ones. Probe on the
  "conditional value" program's `csetval` export (`var b = not n; var m = n * 3; return m`): its body has the
  overflow guard `cbnz x2` at `0x3bc` (the step table gives it an `if arm64_reg 2 s ≠ 0` pc), so the emitter refuses
  the body on the trap branch. The `cset` at `0x390` is not the reason. The same trap is in every case that
  multiplies by 3, which is all six.
- CSEL is modelled in `lib/ProofLib.lean` (~2956). The test docstring in `test_a_conditional_value_is_not_a_branch`
  says it is not; that docstring is stale.
- The guard's operand chain is in the step table: `0x3a8` loads x0 from the stack, `0x3ac` `smulh x2,x0,x1`, `0x3b0`
  `mul x0,x0,x1`, `0x3b4` `asr x1,x0,#63`, `0x3b8` `eor x2,x2,x1`, `0x3bc` the guard. Every link has a model
  `arm64_step` arm (`smulh64` at ProofLib ~1054, `asr64`, `^^^`).

**Still open, and this round did not land code.** The remaining work is the design in "Implementation plan" and the
four "Remaining steps" above. The decision it has not made is how `Refine.BlockCert` quantifies over a guarded body:
it is stated for every state at the entry, and the guard is only sound under `pre`, so the cert must become
`∀ st, pre st → …`. Until that is decided the Lean statement cannot be written, and that is the next round's first
step.

### Landed 2026-11-12 (round 4): the guarded block certificate, and the decision it encodes

**Decision, made:** the guard is a concrete `def` over the ENTRY state `g : Arm64State → Prop`, and the block certificate is
guarded by it, not by a per-state `pre`. The composed prefix (`smulh`/`mul`/`asr`/`eor` up to the `cbnz`) is folded into
`g`, so `g st` is "the not-taken condition at the overflow guard, computed from `st`". A wrong multiplier is refutable
because `g` holds for `n = 1` (`1 * 3` does not overflow, and `1 * 5 ≠ 1 * 3`).

**Landed (infrastructure, not yet a fix for any test):** `lib/Refine.lean` now has, after `block_advance`:
- `structure GuardedBlockCert code b g`: `∀ st, st.pc = b.entry_pc → g st → arm64_runs code b.pcs.length st = some (b.step st)`.
- `theorem guarded_block_advance`: the same conclusion as `block_advance`, under `g st` as an extra hypothesis. Proof is
  `go_exit_block ...` applied to `hcert.runs st hpc hg`, identical to `block_advance`. No `sorry`.

Verified: `lib/Refine.olean` was rebuilt after the edit (lean `-o` does not write on error), and `test_formal_dylib.py`
(`memslot --gb 8`, peak 1.9 GB) is unchanged at PASS=22 FAIL=6, including "no module under lib/ admits a sorry or an admit".
Nothing calls the new lemma yet, so the six failures are unchanged.

**Next step, in order (the work is now in the emitter):**
1. `formal/arm64_proof_gen.py::_dylib_contract_proof`: take `pcs` and `guards` from `_overflow_normal_path` (not `entry + 4*i`).
   Keep the refusal for any body where the reader returns None.
2. Emit `def {ident}_guard : Arm64State → Prop := fun s => <the cbnz's operand, evaluated over the prefix state>`. The
   prefix is the composed `st_i` chain up to the `cbnz`, so this is `(S_k s).regs 2 = 0` in the model's own names, not a
   re-decoded expression. (Using the model's composition keeps `g` concrete and avoids a second decoder.)
3. Emit `theorem bodyCert : Refine.GuardedBlockCert dylib_code body {ident}_guard` and the guarded `_spec` obligation as
   `Refine.export_result_spec_under (fun n => {ident}_guard (start n))`, proved by `guarded_block_advance` plus `bv_decide`
   for the value. The unguarded `export_result_spec` stays for bodies with no guard.
4. The `exitpc` question from round 3 still applies: the normal path leaves at the `ret` (0x3e8..0x3f4), so `atExit`/
   `noEarly` must be stated at that `ret`'s exit, or as a second exit fact. Decide this in step 1, not later.
5. Quick test: `test_formal_dylib.py` "a wrong spec is rejected, not believed" and "a wrong spec on a multi-export image"
   PASS, with the right-spec CONTROL still accepted. Then delete this doc in that commit and run the ratchet.

**Not verified:** whether `bv_decide` closes the guarded value identity for `triple`. That is step 3's first measurement.

### Round 5 (2026-11-12): planning guide for the executed-path emitter (no fix landed)

**Measured this round:** `python3 tools/memslot.py --gb 8 --label quick-reader -- python3 -m pytest -q
test_formal_call_proof_gen.py -k TestOverflowGuardNormalPath` → 3 passed (0.49 s, peak 0.1 GB). The reader is
sound on its fixture. Nothing else was measured, so `test_formal_dylib.py` is still PASS=22 FAIL=6 by the
round-4 measurement.

**Why this round is a planning round:** the rest of the fix is a rewrite of `_dylib_contract_proof`'s core
(about 400 lines of Python plus new Lean), not a patch. Its design is below so the next round can start writing
code. Do not re-derive it.

**What `_dylib_contract_proof` assumes that a guarded body breaks.** Each of these is a literal in the emitter:

1. `m = (func_end - entry)//4` and `pcs = [entry + i*4]`: the normal path is not contiguous (0x3ac jumps to 0x3e8).
   Take `pcs, guards = _overflow_normal_path(words_full, entry, func_end)` instead. `words_full` is the image word
   table, not the `words[k0:k0+m]` slice.
2. `dylib_sr_{k0 + i}`: the per-instruction lemma index must be the word index of `pcs[i]`, i.e.
   `(pcs[i] - base) // 4`, not `k0 + i`.
3. `S{k}_pc` (`entry + 4k`) and `runsTo{k}` use `runs_cons_seq` only. A `B` in the path needs `runs_cons_jump`
   (`lib/ProofLib.lean` ~4136: `hjump : st'.pc ≠ st.pc`), and the pc after it is the jump target, not `pc + 4`.
4. The guard `CBNZ x2` at `pcs` index `j` (`guards[0][0]`): `arm64_step` answers `if … then some taken else some
   fall`. Under the guard the emitter resolves it to the fall-through. The guard is a Lean `def`:
   `def {ident}_guard (s : Arm64State) : Prop := arm64_reg 2 (S_j s) = 0` (not-taken ⟺ x2 = 0; `S_j` is the
   prefix chain, so the expression is the model's own, per round 4). This is the one place a new Lean lemma is
   needed: `guard_not_taken : {ident}_guard s → arm64_step (S_j s) code = some (fall-through state)`, proved from
   the `cbnz` arm of `arm64_step`. **That arm has not been read yet**; reading it is the first action.
5. The block is `Refine.GuardedBlockCert dylib_code body {ident}_guard` (`lib/Refine.lean` line 92), `body.pcs = pcs`
   (executed order), `body.step = S_m`. `guarded_block_advance` (line 100) already gives the advance under `g st`.
6. `pc_writes` and `_step_rhs`: the single allowed pc-moving step is the last one (`ret`). Extend it to allow a `B`
   at an interior index as well, provided the reader already validated it is a jump into the normal tail.

**Exit (the round-3 question), answered from the reader's output.** The reader returns the `RET` as the last path
instruction, and in both fixtures the `RET` is the export's final word. So `exportEnd = func_end` is still the exit,
and `atExit`/`noEarly` need no new fact. **Confirm once on the real image** before relying on it: print
`func_end` and `words[func_end - 4]` for `compile_formal_dylib(['teeth.mojo'], prove=False)`. If the last word is
not the `RET`, the second exit fact from round 3 is needed and this guide is wrong there.

**Order of work for the next round (each step has a measurement before the next):**
1. Read `arm64_step`'s `CBNZ` arm (`lib/ProofLib.lean`), and write `guard_not_taken` in `lib/Refine.lean` or
   `lib/ProofLibSteps*.lean` (whichever already holds the `cbz` lemmas). Build it alone with `lean -o` and check it
   has no `sorry`.
2. Measure `bv_decide` on the value identity alone, outside the generator: `∀ n, {ident}_guard (start n) →
   arm64_reg 0 (S_m (start n)) = n * 3`, written by hand for `triple`. If `bv_decide` cannot close it, that is the
   blocker, and the round ends PARTIAL with that measurement in the doc. Do not start the emitter until this closes.
3. Emitter: items 1-6 above, behind the reader's `None` (keep the refusal for anything else). Add a unit test in
   `test_formal_call_proof_gen.py` (next to `TestOverflowGuardNormalPath`) that `_dylib_contract_proof` on the
   guarded fixture returns a non-empty contract whose `_guard` def contains the expected `= 0`, and that the same
   fixture with a non-trap guard target still returns `""`.
4. `test_formal_dylib.py`: the two wrong-spec cases must now FAIL in Lean with a counterexample (the `n*5` spec is
   refuted at n = 1, which satisfies the guard), and the right-spec CONTROL must still be accepted.

**Quick tests for the next round:** `test_formal_call_proof_gen.py -k TestOverflowGuardNormalPath` (0.5 s) and the
new emitter test; then `test_formal_dylib.py` once, as the Done-when test. Nothing else.

### Landed 2026-11-12 (round 6): step 1 of the round-5 guide, the not-taken CBNZ lemma

- `lib/ProofLibSteps8.lean`: `cbnz_not_taken` (after `work_step_cbnz`). If `arm64_reg rn s = 0`, then `arm64_step s code =
  some { s with pc := s.pc + 4 }`. Proved from `work_step_cbnz` plus one `if_neg`. Axioms: the standard set plus the
  `bv_decide` ones that the `work_step_*` lemmas already carry; no `sorry`.
- `test_formal_call_proof_gen.py::TestCbnzNotTakenLemma`: a Lean-checked probe that uses the lemma, asserting ok and zero
  sorries. It passes (`-k "TestCbnzNotTakenLemma or TestOverflowGuardNormalPath"`: 4 passed, peak 1.3 GB). I did not rebuild
  the tree without the lemma to watch the probe fail first; the pre-lemma failure is `unknown identifier`.
- Lean build note: `ensure_library(find_lean('.'), 'lib')` (formal/lean.py) builds the oleans in ~60 s from a cold tree.
  `LEAN_PATH=lib lean -o ... lib/ProofLibSteps8.lean` on its own fails with `unknown module prefix 'ProofLib'`.

**Not landed, and nothing calls the lemma yet.** `test_formal_dylib.py` is unchanged by this round and the two wrong-spec
cases still fail. Round 5's step 2 is still first: measure `bv_decide` on the hand-written value identity for `triple`,
`∀ n, {ident}_guard (start n) → arm64_reg 0 (S_m (start n)) = n * 3`, before the emitter is touched.

### Landed 2026-11-12 (round 7): the round-5 blocker decision is measured; `bv_decide` is not needed for the value

- **Measured:** the normal path of `triple` (the 20 executed instructions, guard resolved not-taken, `T_{i+1} s = body_i (T_i s)`
  from the generator's own `_step_rhs` bodies, on the REAL image from `compile_formal_dylib(prove=False)`) closes
  `arm64_reg 0 (T20 (start n)) = n * 3` with `simp +decide only [...]` then `simp [mem_read_after_write_u64, ...]`. No `bv_decide`:
  a `bv_decide` line after it errors "No goals". The stack round trip (`stp`/`ldp` at ground addresses, `sp` 0xfffffffffffffff0 - 16
  and `- 131072`) is decided by the library's read-after-write lemmas. Probe: `.tmp/probe/mkprobe.py` (scratch, not committed).
- **Landed as coverage:** `test_formal_call_proof_gen.py::TestGuardedValueIdentity` checks exactly that chain through Lean with no
  `sorry` (5 guard/value tests pass, `-k "TestGuardedValueIdentity or TestOverflowGuardNormalPath or TestCbnzNotTakenLemma"`,
  12 s, peak 1.7 GB). It pins that the emitter's value identity is decidable. It does NOT yet prove a wrong multiplier is refuted, and it
  is not a fail-before test: nothing in the emitter changed.
- **So round 5's step 2 is closed:** the value is not the blocker. What remains is step 1 (wire the reader into
  `_dylib_contract_proof`, with `pcs` executed-order, `B` via `runs_cons_jump`, `_guard` def, `GuardedBlockCert`) and step 3
  (`exportEnd`/`atExit` at the `ret`, which is the last word of the export, `func_end - 4`, so `atExit` at `func_end` is still the exit
  only if the RET's target is the caller; decide it in that round). `test_formal_dylib.py` is still PASS=22 FAIL=6.
- Lean note: the generator's preamble contains a `sorry` on `_semantics_total` (an obligation by design), so the probe cuts the preamble
  before it. Do not paste the preamble into a test that asserts zero sorries.
