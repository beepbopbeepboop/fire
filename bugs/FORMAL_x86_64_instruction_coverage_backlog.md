# FORMAL_x86_64_instruction_coverage_backlog: the x86-64 half of the ISA census, form by form

**Found 2026-10-05 by `tools/formal_isa_census.py`**, the instruction-coverage
census, which prints the matrix for BOTH backends. arm64 is closed: every one
of its 77 emitted forms has a model arm, a fuzz case and an `as` differential,
with the exceptions named in `formal_isa_census.HARNESS_LIMITS` (eight, each a
property of the harness) and `.BACKLOG` (twelve, each with its own doc). This
file is the x86-64 answer, and it is **not** closed: 18 of the 85 emitted forms
have no fuzz case, no model sample, or no decoder arm.

## Status 2026-10-06 (`work/x86-coverage-endtoend`): SHAPE 1 IS DONE — all nine SSE2 forms, executed and compared against the CPU

This host can now RUN x86-64 Mach-O images (Rosetta 2), so each row was closed
all the way rather than only modelled: a decoder arm, a model arm in
`lib/X86.lean`, a `samples()` row, a `test_x86_64_decode.py` row and a
fuzz-pool entry, and then `formal/x86_64_model_fuzz.py --census` compares the
model's XMM file and flags against the hardware. **`addsd`, `subsd`, `mulsd`,
`divsd`, `ucomisd`, `xorpd`, `movq_r64_xmm`, `cvtsi2sd` and `cvttsd2si` are all
`yes yes yes` in the census now**, and every one AGREE against the CPU.

The compare is the one the doc predicted would decide the other eight, and it
did — but the defects it found were in the shared SEMANTICS, not in the
per-instruction arms:

| bug | what it was | found by |
|---|---|---|
| `lib/IEEE754.lean::key` flipped only the SIGN BIT | so two nonzero NEGATIVES ordered by MAGNITUDE, i.e. backwards: `-0.001 < -1e-118` was reported `false`. The standard transform flips ALL bits for a negative. A theorem pinned the two zeros and nothing pinned a nonzero negative | `ucomisd xmm3, xmm1` with xmm3 a tiny negative and xmm1 ~ -0.001: model CF=1, CPU CF=0 |
| `lib/IEEE754.lean::comparable` excluded INFINITIES | `!isNaN b && !isInf b`, so every ordering reading was `false` for a `±inf` operand and `1.0 < +inf` disagreed with `UCOMISD` on CF. Its own docstring already said an infinity IS ordered | the same census, on an infinite operand |

Both are fixed and pinned by new `native_decide` theorems
(`negative_values_order_by_value_not_by_magnitude`, `an_infinity_is_ordered`).

`cvttsd2si` is the one that needed a total function and not an arm: Lean's
`Float` has no `Int` conversion and `ToIntBits` is a `Prop`, so
`x86_cvttsd` is the bit-level truncate-toward-zero over all 2^64 patterns,
including the integer indefinite `0x8000000000000000` for NaN, infinity and
out-of-range. A random XMM mostly drives it out of range, so the fuzz compares
the indefinite answer rather than only ordinary values.

**`test_x86_64_decode.py` lost a REFUSAL that had gone false.** It asserted
`0F 7E` "is not emitted and must not be inferred"; `encode_movq_r64_xmm` emits
exactly that, so a decoder that kept refusing it left every `double`-valued
program un-walkable. That is the census's own "a stale test is a coverage hole"
shape, one file over.

`tools/formal_isa_census.BACKLOG` loses all nine x86-64 SSE entries and the
long-stale `encode_imul_r64_r64_imm` one (over-covered since `4a680153`, left
by the previous pass as "another claim's write set"); the x86-64 backend now
has **no `BACKLOG` row at all**, only the three `HARNESS_LIMITS`-attributed
ones. `test_formal_isa_census.py`'s anti-rot half had been red on both.

Measured: `formal/x86_64_model_coverage_test.py` **211 samples over 80 forms,
all steppable**, all five checks green; `test_x86_64_decode.py` green;
`test_x86_64_encoders.py` 152/152; `test_x86_64_model_fuzz.py` 12/12;
`--census --per-form 4 --seed 11` **287 AGREE, 0 WRONG**.

**What is left in this file, and it is now only shape 2's FUZZ column:**

* `encode_call_r64` — the target is a register's contents, outside the harness's
  one `MAP_FIXED` region; a permanent `HARNESS_LIMITS` reason, not work.
