# FORMAL_x86_64_instruction_coverage_backlog: the x86-64 half of the ISA census, form by form

**Found 2026-10-05 by `tools/formal_isa_census.py`**, the instruction-coverage
census, which prints the matrix for BOTH backends. arm64 is closed: every one
of its 77 emitted forms has a model arm, a fuzz case and an `as` differential,
with the exceptions named in `formal_isa_census.HARNESS_LIMITS` (eight, each a
property of the harness) and `.BACKLOG` (twelve, each with its own doc). This
file is the x86-64 answer, and it is **not** closed: 18 of the 85 emitted forms
have no fuzz case, no model sample, or no decoder arm.

**Status 2026-10-05 (`work/formal40-7`): SHAPE 3 is DONE and one row of SHAPE 2
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

## Status (2026-10-05, `work/formal69-docs`): a FOURTH shape, and it was the only one the three tools in this file could not see

**The three shapes below are all gaps between the EMITTER and the MODEL — a form
the backend can encode that the decoder, the model or the fuzz pool cannot name.
There is a fourth, in the other direction, and it is the one that hid the two
forms this pass closed:**

| | decoded by `x86_64_decode.py` | stepped by `lib/X86.lean` | a sample in `x86_64_model_coverage_test.py` | a row in the end-to-end prover's `_FORMS` |
|---|---|---|---|---|
| `group3:not`, `group3:neg` | yes | **yes** | **yes** | **NO** |

So all three of the tools this file is about — the decoder, the ISA census, the
coverage test — reported those two forms as covered, and six corpus examples
were refused by name anyway:

```console
$ python3 - <<'EOF'
… E._plan() over formal/examples/*.mojo, grouped by the refusal's form …
<form not wired>          5  augassign_floordiv floordiv mod_by_var neg udivmod
<group3:not>              1  unary_ops
<movsxd_r64_r32>          1  printf_int
<idiv>                    2  digits precedence
<str_len: body does not decode>  1
EOF
```

(The list is as `emit_terminates` reports it, so `neg`/`not` are grouped under one
`<form not wired>` line; `printf_int`'s `movsxd_r64_r32` is the one row here that
**no document in `bugs/` names**, and it is also one of the three `NO-RUN`s of the
registered `formal-x86-machine-model` job — see
`bugs/FORMAL_the_x86_machine_model_job_is_red_with_no_marker.md`.)

`no step lemma wired for: neg` reads like the model cannot do a negation. It can;
`lib/X86.lean`'s `F7 /3` arm has been there from the start. What was missing was
`x86_step_neg_r64`, `x86_step_not_r64` and two `_SUCCS` rows, and both lemmas are
one `simp` each over the existing arm — the same five minutes `x86_step_setcc_r8`
took except that `not` is the FIRST test in the arm's `digit = …` chain and so
needs no exclusion hypotheses at all, while `neg` needs exactly one (`neg`'s
successor also has to name four flags, which is why it is not the same five
minutes).

**Why no existing check could see it**, and this is the useful part:

* the ISA census asks whether a form has a decoder arm, a model sample and an
  exemption — all three were true;
* `formal/x86_64_model_coverage_test.py` asks whether `x86_step` can STEP the
  form — it could;
* `SUCCESSOR_FORMS` compares the emitter's successor against the model for the
  forms it lists, and it listed neither;
* the emitter's own tables were consistent — `_FORMS` and `_SUCCS` hold the same
  keys, and `test_formal_sweep_truth.py` checks it — because a form missing from
  BOTH is not an inconsistency.

**The next step for this shape is one line of tooling: derive the coverage
question from `_FORMS` rather than from a hand-built list.** The four rows above
are a table an instrument could compute — for every form in `_FORMS`, does the
corpus actually reach it, and does a corpus example's image contain it — and the
answer for this tree is that `group3:not` was reachable by `unary_ops` and nobody
had asked.

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