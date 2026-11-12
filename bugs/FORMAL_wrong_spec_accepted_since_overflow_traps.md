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