* `encode_and_r8_r8` / `encode_or_r8_r8` — the RBP-operand anomaly, which turned
  out to be this tree's own encoder omitting the REX prefix for SPL/BPL/SIL/DIL
  rather than a hardware one, and which `x86-hw-fuzz` fixed with
  `_byte_rex_required` (see "The byte-wise ALU class" below). Their LEAN and AS
  columns are `yes`.
* Two CENSUS-INSTRUMENT defects, reported rather than edited (the tool is
  another claim's write set): the EX column matches a form by DISASSEMBLY
  MNEMONIC, so two encodings of one instruction are indistinguishable; and the
  EMITTED column's `call_sites` regex counts a DOCSTRING mention, which is why
  `encode_cmov_r64_r64` reads as an unexplained gap — it is named in
  `formal/x86_64_codegen.py`'s prose and called nowhere.
* A fuzz-attribution hole the new pool draws exposed (`x86-hw-fuzz`'s file, not
  fixed here): `_impossible_on_hardware` explains a flag difference only when
  the program's LAST flag-writing instruction is a multiply or divide, so a flag
  set by an `and` whose OPERAND was itself an anomalous `setcc` destination is
  reported `WRONG`. Measured: `-n 16 --ninstr 6 --seed 5` now reports 1 such row
  (it was 0 before only because the old pool never drew that shape).

## Status 2026-10-05 (`work/formal42-5`): SHAPE 2 is three of four done, and each row went all the way

`encode_imul_r64_r64_imm`, `encode_call_r64`, `encode_and_r8_r8` and
`encode_or_r8_r8` had a decoder arm, a MODEL arm, a `samples()` row and a
`test_x86_64_decode.py` row each by the end of this pass. The doc's next step
asked for exactly that and the measurement says it is the whole of the gap: with
the three shapes named in the census as `NO` on its LEAN column, `x86_step`
could not step an image the backend emits, and an unsteppable form reads as
result 0.

| row | census now | what closed it |
|---|---|---|
| `encode_imul_r64_r64_imm` | **yes / yes / yes** | `6B /r ib` (not `69 /r id`, which the BACKLOG note says — see below), `x86_step`'s new arm, `x86_step_imul_r64_imm`, two `samples()` rows with both immediate signs, a pool row. The census's LEAN, FUZZ and AS columns are all `yes`. |
| `encode_call_r64` | **yes / NO / yes** | `FF /2` with `mod=11`, a model arm in front of the old `0xff` arm (which fed the same two bytes to `x86_mem_addr`, refused it, and left `x86_step` returning `none`), `x86_step_call_r64`, two `samples()` rows. FUZZ cannot: the instruction jumps to a register's contents and a random 64-bit value is outside the harness's one `MAP_FIXED` region, the same reason arm64's `encode_br_xn` is in `HARNESS_LIMITS`. |
| `encode_and_r8_r8`, `encode_or_r8_r8` | **yes / NO / yes** | `20 /r` and `08 /r`, one shared `x86_step_alu_r8` for BOTH decoders (the encoder emits a REX byte when either register is r8-r15, so an arm in one of them left the rest unsteppable — measured, `and R11, R10` = `45 20 d3` was a `NORUN`), two step lemmas, four `samples()` rows. FUZZ cannot yet, and the reason is a measurement rather than a policy: see §"The class the byte-wise ALU found" below. |

Two things this pass found that the doc did not predict, both worth the next
reader's time:

* **The three-operand `imul`'s destination is a TARGET, not a third
  multiplicand.**  The first version of the model arm multiplied in `dst`'s old
  value, and the CPU disagreed on all three census states.  Measured here, one
  instruction and one fixed register file through this project's own harness:
  `imul RDX, R12, -1` with RDX = `0x0123456789abcdef` and
  R12 = `0xfedcba0987654321` leaves RDX = `0x012345f6789abcdf`, which is
  `R12 * -1`.  `x86_step_imul_r64` (the two-operand `0F AF` form) IS the one that
  reads its destination.
* **The BACKLOG note for `encode_imul_r64_r64_imm` was false in its first
  clause and false in its fix.**  It said "`69 /r id`: no decoder arm (only
  `0F AF` is decoded)"; the encoder emits `6B /r ib`, and the four-bytes-later
  difference between the two spellings is the whole reason it does — the doc's
  own §"What is NOT a gap here" half says so.  The note also claimed the fix's
  motivation ("8 examples are blocked from being walked") was not what was
  happening, which the doc's Status already measured.  The row is now
  over-covered (`yes / yes / yes`), so the entry exempted nothing and the
  census's anti-rot check reported it as a fixed gap that kept its exemption.
  **The entry was removed from `tools/formal_isa_census.py`'s `BACKLOG` on
  2026-10-05**, in the commit that added the arm64 fuzz case for `TST` — the
  census's own self-test was red on the stale entry and on that missing row,
  and both are now green.

