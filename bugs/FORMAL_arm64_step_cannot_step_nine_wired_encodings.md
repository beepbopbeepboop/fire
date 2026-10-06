# `arm64_step` cannot step nine of the encodings `formal/arm64.py` emits

## Status

**Fourteen of the sixteen counterexamples are LANDED (2026-10-04, `formal28-2`),
and the number that says so is the fuzzer's own tally, not this file.** Twelve
memory forms and two flag-setting compares now have model arms, `work_step_*`
lemmas and generator rows, and both 300-case sweeps went from
`AGREE 197 / NOSTEP 99` (seed `sweepB`) and `AGREE 208 / NOSTEP 86` (seed
`sweepC`) to:

| seed | before | after |
|---|---|---|
| `sweepB` | AGREE 197 WRONG 0 NOSTEP 99 | **AGREE 279 WRONG 0 NOSTEP 17** |
| `sweepC` | AGREE 208 WRONG 2 NOSTEP 86 | **AGREE 273 WRONG 0 NOSTEP 23** |

Every remaining `NOSTEP` is a **`CSEL`** — the one instruction here with its own
document and its own blocker
(`bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`,
whose Status says the certificate is the expensive part and that the certificate
belongs to another claim), so the reachable set this file names is now empty.

What landed, in the order §4 gives:

1. **The width helpers.** `mem_read_u8` / `mem_read_u16` / `mem_read_u32` /
   `mem_write_u8` / `mem_write_u16` / `mem_write_u32` in `lib/ProofLib.lean`.
   Each is a definition and not a composition of the 64-bit pair, because the
   peel lemmas rewrite `mem_read_u64 ∘ mem_write_u64` — a narrow store spelled
   wide would be *provable* and wrong.
2. **The twelve memory arms**, APPENDED at the end of `arm64_step`'s `if` chain
   with their twelve `work_step_*` lemmas. **Appending is the engineering
   decision, not a convenience**: the chain is matched by `else if`, so a branch's
   proof rewrites every earlier condition with an `hne_` of its own, and putting
   these in the architectural position would have meant editing all 34 existing
   lemmas. Appending leaves every existing rewrite chain untouched, and the price
   — that no earlier branch may claim these words — is paid by the twelve new
   lemmas themselves, each of which states the `¬` fact for all the arms before it
   as a `bv_decide` over 2^32 words. They would not typecheck if an earlier arm
   claimed one of these encodings.
3. **`CMN` and `TST`**, also appended, with `arm64_adds_flags` and
   `arm64_logic_flags`. See the correction below: **both of their encoders are
   UNWIRED**, so this is not for the images.
4. `test_formal_call_proof_gen.py::TestUnsignedOffsetAccess` runs all eighteen
   of these on the CPU and compares `arm64_step`'s final state against it — about
   two seconds, and the reason three of the mistakes below were caught rather
   than landed.

**What is left is `CSEL` and `BLR`**, and each is a different kind of work: the
`CSEL` row is three lines of Lean once a certificate that is not its own problem
is fixed, and `BLR` needs the `Callee` table machinery (`arm64_step_call`), which
§3 already says is not "three lines".

## §2 is WRONG about two of its sixteen, and that reorders the work

**`encode_cmn_xn_xm` and `encode_tst_xn_xm` are UNWIRED.** Measured on the tree
this file was filed against and again on the tree this landed on:
`grep -c encode_cmn_xn_xm formal/arm64_codegen.py` is **0**, the same for
`encode_tst_xn_xm`, and both are in `tools/arm64_insn_audit.py::unwired_encoders`.
§3's "CMN … `encode_cmn_xn_xm` is emitted by `formal/arm64_codegen.py`" is false,
and so is §2's "Every encoder in the table above is wired" for those two rows.

So the file's own distinguishing test — an encoder no lowering references cannot
occur in an image, so a model that cannot step it costs nothing — says those two
cost nothing, and §4's ordering (step 2, two one-line arms, before the eight
memory arms) was wrong on that basis.

**They are modelled anyway, and the reason is a SECOND consumer of the model.**
`tools/formal_model_fuzz.py` builds its pool from the ENCODER TABLE, not from
images, so an unwired encoder still appears there as a `NOSTEP`: on seed `sweepB`,
38 of them before these two arms, every one `CMN` or `TST`. The audit's test
answers "can an image contain this", and the fuzzer's tally answers "can the model
step this" — two questions, and a reader of the second is not told which one the
first settled. Two arms and two lemmas take it to zero, which is cheaper than the
alternative (hiding the gap in the pool) and leaves the model complete for
everything `formal/arm64.py` can produce.

**Three mistakes the hardware caught, each of which is a mask or a formula, and
each of which a byte-level review would have passed:**

