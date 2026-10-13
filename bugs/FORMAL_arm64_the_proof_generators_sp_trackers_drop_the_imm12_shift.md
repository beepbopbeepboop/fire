# FORMAL_arm64_the_proof_generators_sp_trackers_drop_the_imm12_shift: the model shifts, the generator does not, so `hcond` rewrites miss

**Area:** FORMAL — `formal/arm64_proof_gen.py`'s `sp`-tracking decoders, against
`lib/ProofLib.lean`'s `arm64_ext_imm12`. **Status: OPEN, filed 2026-10-12 on
`work/formal315-docs` while running the narrow suites for
`FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md`.** Not this branch's
regression: nothing here changed `formal/` or `lib/`, and the failures reproduce
on the base tree.

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

(`bugs/FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md` is the
model-side fix, landed). `formal/arm64_proof_gen.py`'s `_step_rhs` mirrors it
(`:3409`/`:3415`), so an emitted STEP lemma states the shifted value — but the
`sp`-TRACKING decoders still read `(w >> 10) & 0xfff` and drop bits 23:22:

| site | line | note |
|---|---|---|
| `_hcond_mem_rws` | `:4533` / `:4536` | tracks `sp` to place a condition block's spill reads — **this is the failing one** |
| `_sp_stores` | `:4576` / `:4578` | tracks the caller's frame slots for `FrameOk` |
| `_frame_...`/sp-walk helper | `:3996` / `:3999` | the same ADD/SUB-immediate arms |
| sp-walk helper | `:4496` / `:4499` | the same |
| `:9517` / `:9520`, `:11637` | | **different units** (`((w >> 10) & 0xfff) * 8`): decide whether these are the byte form or a slot form before touching them |

So a `lsl #12` frame reservation is tracked as its unshifted immediate, the
addresses the rewrite names are wrong by `(imm << 12) − imm`, and the proof's
`rw` finds no occurrence.

## The exact next step

**One read, not six copies** — the shape
`FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md` §4 prescribes
for the model:

1. one Python helper beside the other decode helpers, mirroring
   `arm64_ext_imm12` exactly (`& 0x1`, the model's own reading of `sh`), and call
   it at `:3996`, `:4496`, `:4533`, `:4576` (the four byte-form sites);
2. audit `:9517`/`:9520` and `:11637` for the `* 8` unit and fix them the same
   way **only if** they are the byte form;
3. verify with `test_formal_eval_eq_mojo_bridge.py` (the three programs should
   typecheck) and re-run `test_formal_call_proof_gen.py` to check the `mod_by_var`
   / `same_image_leaf` reds
   (`bugs/FORMAL_call_proofgen_reds_after_the_arm64_model_merge.md`) do not get
   worse — they are the same `lsl #12` frame shape at the STEP-lemma layer.

The literal `32` versus `131072` is the whole diagnosis; no Lean reasoning about
the model is needed to confirm it, and the proof's own address is the evidence.