### The byte-wise ALU class, and how it turned out

`formal/x86_64_model_fuzz.py` did not draw `and`/`or` for a while because this
harness disagreed about them on an RBP operand and the disagreement was
attributed to `setcontext`-into-RWX rather than to the encoding:

| one instruction, one fixed register file | this harness | exact |
|---|---|---|
| `and RAX, RCX` (`20 c8`) | `rax = efaeef4cddfebb42` | same |
| `and R8, R9` (`45 20 c8`) | `r8 = efaeef4cddfebb42` | same |
| `and RAX, RBP` (`20 e8`) | `rax = efaeef4cddfebb00` | `…42` |
| `and RCX, RBP` (`20 e9`) | `rcx = efaeef4cddfebb02` | `…42` |

**It was this tree's encoder, and the CPU was right.** `encode_and_r8_r8` (and
its `or` twin, and `_setcc`) omitted the REX prefix for SPL/BPL/SIL/DIL (values
4-7), whose 8-bit encodings exist only WITH one: `20 e8` with no prefix is
`andb %ch, %al` — the HIGH byte of RCX — not BPL. `_byte_rex_required` fixes all
three and the rows are in the pool now: a 512-case census over every `rm`/`reg`
pair agrees with exact arithmetic. `encode_setbe(R.RBP)` was the same defect,
which is what the model-fuzz doc's `HARNESS_SETCC_DESTS` class turned out to be.

**What is left in this file is shape 1** — the nine SSE2 scalar binary64
encoders, each of which needs a decoder arm, a model arm, a sample and a pool
entry, and `ucomisd`'s unordered case is the one that decides whether the model
can be trusted for the other eight.  Its next step is unchanged and still the
right one.  Shape 2's fourth row, `encode_movq_xmm_rm64`, was closed with
`work/formal40-7` as a `samples()` row.

**Measured, this pass.**  `formal/x86_64_model_coverage_test.py`: 193 samples
over 71 forms, **all steppable** (was 185/67).  Its successor comparison is now
**green on all 12 forms**: the three `shift_imm8:shl` / `:shr` / `:sar` rows
that set only ZF and SF where `x86_shift_post` sets four were corrected to
quote `x86_shift_post` itself, and the rows added here are what found the drift
(its own doc was deleted with the fix, and `SUCCESSOR_FORMS` is the pin).  The
other four checks are green.
`formal/x86_64_model_fuzz.py --census --per-form 3 --seed 11`: 206 AGREE,
11 HARNESS, 1 FAULT, 1 NORUN, **0 WRONG**.  `-n 16 --ninstr 6 --seed 5`:
11 AGREE, 5 HARNESS, 0 WRONG.  `test_x86_64_decode.py`,
`test_x86_64_encoders.py`, `test_x86_64_model_fuzz.py` and
`test_formal_sweep_truth.py` (136/136) green.

## Status 2026-10-05 (`work/formal40-7`): SHAPE 3 is DONE and one row of SHAPE 2
with it — 18 backlog rows are 13, and all five were closed by asking the CPU a
question rather than by editing a table.** The two `BACKLOG` reasons this file
recorded for three of them are FALSE of this harness and are worth stating,
because "a tool defect that reads as `nothing to do here`" is the direction that
costs:

| row | closed by | measured |
|---|---|---|
| `encode_jcc_rel32`, `encode_jmp_rel32` | a `rel32 0` pool entry — a branch to the NEXT instruction, the same shape the rel8 entries already had | 4 initial states each, AGREE |
| `encode_call_rel32` | a `call rel32 0` pool entry. **The recorded reason was "a call cannot run in the harness's straight-line stub without leaving it", and it does not leave**: the emulated region is ONE `MAP_FIXED` mapping that the terminator falls out of at its end, so a branch to the next instruction stays inside whatever the program already put there, and the pushed return address lands on the emulated stack — outside the compared memory window, which is `DATA_OFF` and not `STACK_OFF`, so it cannot be a false disagreement | 4 initial states, AGREE |
| `encode_lea_r64_rip` | a pool entry. **The recorded reason was "the two engines' RIPs differ by the load slide", and here they do not**: the harness maps its region at a FIXED address and hands the model the same base, so a pc-relative RESULT is the same number in both halves. That reason fits arm64's `encode_adrp`, which keeps its `HARNESS_LIMITS` entry — this project does not map the arm64 harness's code at a fixed address, so only pc DELTAS are comparable there | 4 initial states, AGREE |
| `encode_movq_xmm_rm64` | a `samples()` row. It has had a step-lemma row (`x86_step_movq_xmm_rm64`) since that lemma was written and no sample, so the one function that answers "can `x86_step` step it?" was never asked — and that sample list IS this census's LEAN column on x86-64 | `185 samples over 67 forms — all steppable` (was 183/66) |