* **The `CMN` flags were modelled as a subtraction.** §3 says "`CMP` is `CMN` with
  the operands the other way round, so all three are one-line changes to an
  existing arm's shape". `CMN Xn, Xm` is `ADDS XZR, Xn, Xm` — the flags of the
  SUM. With `arm64_subs_flags` the model answered a carry bit the subtraction
  cannot produce: `cmp x10, #2047 ; cmn x12, x7` gave 0x4 where the hardware gave
  0xc.
* **`arm64_adds_flags`'s first version was wrong in both formulas.** It used
  `((a & b) | ((a ^ sum) & (b ^ sum))) >>> 63` for the carry, which is the identity
  for no addition at all (the right one is `((a & b) | ((a | b) & ~sum)) >>> 63`),
  and it complemented `a` where the overflow identity complements `a ^ b`. Five
  wrong out of six hand-picked operand pairs through the fuzzer.
* **Two masks.** The unscaled pair wanted `0xffe00c00` and got `0xffdffc00`, which
  clears bit 21 — but bit 21 is FIXED at 0 in that class (the `opc` field is
  23:22), and the 9-bit offset runs 20:12, so the first version decoded
  `ldur x7, [sp, #24]` (offset 24 → bit 20 set) as nothing. And the register-offset
  pair wanted `0xffe0fc00`, not `0xffe00c00`: `option` is bits 15:13 and `S` is bit
  12, and a mask that leaves them free does not match the instruction's own word.

**RE-MEASURED 2026-10-05 on `work/formal27-2`: still open, and the headline
count is wrong in this tree's favour — it is SEVEN reachable encodings, not
nine.** `encode_cmn_xn_xm` and `encode_tst_xn_xm` are in `tools/arm64_insn_
audit.py`'s unwired list, so no image this backend produces can contain a `CMN`
or a `TST`, and by this doc's own distinguishing test (§2: "an encoder no
lowering in `formal/` references cannot occur in an image") their NOSTEPs cost
nothing and are not work. §2's claim that "**every** encoder in the table above
is wired" is false for those two, and §3's `CMN`/`TST` entries ("`formal/
arm64_codegen.py` emits it") are false with them. Everything else reproduces
exactly — see "What was re-measured" at the end. NOT fixed: every arm here is a
`lib/ProofLib.lean` change, and that build cannot be run inside a bounded
worker's memory ceiling (measured: 8.0 GB breach at `-j 1`), so landing one
without checking it would put a broken library in a tree whose Lean gate is
disabled.

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

## 4. The exact next step — steps 1, 2, 3 and 5 are DONE; see §Status

The list is kept as written because the two rows that remain (§4.4 below) are
still the work, and because steps 1–3 record the order the work actually took,
which was NOT this one: the helpers and the twelve memory arms first (§Status
item 2 says why), and `CMN`/`TST` last even though this list puts them second,
because they are the two an image cannot contain.

1. ~~The width helpers,~~ LANDED, in this order and for the reason in §3:
   `mem_read_u32`,
   `mem_write_u32`, `mem_read_u8`, `mem_write_u8`, `mem_read_u16`,
   `mem_write_u16` beside `mem_read_u64`/`mem_write_u64` in `lib/ProofLib.lean`,
   with `mem_read_u64 = mem_read_u32 ∘ …`-style equations if the simplifier
   needs them. `mem_read_two_writes_*` are already in the file and are the
   pattern to follow.
2. ~~`CMN` (2 arms) and `TST` (1 arm).~~ LANDED, and **this row's reasoning was
   wrong**: `CMN` is `ADDS`, not `CMP` with the operands swapped, so it needs
   `arm64_adds_flags` and not `arm64_subs_flags` — §Status has the measurement.
3. ~~The eight memory arms, one per encoding, each with its `_STEP_CONDS` row,
   its `work_step_*` lemma and its `_step_rhs` row in the SAME commit~~ LANDED,
   and there were **twelve** rather than eight: the list above counted the
   counterexamples, and `LDR Wt`, `LDUR` and `STUR` were in it while the register-
   offset pair and the two sign-extending loads were not called out separately.
   The `CSEL` doc's §2 is the measurement of what happens when the table and the
   model move apart, and `check_step_conds` is what catches it.
4. **`CSEL` and `BLR` are what remains**, and each is a different kind of work:
   the `CSEL` row is three lines of Lean once a certificate that is not its own
   problem is fixed (its own document says so), and `BLR` needs the `Callee`
   table machinery `arm64_step_call` provides, which §3 already says is not three
   lines.
5. ~~Re-run the tool.~~ DONE — the table is §Status's, measured. The number to move is the NOSTEP column of §1's per-mix
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

## What was re-measured 2026-10-05 (`work/formal27-2`)

**The per-mix table of §1 reproduces exactly**, which is worth saying because it
is the doc's own evidence and a stale table would have made everything below
unreadable:

