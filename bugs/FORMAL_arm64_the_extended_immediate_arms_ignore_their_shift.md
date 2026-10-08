# The `ADD`/`SUB`/`CMP` `#imm12` arms read `imm12` and drop its `lsl #12`

**Status update 2026-10-07 (`work/formal125-docs`): FIXED IN SOURCE; the
`lib/ProofLib.lean` build is still owed to the integrator.** One helper,
`arm64_ext_imm12 (insn : UInt32) : Nat := (((insn >>> 10) &&& 0xfff).toNat) <<< (((insn >>> 22) &&& 0x3).toNat * 12)`,
is called by ALL FIVE `imm12` arms (ADD 32/64, SUB 32/64, CMP), so the shift
cannot be present in one and absent from another; `work_step_add_imm32/64`,
`work_step_sub_imm32/64` and `work_step_cmp_imm` state the shifted value, and
`_step_rhs`/`_step_rhs_generic` for indices 9-13 scale the literal the same way.
On the `sh = 2`/`sh = 3` decision §1 asks for: the `Nat` shift is total and the
model spells the architectural decode for all four; only `sh ∈ {0,1}` can be
assembled (the encoder is `encode_add_xd_xn_imm_sh`/`encode_sub_xd_xn_imm_sh`),
so no image reaches the reserved encodings and there is nothing to refuse. The
CPU-vs-model rows `add x12, x29, #1675, lsl #12`,
`sub x25, x14, #545, lsl #12` and — the anti-rot a helper that always shifted
would fail — an UNSHIFTED `add x12, x29, #1675` are in
`test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`. **The library rebuild
is the one step this worker may not run** (it breaches the 8 GB worker ceiling);
the model change was verified in isolation against the served `ProofLib.olean`,
where the scratch `arm64_step` + the five lemmas elaborate (rc=0, 1.4 GB) and
`#eval`s `x29 + (1675 << 12) = 6860805` and a wrapped `x14 - (545 << 12)`.