The census line moves with them:

```
$ python3 tools/formal_isa_census.py --arch x86_64 | tail -1
   -- 0 form(s) with no LEAN/FUZZ/AS and no exemption; 18 exempt (5 harness, 13 backlog)
```

**What is left is 13 rows in two shapes, and both are bigger than a patch.**
Shape 1 (nine SSE2 scalar binary64 encoders) needs a decoder arm, a model arm, a
sample and a pool entry per form, and `ucomisd`'s unordered case is the one that
decides whether the model can be trusted for the other eight. Shape 2's three
decoder arms (`69 /r id`, `FF /2` with `mod=11`, and the byte-wise `and`/`or`)
each need a model arm and a step lemma as well as the decoder, because
`x86_step`'s group-3 handler and its REX.W-only ALU arm do not reach them today.

**And a defect in the instrument itself, measured and NOT fixed here because the
tool is another claim's write set** (`bug:FORMAL_arm64_instruction_coverage`):
the EX column matches a form against an image by DISASSEMBLY MNEMONIC, so two
encodings of one instruction are indistinguishable. Measured: this doc's own "8
examples" for `encode_imul_r64_r64_imm` is a false attribution — those eight
images contain only `0F AF` (`imulq %rax, %r11`), and the encoder this row is
about emits `6B /r ib` (which the BACKLOG note below miscalls `69 /r id`). Both
spellings print the same mnemonic, so the row claims a corpus that contains a
form it does not, and the fix's motivation ("8 examples are blocked from being
walked") is not what is happening: 39 of the 52 examples emit a `terminates`
theorem today, five of them among the eight named. The fix is to key the column
on (mnemonic, operand shape) and report `ambiguous` where that does not separate
two encodings; it needs the `--examples` cache re-measured for both
architectures, which is cheap (104 compiles, ~5 s).

It is one document rather than eight because the gaps are not eight problems.
They are three shapes, and the shapes are what a reader wants.

## What I ran

```
$ python3 tools/formal_isa_census.py --arch x86_64 | tail -22
   -- 0 form(s) with no LEAN/FUZZ/AS and no exemption; 23 exempt (5 harness, 18 backlog)
```

`0` there means every gap is EXEMPTED, and this file is where 18 of those
exemptions point. The tool's own numbers, not a count stated here: run it.

## Shape 1: SSE2 scalar binary64 (9 forms) — no decoder, no model, no pool

`encode_addsd_xmm`, `subsd`, `mulsd`, `divsd`, `ucomisd`, `xorpd`,
`movq_r64_xmm`, `cvtsi2sd_xmm_r64`, `cvttsd2si_r64_xmm`. All nine are called by
`formal/x86_64_codegen.py` (the `formal_examples.py` host module's `printf`
path and the float arithmetic) and all nine are byte-checked against clang's
assembler in `test_x86_64_encoders.py`. None of them can be NAMED: 

* `formal/x86_64_decode.py` has no `0xF2 0x0F 0x58` arm, so `decode_one`
  refuses — which means `formal/x86_64_proof_gen.py`'s `decode_function_body`
  and `formal/x86_64_endtoend_test.py`'s `_body` cannot walk an image
  containing one, and both report it as "no step lemma wired for: …";
* `formal/x86_64_model_coverage_test.py::samples()` has no sample of any of
  them, so `x86_step` is never asked;
* `formal/x86_64_model_fuzz.py`'s pool has no entry.

The arm64 counterpart of this gap is `bugs/FORMAL_arm64_ieee754_has_no_step_
arms.md`, and it says the same thing about the same ten instructions. Read that
one for what closing it costs on the model side; the x86-64 half additionally
needs the decoder, because on arm64 the emitter's words are classified by
`_STEP_CONDS` (a mask table) rather than by a decoder.

