# `arm64_step`'s `ADD` (shifted register) arm ignores `imm6`, so every `add Xd, Xn, Xm, lsl #3/#4` steps WRONG

**Area:** FORMAL (the arm64 machine model's shifted-register ADD arm).
**Status: OPEN, MEASURED on the CPU, and a SOUNDNESS defect — `arm64_step`
returns a state the machine never reached.** Found 2026-10-08 (`work/
formal231-docs`) while verifying the sibling `#imm12` fix (the arm that read the
12-bit immediate and dropped its `lsl #12`): the same class of omission, in a
different encoding.

This is the same bug as those two `WRONG`-not-`NOSTEP` defects — a decode that
reads the fields it knows and drops one it does not — except the field here is
the SHIFT AMOUNT of a register operand, at bits 15:10 (`imm6`), and it is
dropped by BOTH the register ADD and the register SUB arms.

## 1. What I ran, and what it printed

`tools/formal_model_fuzz.py`'s own harness (`assemble` / `run_native` /
`run_model` through `sweep`), one instruction per case on a hand-built state
(`x1 = x2 = 0x0102030405060708`), so the encoding comes from `as`:

```console
$ python3 tools/memslot.py --gb 8 --label fm -- python3 .tmp/min_repro.py
tally: Counter({'AGREE': 6, 'WRONG': 2})
FINDING (6, …, ['      x7   model=020406080a0c0e10 hardware=09121b242d363f48'])
FINDING (7, …, ['      x7   model=020406080a0c0e10 hardware=1122334455667788'])
```

cases 6 and 7 are `add x7, x1, x2, lsl #3` and `add x7, x1, x2, lsl #4`. The
model answers `x1 + x2` for both (there, two equal values), the hardware answers
`x1 + (x2 << 3)` and `x1 + (x2 << 4)`. The two encodings are
`encode_add_xd_xn_xm_lsl3(7,1,2) = 0x8b020c27` and `…_lsl4 = 0x8b021027`, whose
`imm6` fields (bits 15:10) are 3 and 4.

The first six cases — `adds x7,x1,x15`, `cmn x1,x15`, `add/sub #imm,lsl #12`
and the unshifted `add/sub #imm` — are `AGREE`, which is what the sibling fix
buys and what makes this a separate defect.

The same run through the mix its own generators feed
(`python3 tools/memslot.py --gb 8 --label fm -- python3 tools/formal_model_fuzz.py
--mix flagged --cases 200 --seed sweepB`) reports **AGREE 125 WRONG 75**, and
every reduced case is a `lsl #3`/`lsl #4` register add.

## 2. What I expected

`ADD Xd, Xn, Xm, shift` is `Xn + (Xm << shift)`. The model's arm reads `Xm`
(bits 16:20) and adds it unshifted.

## 3. What is wrong

`lib/ProofLib.lean`, the `0x8b000000` arm:

```lean
  else if (insn &&& 0xffe00000) = 0x8b000000 then
    -- ADD Xd, Xn, Xm (register, SHIFTED form): 0x8b000000
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s + arm64_reg xm s)
    some (arm64_set_reg rd s result)
```

The comment says "SHIFTED form" and the shift field `imm6` (bits 15:10) is never
read. The register `SUB` arm (`0xcb000000`) has the same omission; no lowering
emits a shifted `SUB` today, so only the ADD half is reachable, but the two
should be fixed together or the model is half-correct about one class.

**It is reachable in a real image.** `formal/arm64_codegen.py` emits
`encode_add_xd_xn_xm_lsl3` / `…_lsl4` at **38 sites** — list and dict element
addresses (`X5 = base + (index << 3)` and the dict-key pair's `<< 4`), the
key-slot and blob strides. Each is a real index computation, so a theorem over
any image that builds a list or a dict reasons about a state the machine never
reached (the `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §2 rule, one
layer down, in the model rather than the emitter).

## 4. The exact next step

**One reader for the shifted register operand, not two copies**, the same
argument the `#imm12` fix made (and the reason that fix is a shared
`arm64_ext_imm12`): a second `((insn >>> 10) &&& 0x3f)` written into one arm and
not the other is exactly how this defect happened.

1. `lib/ProofLib.lean`: a helper beside `arm64_ext_imm12`, e.g.
   `def arm64_shifted_reg (insn : UInt32) (s : Arm64State) (rm : Nat) : UInt64 :=
   arm64_reg rm s <<< UInt64.ofNat (((insn >>> 10) &&& 0x3f).toNat)`, and **both**
   the ADD and SUB shifted-register arms call it. `imm6` is bits 15:10 and is a
   6-bit shift count, so the operand is `Xm << imm6` (the arithmetic-shift
   variant the `S` bit selects is not modelled and no encoder here emits it, so
   the `<<<` is the whole of what is reachable).
2. `arm64_step_add_reg` and `work_step_add_reg` (and the SUB pair,
   `arm64_step_sub_reg` / `work_step_sub_reg`) re-stated with the shifted
   operand; the `¬` facts are unchanged (the masks do not move), and the
   `try dsimp; try rfl; try simp` closing tactic still applies.
3. `formal/arm64_proof_gen.py`: `_step_rhs` and `_step_rhs_generic` for idx 2
   (ADD register) and idx 3 (SUB register), which both drop the shift today.
4. CPU-vs-model rows in `test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`
   (`add x7, x1, x2, lsl #3` and `lsl #4`, plus an unshifted `add x7, x1, x2`
   so a fix that always shifted is caught), and a generator-source pin like
   `test_cmn_writes_its_destination_and_the_immediate_arms_scale`.
5. `tools/formal_model_fuzz.py`'s `flagged` mix already draws the shifted pair
   (`gen_flagged_alu` k == 2/3), so the anti-rot is the tool's own tally:
   `--mix flagged --cases 200 --seed sweepB` should go from `WRONG 75` to `0`.

## 5. Provenance

Measured by the arm64 model fuzzer after the `#imm12` fix landed, while
re-measuring that defect's own `sweepB` row. The `flagged` mix's `lsl #3/#4`
generators and the two encoders predate it; no run had drawn them against a
model fixed for the immediate forms, which is why the omission outlived the
campaign that found its two siblings.

## 6. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label fm -- python3 tools/formal_model_fuzz.py \
    --mix flagged --cases 200 --seed sweepB
# AGREE 125  WRONG 75  — every reduced case is `add Xd, Xn, Xm, lsl #3/#4`
```
