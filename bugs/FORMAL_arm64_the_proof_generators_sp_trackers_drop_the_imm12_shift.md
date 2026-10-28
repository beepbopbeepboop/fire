# FORMAL_arm64_the_proof_generators_sp_trackers_drop_the_imm12_shift: the model shifts, the generator does not, so `hcond` rewrites miss

**Area:** FORMAL — `formal/arm64_proof_gen.py`'s `sp`-tracking decoders, against
`lib/ProofLib.lean`'s `arm64_ext_imm12`. **Status: FIXED for the five byte-form
decoders (`a76dae35`, 2026-10-12, `work/formal315-docs`); the four
frame-analysis helpers that read the same bits with a `* 8` unit still drop the
shift and are left for their own measurement (below).** Filed 2026-10-12 while
running the narrow suites for
`FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md`. Not this branch's
regression: nothing here changed `formal/` or `lib/` before the fix, and the
failures reproduced on the base tree.

**What landed.** `_imm12_shifted(w)`, one reader mirroring `arm64_ext_imm12`
(`((w >> 10) & 0xfff) << (12 * ((w >> 22) & 0x1))`), called by `_step_rhs`
(consolidation), `_frame_ldp_addrs`, `_frame_read_addrs`, `_hcond_mem_rws` and
`_sp_stores`. Measured after: `test_formal_eval_eq_mojo_bridge.py`'s three
typechecks (`ifonly`/`elif3`/`condassign`) close, `test_formal_call_proof_gen.py`
goes 9 -> 8 red (the `sgt8` rewrite was the same shift), and
`test_formal_run.py` (1209/0), `test_formal_short_circuit_cond.py` (15 OK) and
`test_formal_proof_shape.py` (24 OK) are unmoved.

## What the fix exposed on the examples corpus

Two measurements worth recording, both through
`tools/formal_proof_census.py --remeasure` on `formal/examples`:

* **`ifonly` is now `proved`** (39.5 s; it was `lean-rejected` on the current
  tree with the same `Tactic rewrite failed` this doc's inline program had).
  The committed baseline still records `ifonly` as `proved` from 2026-10-05 —
  so the baseline PREDATES the stack-floor guard's `lsl #12` reservation, and
  this fix restores a row the guard had broken.
* **`count` admits 1 `sorry` more than the baseline** (still `lean-rejected`,
  now at a later `maximum recursion depth`), and `identity`'s CPU reads 4x the
  baseline — **but `identity` measures ~29.5 s CPU with and without this fix**,
  so that one is pre-existing drift in the committed baseline, not this change.
  `count`'s extra hole is this change: its `FrameOk` window now gets the correct
  131072-byte depth and the proof reaches the next obligation instead of
  stopping earlier.

**So the committed baseline is stale over a large part of the corpus and the
`formal-proof-census` re-seed is the integrator's** — this fix moves rows
toward their real verdict; it cannot turn a `proved` row red, because a proof
whose `sp` tracker names `sp − 32` while the model's state is `sp − 131072`
cannot close in the first place.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 test_formal_eval_eq_mojo_bridge.py
Ran 27 tests in 2.1s
FAILED (failures=4)
```

`TestBridgeTypechecks::test_bridge_typechecks_with_no_sorries` fails for
`ifonly`, `elif3` and `condassign`, and
`TestAConditionalExpressionIsAValue::test_a_spill_is_not_attributed_to_the_conditional_expression`
fails once. (The test file is registered in no bucket, which is why this red has
stood; `formal-run`/`formal-call-proofgen` do not exercise these three inline
programs.)

## What I saw

Every failure is the same tactic error (`ifonly` shown):

```
ifonly_proof.lean:3962:10: error: Tactic `rewrite` failed: Did not find an occurrence of the pattern
  mem_read_u64
    (mem_write_u64 (mem_write_u64 ?m.975 (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16).toNat ?m.988)
      (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16 + 8).toNat ?m.989)
    (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16).toNat
in the target expression
  ...
            (mem_write_u64 s_0.mem (s_0.sp - UInt64.ofNat 131072 - UInt64.ofNat 16).toNat (n + UInt64.ofNat 0))
            (s_0.sp - UInt64.ofNat 131072 - UInt64.ofNat 16 + 8).toNat s_0.x2)
          (s_0.sp - UInt64.ofNat 131072 - UInt64.ofNat 16).toNat)
```

The emitted `rw` is `_hcond_mem_rws`'s line
`formal/arm64_proof_gen.py:3962`:
`rw [mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) - UInt64.ofNat 16) _ _]`.
The pattern's address is `sp − 32 − 16`; the real state's is `sp − 131072 − 16`.

## Why: the model reads the `sh` field and the generator does not

`131072` is `32 << 12`: the prologue's frame reservation is
`sub sp, sp, #32, lsl #12`. `lib/ProofLib.lean`'s `arm64_step` now decodes that
with its one helper

```lean
def arm64_ext_imm12 (insn : UInt32) : Nat :=
  (((insn >>> 10) &&& 0xfff).toNat) <<< (12 * (((insn >>> 22) &&& 0x1).toNat))
```

The model-side fix is landed and its doc is deleted with it (`5361903f`).
`formal/arm64_proof_gen.py`'s `_step_rhs` mirrors it
(`:3409`/`:3415`), so an emitted STEP lemma states the shifted value — but the
`sp`-TRACKING decoders still read `(w >> 10) & 0xfff` and drop bits 23:22:

| site | line (pre-fix) | note |
|---|---|---|
| `_hcond_mem_rws` | `:4533` / `:4536` | tracks `sp` to place a condition block's spill reads — **this was the failing one** — FIXED |
| `_sp_stores` | `:4576` / `:4578` | tracks the caller's frame slots for `FrameOk` — FIXED |
| `_frame_ldp_addrs` | `:3996` / `:3999` | the same ADD/SUB-immediate arms — FIXED |
| `_frame_read_addrs` | `:4496` / `:4499` | the same — FIXED |
| `_step_rhs` | `:3409` / `:3415` | already shifted; now calls the helper — consolidation |
| `_frame_stack_depths`, `_frame_slot_accesses`, `_frame_store_depths`, `_frame_store_writes` | `((w >> 10) & 0xfff) * 8` | **OPEN** — these also drop the shift, but they scale the result by 8 as well; the unit is a separate question from the shift and needs a re-measurement of the method/export contracts that read them before they are touched |

So a `lsl #12` frame reservation was tracked as its unshifted immediate, the
addresses the rewrite names were wrong by `(imm << 12) − imm`, and the proof's
`rw` found no occurrence.

## The exact next step

**Done for the byte form (`a76dae35`).** What is left is the `* 8` half:

1. decide whether `_frame_stack_depths`, `_frame_slot_accesses`,
   `_frame_store_depths` and `_frame_store_writes` track `sp` in BYTES (then the
   `* 8` is wrong and the shift must be added) or in 8-byte SLOTS (then the `* 8`
   is right and only the shift is missing). Every one reads STP/LDP `imm7 * 8`
   as bytes in the same loop, which is the evidence for BYTES, but a method's
   contract is the only thing that reads them and no narrow suite has been shown
   to exercise an `lsl #12` ADD/SUB there;
2. if they are the byte form, call `_imm12_shifted(w)` and drop the `* 8`;
3. verify against the method/export contract suites (`test_formal_dylib.py`,
   `test_formal_cross_module.py`).

The literal `32` versus `131072` is the whole diagnosis; no Lean reasoning about
the model is needed to confirm it, and the proof's own address is the evidence.