**Area:** FORMAL (the arm64 machine model's extended-immediate arms).
**Status: OPEN, MEASURED on the CPU, and a SOUNDNESS defect — `arm64_step`
returns a state the machine never reached.** Not fixed: `lib/ProofLib.lean`, and
that build peaks at **9.8 GB** measured with `formal/lean.py::ensure_library`'s
own invocation — over a bounded worker's 8 GB ceiling, under the tree's
`LIBRARY_MEMORY_MB = 12288`, so the blocker is memory alone and the library is
not broken. (The `-T 0` trap that measurement has is written up in
`bugs/FORMAL_contract_ladder_reach.md`.)

## 1. What I ran

The same harness as the sibling doc — `tools/formal_model_fuzz.py`'s own
`assemble` / `run_native` / `run_model`, so the encoding comes from `as`:

```console
$ python3 tools/memslot.py --gb 4 --label fm -- python3 .tmp/min_repro.py
sub x25, x14, #545, lsl #12              0xd14885d9
add x12, x29, #1675, lsl #12             0x915a2fac

case 2  sub x25, x14, #545, lsl #12   cpu=OK model=OK
   MISMATCH x25  cpu=ffffffffffddf000 model=fffffffffffffddf
case 3  add x12, x29, #1675, lsl #12  cpu=OK model=OK
   MISMATCH x12  cpu=000000000068b000 model=000000000000068b
```

`545 << 12 = 0x221000`, and `545 = 0x221`; the model answers with the
UNSHIFTED immediate (`…fffddf` is `x14 − 545`), the CPU with the shifted one.
`1675 << 12 = 0x68b000` against a model answer of `0x68b = 1675`. Both classes,
both directions, and the flags are right in both — so this is the immediate, not
the operation.

It is found by the fuzzer as `WRONG`, which is how it was found: the `flagged`
mix at `--seed ledgerA` reports `AGREE 8 WRONG 23 NOSTEP 9` of 40, and
`--minimise` reduces three of those to exactly these two instructions.

## 2. What is wrong

`lib/ProofLib.lean:2028-2069`, the four `imm12` arms:

```lean
  else if (insn &&& 0xff800000) = 0x91000000 then
    let rn    := ...
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    ...
        + UInt64.ofNat imm12)
```

`imm12` is read from bits 21:10 and the **`sh` field — bits 23:22 — is never
read**. On this class `sh` is not decoration: it selects `LSL #0`, `#12`,
`#24` or `#36`, and the mask `0xff800000` does not exclude it, so every
`lsl #12` immediate in an image is stepped as if it were unshifted.

The `sh` value is in the same word and in the same class, so this is a decode
omission rather than a missing capability: `((insn >>> 22) &&& 0x3)` is the
field and `imm12 <<< (12 * sh)` is the value.

**`sh == 2` (`lsl #24`) and `sh == 3` (`lsl #36`) can never be expressed by an
`imm12` plus a shift smaller than 12.** That is not a reason to skip them — it is
the reason the multiply-and-add form exists — but it does mean the fixed arm
below is the wrong shape for the whole class, and §4 says what the right shape
is.

## 3. Why it is reachable, and why it matters

`encode_add_xd_xn_imm12_lsl` and `encode_sub_xd_xn_imm` are both WIRED
(`tools/arm64_insn_audit.py::unwired_encoders` lists neither). The backend
reaches for these arms for ordinary arithmetic: `formal/arm64_codegen.py:3542`
and `:3576` both say "steps use SUB (ARM64 ADD imm12 is unsigned)" and
`:46` says a scaled `imm12` is "what makes it one scaled imm12 instruction",
i.e. `imm << 12` for a blob offset. So the shape that computes a large constant
offset is exactly the shape the model gets wrong, and `formal/arm64_codegen.py:38`
says the blob layout depends on it.

As with the sibling `CMN` defect, the fuzzer's `WRONG` bucket understates this: a
`WRONG` step means a theorem emitted over such an image reasons about a state
the machine never reached (`bugs/FORMAL_dylib_export_loops_and_frame_bounds.md`
§2, one layer down).

## 4. The exact next step

**One read, not four copies.** There are four `imm12` arms (ADD 32/64, SUB
32/64) plus the CMP arm, and each would need the same two lines, which is the
duplicate-implementation shape this project has been bitten by. So:

1. one helper beside the other `arm64_*` decode helpers in `lib/ProofLib.lean` —
   `arm64_ext_imm12 (insn : UInt64) : Nat := ((insn >>> 10) &&& 0xfff).toNat <<< (((insn >>> 22) &&& 0x3).toNat * 12)`
   — and **all five** arms call it, so the shift cannot be present in one and
   absent from another;
2. **decide what the class does for `sh = 2` and `sh = 3` BEFORE writing the
   helper**, because a `Nat` shift is total and would silently compute an
   immediate no instruction can encode. The honest options are to `Nat.mod` the
   result into `2^64` (what the hardware does, since `ADD Xd, Xn, #imm` with a
   12-bit `imm` shifted by 36 is architecturally a DIFFERENT instruction and
   `as` refuses to assemble it) or to refuse. Refusing is safer and is a
   generator-side decision, so this is the one step that needs a person;
3. a `work_step_*` lemma per arm stating the shifted value, plus the `¬` facts
   for every earlier arm — appended, not edited in place, per
   `bugs/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` §Status item 2;
4. `_STEP_CONDS` and `_step_rhs` rows in the SAME commit;
5. CPU-vs-model rows for `add x12, x29, #1675, lsl #12` and
   `sub x25, x14, #545, lsl #12` in `test_formal_call_proof_gen.py`, and — the
   anti-rot that matters — a row for an **unshifted** `imm12` too, since a
   helper that always shifts would pass the two rows above and fail that one.

## 5. Provenance

Found in the same sweep as
`bugs/FORMAL_arm64_the_cmn_arm_writes_no_destination_register.md`, while
re-measuring `bugs/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md`. That
doc's §1 counterexample list is a list of instructions the model cannot STEP
(`NOSTEP`); this is one it steps WRONGLY, which is a different bucket and is why
the sweep it names would not have found it.
## 6. Confirmed a second way, without the fuzzer (2026-10-05)

Same reason as the sibling document: `tools/formal_model_fuzz.py::run_model`
passes `heartbeats=0`, so its model side is not the invocation
`ensure_library` uses. One independent check, through `run_lean` with **no**
`heartbeats` override against the prebuilt `lib/ProofLib.olean`, on
`x29 = 5`, `x14 = 9`:

```
#eval (match arm64_step s0 (codeAt 0x915a2fac) with   -- ADD x12, x29, #1675, lsl #12
       | none => 999 | some s => s.x12.toNat)
1680                                 -- = 5 + 1675; the model used imm12 unshifted
                                     -- hardware: 5 + (1675 << 12) = 0x68b005

#eval (match arm64_step s0 (codeAt 0xd14885d9) with   -- SUB x25, x14, #545, lsl #12
       | none => 999 | some s => s.x25.toNat)
18446744073709551080                 -- 2^64 - 535; hardware: 9 - (545 << 12)
```

1680 is `x29 + 1675` exactly — the immediate with its shift simply absent — and
the two classes (ADD and SUB) fail identically, which is what a decode omission
in a shared shape looks like and is not what a wrong operation would look like.