**Next step**: one form, `ucomisd`, end to end — a decoder arm, a sample in
`x86_64_model_coverage_test.py`, a pool entry. The compare is the interesting
one: `UCOMISD` reports UNORDERED with ZF=PF=CF=1, which is why
`formal/x86_64_codegen.py` follows it with `andb`/`setnp` rather than reading
one flag, and a model that decoded it as an integer compare would agree with the
hardware on every ordered pair and disagree on `NaN`.

## Shape 2: forms the emitted encoder has and the DECODER cannot name (4)

| encoder | what it is | why nothing downstream can see it |
|---|---|---|
| `encode_imul_r64_r64_imm` | `69 /r id`, the `x * 10` shape | the decoder's `imul` arm is `0x0F 0xAF` only |
| `encode_call_r64` | `FF /2` with `mod=11`, the call through a function VALUE | the decoder maps `FF` only to `FF 15` / `FF 25` (the RIP-relative forms) |
| `encode_and_r8_r8` / `encode_or_r8_r8` | the byte-wise `and`/`or` the floating compare needs | no REX.W, and the decoder's ALU arm is `w and …` |

Each of these is byte-checked against clang today (`test_x86_64_encoders.py`'s
new rows: `imulq $7, %rbx, %rax`, `andb %cl, %al`, `orb %cl, %al`), which is
why this gap is a NAMING gap and not an encoding gap — and why it is invisible
to every other check in the tree.

**Next step**: the three decoder arms, each with a `samples()` row so the
coverage test asks `x86_step` about it, and each with a `test_x86_64_decode.py`
row. `encode_movq_xmm_rm64` is the fourth in this shape and is already decodable
(`0x66 REX.W 0F 6E`); it only lacks a coverage sample and a pool entry.

## Shape 3: runnable, and the pool does not draw them (5) — DONE 2026-10-05

**All four of the runnable rows are in the pool and AGREE against the CPU** (the
table at the top), and `encode_movq_xmm_rm64` — which this section called "the
fourth in this shape" — is closed by a sample rather than by a pool entry. The
text below is what the section said while the rows were open, and BOTH of the
reasons it gives are recorded at the top because both are false of this harness.


`encode_jcc_rel32`, `encode_jmp_rel32` — the pool draws only the rel8 branch,
while `formal/x86_64_codegen.py` emits the rel32 spelling past a 128-byte reach.
`encode_call_rel32` — a call cannot run in a straight-line stub without leaving
it. `encode_lea_r64_rip` — RIP-relative, so it belongs in `HARNESS_LIMITS`
alongside arm64's `encode_adrp` (the two engines' RIPs differ by the load
slide); it is in `BACKLOG` only because moving it is a one-line edit to this
tool and the edit has not been made.

**Next step**: add `jcc_rel32`/`jmp_rel32` to `formal/x86_64_model_fuzz.py`'s
pool as a branch to the NEXT instruction (the same shape as its rel8 entry, and
`formal/x86_64_endtoend_test.py::_BRANCH_FORMS` already treats them as one
family), and move `encode_lea_r64_rip` to `HARNESS_LIMITS`.

## What is NOT a gap here, so nobody re-derives it

* **`encode_je_rel8` / `encode_jne_rel8`** read `FUZZ: no` to a naive grep and
  are covered: both bottom out in the private `_jcc_rel8`, and the pool draws
  every condition code through `encode_jcc_rel8`. `formal_isa_census._
  delegating_encoders` follows that, and the census reports `yes`.
* **The ten `encode_set*` encoders** are drawn by the pool through
  `getattr(X, "encode_set" + nm)`, which an attribute-only AST walk cannot see.
  `_resolve_getattr` resolves it from the tuple that feeds the comprehension, so
  the answer comes from the ten NAMES rather than from a prefix match — which
  matters, because `setp`/`setnp` are deliberately NOT in that tuple (the model
  does not evaluate parity) and a prefix rule would have claimed them.
* **The memory forms' REX byte.** `as` writes `8b 45 f8` where this backend
  writes `40 8b 45 f8` (a null REX) and writes `48 0f b6` where this backend
  writes `40 0f b6` (no REX.W on a zero-extending load). Both are the same
  instruction; `test_x86_64_encoders.py`'s `REX_VARIANT_CASES` checks that the
  two differ in the REX byte and in NOTHING ELSE, which is the property a field
  in the wrong place would break.