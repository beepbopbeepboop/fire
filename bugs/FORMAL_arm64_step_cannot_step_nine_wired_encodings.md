# `arm64_step` cannot step nine of the encodings `formal/arm64.py` emits

## Status

OPEN, and NEW — found 2026-10-04 by `tools/formal_model_fuzz.py`, which runs a
generated instruction on the CPU and the same bytes through `arm64_step` and
compares the state. It is the **second** class of finding that tool produces
(`WRONG` is the first), and it is the worse one: a wrong answer is a false
theorem about the instruction, while a refusal is a proof about NOTHING.

**Step 1's first half has LANDED (2026-10-04, `formal28-2`), with a measurement
attached.** `lib/ProofLib.lean` has `mem_write_u32` — the four-byte write beside
`mem_write_u64` — and the `STR Wt` arm (0xB9000000) uses it, because `STR Wt` is
four bytes wide and the arm wrote eight: the four bytes above the stored word
were clobbered in the model and left alone by the hardware (seed `sweepC`, case
123). §3's last paragraph is therefore done: the `STR Wt` defect that was "already
landed as well" is closed, and what remains of step 1 is the NARROWER widths
(`mem_read_u8`/`mem_write_u8`, `mem_read_u16`/`mem_write_u16`, and
`mem_read_u32` for the narrow-width loads) plus the two named in §4 step 1 that
no arm uses yet. `mem_write_u32`'s docstring says why it is a definition and not
a composition of `mem_write_u64`: the peel lemmas (`mem_read_after_write_u64`,
the `FrameOk` window family) rewrite `mem_read_u64 ∘ mem_write_u64`, so a 32-bit
store spelled as a 64-bit write would be *provable* and wrong.

**The base-register half of the same family is also landed**, and it is not in
this document because it was a separate bug
(`ldr x0, [sp, #32]` modelled as a load from address 32): the three
unsigned-offset arms now read `Rn` through `arm64_reg_or_sp`, and
`test_formal_call_proof_gen.py::TestUnsignedOffsetAccess` runs those three
instructions on the CPU. That is the shape of test this document's nine
encodings want, and it is the reason step 3 below has a template rather than
being open-ended.

Every case below is `NOSTEP`: `arm64_step` answered `none`, the CPU ran the
instruction, and the two disagreed in the only way a step function can disagree
with a machine that has an instruction.

## 1. What was run, and what it printed

```
$ python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
      --cases 300 --seed sweepB
arm64 model vs hardware: AGREE 196  WRONG 1  NOSTEP 99  (of 296)
```

and, per mix, 60 cases each (seed `ledgerA`) — the two rows that matter are the
ones that cannot agree at all:

| mix | AGREE | WRONG | NOSTEP | what the NOSTEPs are |
|---|---|---|---|---|
| `memreg` | 0 | 0 | 60 | the register-offset load and store |
| `mem` | 11 | 4 | 45 | the narrow-width and unscaled accesses |
| `select` | 18 | 0 | 42 | `csel`, `cmn` |
| `flags` | 35 | 0 | 25 | `cmn` |

One-instruction counterexamples, each reduced by `--minimise`:

| instruction | encoding | the model's answer |
|---|---|---|
| `cmn x0, x3` | `0xab0003e0` | `none` |
| `csel x1, x5, x1, lt` | `0x9a851420` | `none` |
| `ldrb w27, [sp, #27]` | `0x39406b7b` | `none` |
| `strb w10, [x9, #38]` | `0x390b4a2a` | `none` |
| `ldrh w4, [x3, #8]` | `0x79418464` | `none` |
| `strh w20, [x9, #6]` | `0x79013134` | `none` |
| `ldrsb x29, [x9, #11]` | `0x398091bd` | `none` |
| `ldrsh x0, [x17, #28]` | `0x798e3800` | `none` |
| `ldrsw x25, [x9, #24]` | `0xb9806919` | `none` |
| `ldr x29, [x17, x9]` | `0xf8693b9d` | `none` |
| `str x29, [x17, x9]` | `0xf8293b9d` | `none` |
| `ldur x4, [x3, #-8]` | `0xf85f80c4` | `none` |
| `stur x4, [x3, #-8]` | `0xf81f80c4` | `none` |
| `tst x2, x3` | `0xea020020` | `none` |
| `ldr w4, [x3, #8]` | `0xb9401844` | `none` |
| `str w4, [x3, #8]` | `0xb9001844` | `none` |
| `blr x16` | `0xd63f0200` | `none` |

