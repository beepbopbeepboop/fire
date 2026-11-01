# The shifted-REGISTER arms read `Rn` and `Rm` and drop the shift, so `add xD, xN, xM, lsl #3` models as `xN + xM`

**Area:** FORMAL (the arm64 machine model's shifted-REGISTER data-processing
arms in `lib/ProofLib.lean`; the `0x8b000000` arm is the one an image reaches).
**Status: OPEN, MEASURED on the CPU, and it is a SOUNDNESS defect rather than an
incompleteness — `arm64_step` returns a state the machine never reached.** Not
fixed: every arm here is a `lib/ProofLib.lean` change and that build breaches a
bounded worker's 8 GB ceiling (the sibling measurement is
`bugs/formal/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md`'s build wall, and
the `#imm12` shift arm — the same class of change — is now FIXED by `5361903f`
with its doc deleted), so landing it without typechecking it would put a
`sorry`-shaped hole in the tree whose Lean gate is disabled. It is the third
"the model is LOUD and WRONG" defect, after the `CMN` destination-register one
(fixed, its doc deleted) and the `#imm12` shift one (fixed) — a bucket no
`NOSTEP` tally can see.

## What I ran, and what it printed

One instruction, through `tools/formal_model_fuzz.py`'s own harness
(`assemble` / `run_native` / `run_model`) so nothing here re-implements a
comparison the tool already owns, and the encoding comes from `as`:

```console
$ python3 tools/memslot.py --gb 8 --label fm -- python3 .tmp/rshift_repro.py
encoding: 0x8b021023
tally: {'WRONG': 1}
  2 instruction(s), nzcv=0x0
    cmp x0, #1
    add x3, x1, x2, lsl #4
      x3   model=0000000000000013 hardware=0000000000000040
memcap: done, peak 1.2 GB across up to 2 procs (ceiling 8.0 GB), child exit 0
```

`x1 = 0x10`, `x2 = 0x3`, so the hardware is `0x10 + (3 << 4) = 0x40` and the
model is `0x10 + 3 = 0x13`. `add x3, x1, x2, lsl #3` fails the same way (the
`lsl #4` form is the one above because `encode_add_xd_xn_xm_lsl4(3, 1, 2)` is
`0x8b021023`).

It is found by the fuzzer as `WRONG`, which is how it was found — the `flagged`
mix, which draws `gen_flagged_alu`'s scaled ALU forms:

```console
$ python3 tools/memslot.py --gb 8 --label fm -- python3 tools/formal_model_fuzz.py \
      --cases 200 --seed ledgerA --mix flagged --minimise 4
... : AGREE 133  WRONG 67  (of 200)
  case 7 reduces to:
    cmp x29, #8
    add x16, x5, x25, lsl #4
      x16  model=0000000600500000 hardware=0000000605000000
```

`0x605000000 − 0x600500000 = x25 * 15`, i.e. exactly the missing `<< 4`.

## What is wrong

`lib/ProofLib.lean`'s `0x8b000000` arm:

```lean
  else if (insn &&& 0xffe00000) = 0x8b000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s + arm64_reg xm s)
    some (arm64_set_reg rd s result)
```

This is ADD (shifted register), and on that class the two fields the shift lives
in are **bits 23:22 (`shift`: `00` LSL, `01` LSR, `10` ASR, `11` ROR) and bits
15:10 (`amount`)**, neither of which the mask `0xffe00000` excludes and neither
of which the body reads. So every nonzero shift is stepped as if it were
`LSL #0`: `add xD, xN, xM, lsl #3` computes `xN + xM`, and `lsr`/`asr`/`ror`
forms of the same class compute a plain add. `work_step_add_reg` in the same
file states the same unshifted right-hand side, and
`formal/arm64_proof_gen.py`'s `_step_rhs` index 2 mirrors it, so the two move
together — and a generated proof over such a word would be a theorem about an
instruction the machine does not have.

## Why it is reachable, and not theoretical

`encode_add_xd_xn_xm_lsl3` / `encode_add_xd_xn_xm_lsl4` are **wired** and
**heavily emitted**: `grep -c "asm.emit(encode_add_xd_xn_xm_lsl[34]"
formal/arm64_codegen.py` is **36**, and the sites are element-address and
key-slot arithmetic (`+ 8*i`, `+ 8*k*nL`, a dict's key slot, a list's stride) —
i.e. exactly the `add xD, xN, xM, lsl #3` form whose 8-byte stride an image
computes. `tools/arm64_insn_audit.py::unwired_encoders` lists neither, so the
generator's own "an encoder no lowering references cannot occur in an image"
test does not clear this one.