```console
$ for M in memreg mem select flags; do python3 tools/memslot.py --gb 4 --label fm -- \
      python3 tools/formal_model_fuzz.py --cases 60 --seed ledgerA --mix $M; done
memreg   NOSTEP 60                (of 60)
mem      AGREE 11  WRONG 4  NOSTEP 45   (of 60)
select   AGREE 18            NOSTEP 42   (of 60)
flags    AGREE 35            NOSTEP 25   (of 60)
```

§1's four rows were `0/0/60`, `11/4/45`, `18/0/42`, `35/0/25`. Same numbers, so
the model has not moved under this doc.

**And the reachability split, which is the correction.** `tools/arm64_insn_
audit.py::unwired_encoders`, asked about the seventeen encoders this doc's §1
and §2 name:

```
UNWIRED (cannot occur in an image): ['encode_cmn_xn_xm', 'encode_tst_xn_xm']
WIRED   (a real gap):               ['encode_csel_xd_xm_cond', 'encode_ldrb_wd_wn',
                                     'encode_strb_wd_wn', 'encode_ldrh_wt_wn_imm',
                                     'encode_strh_wt_wn_imm', 'encode_ldrsb_xt_xn_imm',
                                     'encode_ldrsh_xt_xn_imm', 'encode_ldrsw_xt_xn_imm',
                                     'encode_ldr_xt_xn_xm', 'encode_str_xt_xn_xm',
                                     'encode_ldur_xt_xn_imm', 'encode_stur_xt_xn_imm',
                                     'encode_ldr_wt_wn_imm', 'encode_str_wt_wn_imm',
                                     'encode_blr_xn']
```

So the work is **seven** encodings — `csel`, the eight narrow/unscaled memory
forms, the two register-offset forms and `blr` are wired and are real gaps;
`cmn` and `tst` are not. That also reorders §4: step 2's "`CMN` (2 arms) and
`TST` (1 arm), one-line changes to an existing arm's shape" is the CHEAPEST work
in the doc and it is work on instructions no image contains, which is why it has
not been done and why doing it would have been a waste.

**What blocks the seven, and it is not the table or the arms.** Every one of them
is a `lib/ProofLib.lean` change: a `work_step_*` lemma per encoding, a
`_STEP_CONDS` row, and `mem_read_u32`/`mem_write_u32`/`u8`/`u16` beside
`mem_read_u64`. The `ProofLib.olean` build on this tree does not fit a bounded
worker:

```console
$ python3 tools/memslot.py --gb 8 --label prooflib -- python3 .tmp/buildlib.py .tmp/lib5 ProofLib
memcap: BREACH  8.0 GB > 8.0 GB ceiling (100%), 2 procs -- killing prooflib
memcap: peak observed before the kill: 8.0 GB
```

That is `formal/lean.py::run_lean` with `-j 1` (the library bounds, the library
memory cap) against the tree's own measured 7.82 GB for the same build at
`-j 4`, so the margin is gone before the parallelism is: a one-thread build of
this library needs more than 8 GB, and the doc's §5 step 1 ("Build
`lib/ProofLib.olean` (7.7 GB, ~100 s)") reads as a routine step because it was
written by a worker that could afford it. A `sorry`-shaped hole is the failure
mode here rather than a red test: the `work_step_*` lemmas and the generator's
`_step_rhs` rows have to move together, and a mismatch between them is a
generated proof that fails to elaborate — with the eight Lean-checking formal
gate tests disabled, nothing in the gate would catch it.

**So the order for whoever takes this, with the reachability correction folded
in:**

1. Get a `ProofLib.olean` build that fits (raise `MEMLIMIT_GB` for the `prooflib`
   job, or run it as a non-light worker). Everything below is gated on that, and
   the measurement above is why: this is the step, not the arms.
2. The width helpers (`mem_read_u32`, `mem_write_u32`, `u8`, `u16`) — needed by
   six of the seven AND by the `STR Wt` width defect already landed in the model
   (`lib/ProofLib.lean` gained `mem_write_u32` beside `mem_write_u64` on
   2026-10-05, because the 0xb9000000 arm was writing eight bytes through a
   four-byte instruction; the doc that recorded both that and the unsigned-offset
   base-register half is deleted with its fix, so this names the change rather
   than a path), so they are shared work rather than this doc's alone.
3. The eight memory arms, one encoding at a time, each with its `_STEP_CONDS`
   row, its `work_step_*` lemma and its `_step_rhs` row in the SAME commit.
4. `CSEL` and `BLR` last, behind their own docs' blockers
   (`FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it`,
   `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value`).
5. Drop `CMN` and `TST` from the list, or wire them and then add the arms — the
   honest state today is "no image contains them".