That is **nine distinct ENCODINGS** (the sixteen rows are the counterexamples;
`cmn`, `csel`, `tst` and `cmn`'s immediate form are four encodings between them).

## 2. Why each one is a gap and not a decision

The distinguishing test is `tools/arm64_insn_audit.py::unwired_encoders`: an
encoder no lowering in `formal/` references cannot occur in an image, so a model
that cannot step it costs nothing. **Every encoder in the table above is wired.**

```
$ python3 -c "import importlib.util as u; s=u.spec_from_file_location('a',
    'tools/arm64_insn_audit.py'); m=u.module_from_spec(s); s.loader.exec_module(m);
    print([n for n in ('encode_cmn_xn_xm','encode_csel_xd_xm_cond','encode_tst_xn_xm',
    'encode_ldrb_wd_wn','encode_strb_wd_wn','encode_ldrh_wt_wn_imm','encode_strh_wt_wn_imm',
    'encode_ldrsb_xt_xn_imm','encode_ldrsh_xt_xn_imm','encode_ldrsw_xt_xn_imm',
    'encode_ldr_xt_xn_xm','encode_str_xt_xn_xm','encode_ldur_xt_xn_imm',
    'encode_stur_xt_xn_imm','encode_ldr_wt_wn_imm','encode_str_wt_wn_imm',
    'encode_blr_xn') if n not in m.unwired_encoders()])"
['encode_cmn_xn_xm', 'encode_csel_xd_xm_cond', 'encode_tst_xn_xm',
 'encode_ldrb_wd_wn', 'encode_strb_wd_wn', 'encode_ldrh_wt_wn_imm',
 'encode_strh_wt_wn_imm', 'encode_ldrsb_xt_xn_imm', 'encode_ldrsh_xt_xn_imm',
 'encode_ldrsw_xt_xn_imm', 'encode_ldr_xt_xn_xm', 'encode_str_xt_xn_xm',
 'encode_ldur_xt_xn_imm', 'encode_stur_xt_xn_imm', 'encode_ldr_wt_wn_imm',
 'encode_str_wt_wn_imm', 'encode_blr_xn']
```

## 3. What it costs, per encoding

* **`CMN` (both forms)** — the model has `CMP` (0xeb000000, 0xf1000000) and `CMP`
  is `CMN` with the operands the other way round, so one arm each fixes both.
  `encode_cmn_xn_xm` is emitted by `formal/arm64_codegen.py`.
* **`TST`** — `ANDS XZR, Xn, Xm`, the same shape as the CMP arm with a logical
  op. One arm. Note the subtlety: `arm64_step`'s `AND (shifted register)` arm is
  0x8a000000, which is a DIFFERENT word from TST's 0xea000000 (the logical
  immediate group), so this is an addition and not an alias.
* **`CSEL`** — the row `_STEP_CONDS` had and then lost; see
  `bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`,
  whose §4 already costs this at three Lean lines plus a `work_step_csel`, and
  whose Status says the certificate is the expensive part. That doc's ordering
  still stands and this one does not change it.
* **The narrow-width and unscaled accesses** (`LDRB`/`STRB`, `LDRH`/`STRH`,
  `LDRSB`, `LDRSH`, `LDRSW`, `LDR Wt`, `STR Wt`, `LDUR`, `STUR`) — one arm
  each, and each needs a `mem_write`/`mem_read` at its own WIDTH: `mem_read_u64`
  exists and there is no `mem_read_u32`, and `mem_write_u64` writes eight bytes,
  which is wrong for every narrow store (the model's `STR Wt` arm at 0xb9000000
  ALREADY has that defect — it writes eight bytes of a four-byte store — so the
  width helpers are needed for a bug that is already landed as well as for the
  nine that are not).
* **`LDR`/`STR` with a register offset** — one arm each, and they are the form a
  list blob past 32760 bytes needs
  (`encode_ldr_xt_xn_xm`'s own docstring), so the reachability is not
  theoretical.
* **`BLR`** — the call through a function value, which
  `bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
  says a lowering emits. It needs the `Callee` table machinery
  (`arm64_step_call`), not just a decode arm, so it is the one row here that is
  not "three lines".

## 4. The exact next step

1. The width helpers, in this order and for the reason in §3: `mem_read_u32`,
   `mem_write_u32`, `mem_read_u8`, `mem_write_u8`, `mem_read_u16`,
   `mem_write_u16` beside `mem_read_u64`/`mem_write_u64` in `lib/ProofLib.lean`,
   with `mem_read_u64 = mem_read_u32 ∘ …`-style equations if the simplifier
   needs them. `mem_read_two_writes_*` are already in the file and are the
   pattern to follow.
2. `CMN` (2 arms) and `TST` (1 arm). `CMP` is `arm64_subs_flags (arm64_reg xm
   s) (arm64_reg rn s)` with the operands swapped, so all three are one-line
   changes to an existing arm's shape.
3. The eight memory arms, one per encoding, each with its `_STEP_CONDS` row,
   its `work_step_*` lemma and its `_step_rhs` row in the SAME commit — the
   `CSEL` doc's §2 is the measurement of what happens when the table and the
   model move apart, and `check_step_conds` is what catches it.
4. `CSEL` and `BLR` last, and only after their own docs' blockers.
5. Re-run the tool. The number to move is the NOSTEP column of §1's per-mix
   table, and it should be measured rather than asserted:
   `python3 tools/formal_model_fuzz.py --cases 300 --seed sweepB`.
6. **The harness's own coverage note.** `tools/formal_model_fuzz.py` puts a
   refusal in its own bucket precisely so that this doc's table and the tool's
   tally cannot drift apart; when an arm lands, the row moves because the tool
   says so, not because this file was edited.

## 5. Why nothing else caught this

`formal/arm64_proof_gen.py::check_step_conds` compares the model's branch
CONDITIONS with `_STEP_CONDS`. It passes, because `_STEP_CONDS` and the model
agree — both omit these encodings. `_step_branch_index` returns `None` for an
unmodelled word, and the generator's "the model takes no step here" is then
*true*. `bugs/FORMAL_fuzz_ledger.md` §2's rows are PROGRAM-level: a generated
program that reaches one of these instructions is proved by a run certificate
that cannot be built, so the program is refused — which is a loud failure, but
only for a program that reaches it, and the examples here mostly do not.

The gap is therefore not "the model is wrong". It is "the model is silent, and
silence is indistinguishable from correctness until something that can execute
an instruction asks".

## 6. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 300 --seed sweepB
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 60 --seed ledgerA --mix mem --mix memreg --mix flags --mix select
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 300 --seed sweepB --minimise 4
python3 -c "import importlib.util as u; s=u.spec_from_file_location('a',
    'tools/arm64_insn_audit.py'); m=u.module_from_spec(s); s.loader.exec_module(m);
    print(m.unwired_encoders())"
```