`bugs/formal/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` §3's prescription
("`CMN` is `CMP` with the operands the other way round, so all three are
one-line changes to an existing arm's SHAPE") is the same mistake one level over:
a shifted-register arm's SHAPE includes its shift, and the shape that was copied
was `LSL #0`.

## The class, and which of its members an image reaches

Every arm with mask `0xffe00000` in the shifted-register families ignores the
shift: index 2 `ADD` (`0x8b000000`), 3 `SUB` (`0xcb000000`), 6 `SUBS`/`CMP`
(`0xeb000000`), 7 `AND` (`0x8a000000`), 8 `EOR` (`0xca000000`), 25 `ORR`
(`0xaa000000`), 66 `ADDS`/`CMN` (`0xab000000`), 67 `ANDS`/`TST` (`0xea000000`).
The **ADD** one is the live defect: it is the only member this backend spells
with a nonzero shift (`encode_add_xd_xn_xm_lsl3/lsl4`; the others are only ever
emitted with shift 0, so they are latent rather than reachable). The two
pre-existing comments in the file that DO claim the shift matters — `ORN`'s mask
pins `imm6 = 0` and `shift = LSL` (`0xffe0fc00`), and one above the `ADDS` arm
names its word precisely because a mask that leaves `imm6` free "does not match
the instruction's own word" — are the same lesson arrived at twice for two arms
and not applied to the eight.

## Why the ledger did not already say so

`bugs/formal/FORMAL_model_fuzz_ledger.md` §2.1's per-mix table has no `flagged` row:
`gen_flagged_alu` is one of the two mixes added *after* that table was taken
("the two mixes that closed the last of the census's FUZZ gaps"), and the
`select`/`ext`/`alu` mixes that ARE in it do not draw a scaled register add. So
the ledger's `WRONG 0` is a statement about the mixes it ran and not about the
model, which is the reading its own §2 warns for.

## The exact next step

1. **One decode helper, not eight copies.** Beside the other `arm64_*` decode
   helpers in `lib/ProofLib.lean`, something of the shape
   `arm64_shifted (insn : UInt32) (x : UInt64) : UInt64` that reads
   `shift := (insn >>> 22) &&& 0x3` and `amount := (insn >>> 10) &&& 0x3f` and
   applies LSL/LSR/ASR/ROR (`<<<`, `>>>`, the sign-extending arithmetic shift
   already in the file at `arm64_asr`, and a rotate), so the eight arms call it
   and the shift cannot be present in one and absent from another.
2. The eight arms apply it to `Xm` (the shifted operand is `Rm`; `Rn` is not
   shifted), and `work_step_add_reg`/`sub_reg`/`cmp_reg`/`and`/`eor`/`orr`/
   `cmn`/`tst` restate their right-hand sides to match — appended edits within
   the existing bodies, per `FORMAL_arm64_step_cannot_step_nine_wired_
   encodings.md` §Status item 2's append-don't-edit rule for the arms.
3. `formal/arm64_proof_gen.py`'s `_step_rhs` for indices 2/3/6/7/8/25/66/67 in
   the SAME commit, or a generated proof over such a word fails to elaborate
   with the Lean gate disabled — the failure mode that doc names.
4. CPU-vs-model rows in `test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`
   for `add xD, xN, xM, lsl #3` and `lsl #4`, and — the anti-rot that matters — a
   row for an UNSHIFTED `add xD, xN, xM`, so a helper that always shifts fails
   the last one. The `#imm12` fix's three rows beside them are the shape.
5. The `lib/ProofLib.olean` rebuild is the integrator's (it breaches an 8 GB
   worker ceiling); the source change can be verified in isolation the way the
   sibling docs' were, by elaborating a scratch `arm64_step` that carries the
   edited arm against the served `ProofLib.olean` and `#eval`-ing the two words.

## Provenance

Found 2026-10-13 re-measuring `bugs/formal/FORMAL_arm64_step_cannot_step_nine_wired_
encodings.md` on this tree: that file's fuzzer tally of `WRONG 0` was taken
before the `flagged` mix landed, and the unchanged `NOSTEP` column it reports is
still right (`CSEL` and `BLR` remain the model's only refusals). It is the same
bucket as that file's §Status "the model is loud and wrong" row and is named
there.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 200 --seed ledgerA --mix flagged --minimise 4
```
