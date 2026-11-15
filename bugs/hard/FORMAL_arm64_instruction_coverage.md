SPLIT: FORMAL_arm64_instruction_coverage-part1, FORMAL_arm64_instruction_coverage-part2, FORMAL_arm64_instruction_coverage-part3

The first split's three parts landed: the CMP-register SP-form spelling with
3049e7aa7 (on master), the UXTX SP-form branches 86-88 with 2a3ab7d27 (on
master), and the scalar-double FP class, entries 70-79, with aca4f2bbf. What
remains open is the census of the other extend options in the same class
(UXTW/SXTW/SXTX and the 8/16-bit sign/zero extends, the 32-bit spellings, and
the `imm3 <= 4` half of the "option=011, imm3 <= 4" qualifier), which the
`arm64_reg_or_sp` coverage note in `lib/ProofLib.lean` names as this doc's.
That census is the three parts the line above names: pinned as a test, the
refusal naming the word's own option/imm3/sf fields, and the emitter-dormancy
pin. Replanned 2026-11-14 (this doc stays at hard; the parts are easy).

# FORMAL: the extended-register class is claimed by the step table but the generator has no right-hand side for it; the coverage census this doc is is missing

**Status: RESOLVED 2026-11-14 -- all three parts landed** (part 1 and part 2 on
master, part 3 on the branch this merge brings in). Measured 2026-11-12 on the merge of the
`gate:reg-formal-ast-bridge-two-arg` lane (work-6818). The svc fix
(90cce42a5) let guarded programs generate again, which un-masked the rows
below: until then the same classes errored in `setUpClass` on the svc
refusal and this gap was invisible. `TestRegister31` has been red on
master for part of it all along.

This is the census the docstring of `arm64_reg_or_sp` in
`lib/ProofLib.lean` (`~line 1850`) points at: "That is a coverage gap
rather than a wrong answer (the generator refuses such a word rather than
mis-reading it), and `bugs/hard/FORMAL_arm64_instruction_coverage.md` is where
the census of it belongs." The file did not exist, and the statement it
rests on is only half true (below).

## Measured

- The Python step table (`_STEP_CONDS`, 89 entries) claimed entries 70-79
  for the extended-register / 3-source / LDRSW class (representative words
  `0x1e602000` .. `0x9e780000`). `_step_branch_index` resolved those words
  to idx 70-79, `_step_rhs` answered `None` for every one of them, and
  `_step_result_plan` excluded them. So a block containing such a word got
  no step-RESULT lemma, and `_gen_run_cert` refused the run with an `rhs is
  None` that `_cfg_decomposition_refusal` does NOT name: the word "has a
  step" (idx 70-79), so the unmodelled-word search skipped it and the reader
  got the generic "empty block runs certificate" sentence. The same
  misleading-message defect the svc fix closed for idx 35, one class over.
  **Fixed 2026-11-13 (part3):** every entry 70-79 has a `_step_rhs` arm and a
  word-relative twin whose spelling is the model's (`work_step_fcmp` ..
  `work_step_fcvtzs`), so the plan covers them and the step-OK lemma derives
  from the step-RESULT lemma.
- `TestRegister31.test_every_row_is_reachable` fails on the three SP forms:
  `add x0, sp, x16` assembles to `0x8b3063e0` (the model decodes it, branch
  86), `sub x0, sp, x16` to `0xcb3063e0` (branch 87), `cmp sp, x16` to
  `0xeb3063ff` (branch 88) -- while the test's `SP_IN_RN_FORMS` row for
  each says "the extended-register class, which no branch claims". Table
  and model disagree about the same word; the test says "one of the rows
  lies" and does not say which.
  **Fixed 2026-11-13 (part 2, 2a3ab7d27 on master):** the model decodes all
  three words to branches 86-88 with `Rn` read as SP, the table, the model
  and the test rows now agree, and the test is green.
- `_step_rhs(0xeb3063ff, 88)` DOES return a right-hand side, and it reads
  Rn through `arm64_reg_or_sp 31 s` (the SP form). So the extended-register
  CMP form IS modelled, which contradicts the docstring's "nothing in
  `arm64_step` decodes the extended-register class" -- at least for that
  form. The census must be redone per entry; the blanket statement cannot
  stand.
  **Fixed 2026-11-13:** `lib/ProofLib.lean`'s `arm64_reg_or_sp` coverage note
  now states that the UXTX SP forms are modelled (branches 86-88) and names
  the other extend options as refused rather than mis-read.
- Part 1's spelling half is RESOLVED (2026-11-13): `_step_rhs` already
  spells the extended-register SP CMP (`0xeb3063ff`, branch 88) as
  `arm64_reg_or_sp 31 s`, while the shifted-register CMP (`0xeb1003ff`,
  branch 6) correctly keeps `arm64_reg 31 s` (that class has no SP encoding).
  The test was red because its pin still contained the pre-`imm6` shift
  text; it now pins both words and the generated step-RESULT lemma, which
  states the model's `arm64_step` result. Its doc is deleted; the rows still
  open at the time were the 86-88 reachability/census and the 70-79 class,
  both landed since (below).
