# FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it

**A SECOND blocker, measured 2026-10-05, and it is the one that decides who can
take this: step 1 below is a `lib/ProofLib.lean` change and that module's
`.olean` does not fit a bounded worker** — `memcap: BREACH 8.0 GB > 8.0 GB
ceiling (100%)` at the tree's own `-j 4`, against `lib/Refine.lean`'s 1.2 GB
from the same call in the same minute (measurement, method and control in
`FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` §"the build wall is
CONFIRMED"). So the two blockers compose and neither is the interesting one:
the certificate (`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`,
another claim) is what makes the row worth landing, and the build is what stops
a bounded worker landing it. Both have to be gone.

**Status, 2026-11-01: the table row and the model are IN together — the arm,
`work_step_csel`, and the generator's five entries land in one commit — and the
class is measured end to end. What remains is step 0's four-branch certificate
(the named walled leaf, reached and recorded below) and one recorded separate
defect that sits across the class's full-file Lean check.**

* **The pairing lands in §4 step 2's order.** `lib/ProofLib.lean`'s diff is
  exactly two hunks, neither in HEAD `d376fad2`: the `arm64_step` CSEL arm
  (34 lines, chain-last — `_STEP_CONDS` hard-codes indices, so a new
  instruction goes last; the arm's comment records the platform-assembler
  measurement that the mask's kept bits separate this class from CSET/CSINC/
  CSNEG/CSINV) and the `work_step_csel` lemma it needs (100 lines, after
  `work_step_smulh`, `hne_ret` plus 68 `bv_decide` exclusion facts). The tree
  had arrived unpaired — the arm WIP, the row absent, and every proved arm64
  build raising in `check_step_conds` — so both land here, in the same commit
  as the generator's five entries, table and model moving together: the
  `_STEP_CONDS` row `(0xffe00c00, 0x9a800000)` (idx 69), the
  `_step_rhs`/`_step_rhs_generic` arms, `_regs_written`, and the `_WORK_STEP`
  entry. `check_step_conds` passes; `audit_step_table` passes with exactly the
  three pre-existing overlap notes.
* **Verification, Lean-free:** `test_formal_proof_breadth.py` 33/33 (wall
  435.6 s, peak 7.7 GB — the doc's two original regressions,
  `test_a_call_to_a_second_function_is_a_proof_refusal` and
  `test_a_list_literal_is_a_proof_refusal_not_a_crash`, now pass; the run also
  rebuilt `lib/ProofLib.olean` with arm and lemma, so the arm builds). Wiring
  9/9 (`test_the_step_table_and_the_model_are_the_same_set` +
  `TestRegister31`), `test_arm64_encoders.py` green; csinc/csneg → idx 42,
  csinv → None (pre-existing), ldur/stur → 64/65, all disjoint.
* **The class, measured under the 12 GB slot** (`check_proof_cached`): the
  ternary (`1 if n > 0 else 2`, one CSEL word `0x1000004d8`) closes
  `tern_sr_70` on `exact work_step_csel …` with the model's own conclusion;
  f3 (three branches, 772,883 bytes) checks at wall 560.1 s / peak 5.6 GB with
  the errors EXACTLY the five `ast` ones of the defect below — all three
  `work_step_csel` closers, the walk, the run tests check; f4 (four branches,
  1,063,840 bytes) is killed at 1501 s CPU against the 1500 s bound (peak
  6.3 GB, "NOT a verdict on the proof") — **step 0's four-branch boundary
  reached for a CSEL program: the named walled leaf, unchanged by the row.**
  The cost is the certificate, not CSEL: the same reading the 2026-10-03
  Status got from the `B.cond` control, now with the arm in the model.
* **Recorded, not fixed here: a separate defect in the emission path.**
  `FORMAL_arm64_concrete_eval_eq_mojo_instances_are_emitted_when_the_ast_bridge_is_omitted.md`:
  the concrete `eval_eq_mojo_N` instances are emitted for a body the AST model
  cannot state, referencing an `ast` the file never declared — five
  `Expected type must not contain free variables` errors per file, and every
  loop-free conditional expression hits it (the ternary and both f-fixtures
  above). It is in HEAD before this round (the gate at L12270 of `d376fad2`;
  the diff here is only the step-table hunks), its next step is one line, and
  its round re-runs the ternary and f3 for the full-file green.
* **A known red in the round's quick tests is not the round's: `test_arm64_emission.py`
  is 6 PASS / 3 FAIL, byte-identical on pristine `097b6818` (measured on a
  `git archive` copy).** The three are the RUNTIME half's bit-test emission
  shapes — `TBZ is emitted, tests the right bit, and its displacement is
  patched` (the bit-3 image disassembles as a test of bits 3, 5, 6 and 13),
  `TST and CMN are emitted and answer CPython` (a one-bit test emits a TBZ
  alongside the TST), and `a mask that is not one bit keeps the general path`
  (a non-power-of-two mask takes the bit-test path). The round lands in the
  proof half — the model, the step table, the generated certificate — and does
  not touch the emitter, so the failures predate it; they are the bit-test
  emitter's own, unfiled here.

**Status, 2026-10-03 (`work/formal16-2`): the REGRESSION is fixed and pinned; the
MODEL ROW is not, and the measurement says the order of the remaining work is the
opposite of what §4 assumed.**

Re-measured rather than quoted, on this tree:

* `_STEP_CONDS` has **54** rows and no CSEL; `lib/ProofLib.lean`'s `arm64_step`
  has **no** `0x9a8…` branch and `lib/work.lean` has no `csel`. Both auditors
  agree, so the state this doc asks for is the state the tree is in.
* The auditor that would have caught the regression is
  `audit_step_table`, and **it was itself broken until 2026-10-03** — it read
  `arm64_step`'s branch conditions with an unanchored regex and matched the
  COMMENT above the TBZ case, so it raised on every run, which took
  `test_formal.py` down before it generated a proof for any of its 49 examples.
  That is why nothing noticed the table drifting. Fixed, and the fix is
  de-duplication rather than a reworded comment: `audit_step_table` now calls the
  same `_decoder_branch_conds` that `check_step_conds` uses (the fix of the
  step-table audit's comment branch, commit `c18fe3a2`).
* `test_formal_call_proof_gen.py::TestGeneratorSource`'s
  `test_the_step_table_and_the_model_are_the_same_set` now asserts both auditors
  pass, so "the table and the model move together" is a test rather than a
  sentence in this doc.

**The CSEL row itself is still not landed, and §4's step 1 is not the blocker.**
The three-line `arm64_step` branch (plus the `work_step_csel` the row needs)
builds — that much was already true. What §4 measured as "the Lean-side research
problem" is a property of `_gen_run_cert` and not of CSEL: with CSEL in the model
a CSEL-carrying export fails with `excessive memory consumption`, and the same
wall is reached by a THREE-BRANCH FUNCTION whose branches are ordinary `B.cond`
comparisons — measured, both shapes, `lean exceeded 1500s wall`, and the
comparisons are the control. See
`bugs/formal/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`, which has the
table and the next step.

So the work is: **the certificate first, the CSEL row second.** The row is three
lines of Lean plus three generator entries once the certificate stops being the
expensive part, and doing it the other way round buys a modelled CSEL that still
gets no proved contract — which is what §4 step 3 offers as the alternative, and
which is worth not choosing on purpose.

---

`formal/arm64_proof_gen.py`'s `_STEP_CONDS` gained a CSEL row
(`(0xffe00c00, 0x9a800000)`) with no matching branch in `lib/ProofLib.lean`'s
`arm64_step`, and `check_step_conds` — which `generate_arm64_proof` calls, so
every proved arm64 build — raises on the mismatch.** Found on 2026-10-03 while
merging `work/formal13-3` into `work/merge-formal14`; the row was introduced by
`work/formal13-3`'s own commit `1be26fff`, and the merge removed it.

## 1. What was seen

```
$ python3 test_formal_proof_breadth.py
FAIL: test_a_call_to_a_second_function_is_a_proof_refusal
AssertionError: 'proof-crash' != 'proof-refused'
FAIL: test_a_list_literal_is_a_proof_refusal_not_a_crash
AssertionError: 'proof-crash' != 'proof-refused'
```

and the verdict behind the misclassification:

```
>>> import formal.arm64_proof_gen as G; G.check_step_conds()
AssertionError: _STEP_CONDS has drifted from arm64_step in lib/ProofLib.lean:
0 model branch(es) with no entry (); 1 entry(ies) with no model branch
(0xffe00c00/0x9a800000).  Every *_step_ok lemma excludes the branches it is NOT
selecting, so a missing entry leaves an `if` open and the generated proof fails
with 'unsolved goals' that name no branch.
```

The counts on the three refs that matter:

| ref | `_STEP_CONDS` | `arm64_step` branches | agrees |
|---|---|---|---|
| `master` | 52 | 52 | yes |
| `work/formal13-3` | **53** | 52 | **no** |
| `work/formal13-8` | 52 | 52 | yes |
| this merge, before the fix | 53 | 52 | no |
| this merge, after | 52 | 52 | yes |

So this is `work/formal13-3`'s own regression and not an interaction between two
branches: on `work/formal13-3` by itself the same call raises. Its commit message
even states the premise it then violated — *"`CSEL` is absent from `arm64_step`,
so all three of these bodies still get no PROVED contract"* — and the comment it
wrote next to the new row asserts a ProofLib row that does not exist
(*"ProofLib's row sits beside its own CSET case rather than at the end of the
chain"*).

## 2. Why the row is wrong rather than merely redundant

`_STEP_CONDS` is the GENERATOR's decoder; `arm64_step` is the function every
generated proof is a theorem about. With the row present and no model branch:

* `_step_branch_index` returns 52 for a CSEL word, and `_step_rhs` renders
  `some (arm64_set_reg rd s (if arm64_matches_condition c s.nzcv then Xn else Xm))`;
* `arm64_step` for the same word matches no branch at all and returns `none`
  (`csel x0, x0, x1, eq` is `0x9a810000`, and no `0xffe0fc00`-masked row in the
  chain claims it — `0x9ac00c00` and the rest are `CSINC`/`CSNEG`/`CSINV`).

So the generator would state an equation about a function that takes no step for
that word: a proof about a different program. `check_step_conds` is right to
refuse, and the loud failure is much better than the quiet version.

## 3. Why the row was removed rather than the model extended

Modelling CSEL is the real fix and `work/formal13-3` measured what it costs:
the three-line `arm64_step` branch *builds*, and adding it turns row 3 of
`bugs/formal/FORMAL_a_conditional_value_in_a_dylib_export.md` §2.1's table into a Lean
**"excessive memory consumption"** failure out of `_gen_run_cert`. That is a
Lean-side research problem, not a merge decision, and a light merge worker is not
permitted to run Lean at all.

**One correction to the sentence this section carried until 2026-10-05**: the
failure is NOT out of the composed-state **`hx30`** proof. All 32 `hx30` goals
are inside a 23.1 s / 2.5 GB check; the cost is the **`hprior_*`** value-flow
facts, 48/144/384/960 at two/three/four/five conditional branches. Both
measurements, and the `hprior` sharing that has since landed, are in
`bugs/formal/FORMAL_a_conditional_value_in_a_dylib_export.md` §2.3–§2.4; the cost
centre and the fix belong to
`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`.

Removing the row restores the status quo the model states: CSEL is unmodelled on
BOTH sides, so `_step_branch_index` returns `None` and the generator's "the
model takes no step here" is true. That is honest — a limit, not a wrong answer —
and it is what `formal13-3`'s `_dylib_spec_lean` already assumed when it wrote
that these bodies "still get no PROVED contract".

Also removed, because they were reachable only through that index: the
`if idx == 52:` arm of `_step_rhs` (the CSEL effect) and `52` from
`_regs_written`'s one-register tuple.

## 4. The exact next step

**REORDERED 2026-10-03, with the measurement that reorders it.** Step 3 is the
first one to do and steps 1–2 are the last, for the reason the Status gives: the
cost is `_gen_run_cert`'s certificate and not the instruction. Steps 1, 2 and 4
below are unchanged and still correct; they are simply not where the work starts.

0. **The certificate** — `bugs/formal/FORMAL_a_three_branch_certificate_exceeds_the_lean_
   bound.md` §4, steps 1–3. Measured to be the same wall for a CSEL export and
   for three `B.cond` branches, so a fix for it closes both.
1. Add the branch to `lib/ProofLib.lean`'s `arm64_step`, beside the CSET case
   (the position `work/formal13-3`'s comment already claimed):

   ```lean
   else if (insn &&& 0xffe00c00) = 0x9a800000 then
     some (arm64_set_reg (insn &&& 0x1f)
             { s with x0 := ..., x1 := ..., x2 := ...
                     nzcv := arm64_matches_condition_bit ((insn >>> 12) &&& 0xf) s.nzcv
                     pc := s.pc + 4 })
   ```

   The three source registers and the condition field have to come out of the
   word, so the row needs a `work_step_csel` lemma beside the existing
   `work_step_*` family — the generator's per-instruction shape, which
   `_step_rhs` already knows how to produce.
2. Then re-add the `_STEP_CONDS` row, the `_step_rhs` arm and `_regs_written`'s
   `52`, all three in one commit, so the table and the model move together.
   `check_step_conds` and `audit_step_table` then say so themselves — and both
   now work, which is the half of this that was silently broken.
3. ~~Solve the `hx30` memory problem~~ — this is step 0 now.
4. Delete this doc in the same commit, per CLAUDE.md.

## 5. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds()"
python3 -c "import formal.arm64_proof_gen as G; print(G.audit_step_table('lib/ProofLib.lean'))"
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_breadth.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
```

`check_step_conds` passes; `audit_step_table` passes with the three pre-existing
overlap notes (`entry 3 shadows entry 5`, `entry 4 shadows entry 47`,
`entry 48 shadows entry 50`); `test_formal_proof_breadth.py` 7/7 (7.9 s);
`test_formal_call_proof_gen.py` 32/32 (17.7 s, and its
`test_generated_proofs_typecheck_with_no_sorries` is the one that would have
caught this by going red rather than by raising).