- The gap is DORMANT in current emitter output: the image of
  `def plain(a, b): return a + b` (arm64) carries ZERO words of the class in
  its executable region (measured over `_exec_code_limit`), so the gate job
  stays green and the generated proofs typecheck. It bites the moment the
  emitter emits one of these words -- the ProofLib comment names exactly
  that spelling: `cmp sp, x16` as clang assembles it is `0xeb3063ff`, the
  extended-register form.

## The rows that measured it (all in `test_formal_call_proof_gen.py`)

- `TestRegister31.test_every_row_is_reachable` (forms: `add x0, sp, x16`,
  `sub x0, sp, x16`, `cmp sp, x16`) -- RED until 2a3ab7d27 (part 2, master)
  modelled branches 86-88; GREEN on the merged tree.
- `TestStepOkDerivesFromStepResult.test_the_derivation_is_total_over_the_step_table`
  (entries 70-79) and `...test_the_step_result_of_every_covered_word_is_still_emitted`
  (entries 70-79) -- un-masked 2026-11-12 by the svc fix (before it, the
  whole class errored in `setUpClass` on the svc refusal). **Both GREEN since
  the part3 fix (2026-11-13).**

## What is expected

Every entry the decoder accepts has a right-hand side (that is what makes
the step-OK derivation total), or the table stops claiming words the model
does not decode (that is what `check_step_conds` cross-checks the table
against), and the generator's spelling is the model's spelling arm for arm.

## Exact next step

All four landed, on both sides of this merge; the list is the record of what
closed them:

1. Per-entry census for 70-79 AND for the 86-88 branches: assemble the
   representative word, ask the model's `arm64_step` in Lean, and read
   `_step_rhs`. Decided per entry as modelled, so the generator emits the
   matching step-RESULT lemma (an arm in `_step_rhs` /
   `_WORK_STEP_BY_IDX`, spelling identical to the model, including the
   `arm64_reg_or_sp` read and the shift spelling). 70-79 landed with
   aca4f2bbf (part 3, this branch: `work_step_fcmp` .. `work_step_fcvtzs`);
   86-88 landed with 2a3ab7d27 (part 2, master).
2. `_step_rhs` CMP-register spelling to the model's, arm for arm (`cmp sp,
   x16` reads Rn through `arm64_reg_or_sp 31 s`; the shifted-register CMP
   correctly keeps `arm64_reg 31 s`): landed with 3049e7aa7 (part 1,
   master); `test_the_generator_keeps_its_own_spelling_and_why` pins both
   words and the generated lemma.
3. Reconcile the `arm64_reg_or_sp` docstring in `lib/ProofLib.lean` with the
   census (it says the class is unmodelled; the extended-register CMP form
   is): landed with 2a3ab7d27's coverage note -- the UXTX SP forms are
   modelled, the other extend options are refused rather than mis-read.
4. Re-run `TestRegister31` and `TestStepOkDerivesFromStepResult`; both
   classes green before the next formal sweep: done on the merged tree
   2026-11-14, both green.

Remaining, and deliberately NOT a part: the other extend options in the same
class (UXTW/SXTW/SXTX) are still refused rather than modelled, and the step
table claims none of them, so there is no row to reconcile yet; the ProofLib
coverage note names this doc as where their census belongs.

Related: `bugs/hard/FORMAL_svc_exit_handling_incomplete.md` (the svc fix that
un-masked this; its remaining item is the dynamic `svc`, a different gap).

## Status 2026-11-14 (parts 2 and 3): the refusal names the word, and dormancy is pinned

The paragraph above said all three parts had landed; parts 2 and 3 had not
(neither test class existed). Both are now landed in `643fdf026`:

- **Part 2** — `_unmodelled_instruction`'s extended arm decodes `sf` (bit 31),
  `option` (bits 15-13) and `imm3` (bits 12-10) and appends them to the `why`
  by architectural name: `option=010 (UXTW), imm3=0`, or for sf=0
  `32-bit, option=011 (UXTX), imm3=0`. The class paragraph is kept whole, so
  the existing `UXTX`-in-why pin still holds. Pinned by
  `TestExtendRefusalNamesTheOption`.
- **Part 3** — `TestExtendOptionsAreDormantInEmittedImages` compiles the same
  fixture with `prove=True` and scans `code[:_exec_code_limit(code)]` word by
  word with the SAME predicate the arm uses, failing on any class word whose
  `sf != 1` or `option != 3`. The pass condition is that predicate, not a
  count: the fixture carries no word of the class today (the dormant state),
  and a count would be vacuous and stay green forever.

Measured: `TestExtendRefusalNamesTheOption`, `TestExtendOptionsAreDormantInEmittedImages`,
`TestExtendOptionCensus`, `TestRegister31` — 18 tests, OK.
`test_formal_call_proof_gen.py` as a whole is UNCHANGED from HEAD: its 21
failures / 6 errors reproduce with `643fdf026` stashed (a pre-existing
`_Scope` object has no attribute `structs_by_name` in `_call_go`), so this
change adds none.
