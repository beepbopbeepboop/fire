# FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it

**`formal/arm64_proof_gen.py`'s `_STEP_CONDS` gained a CSEL row
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

Modelling CSEL is the real fix and `work/formal13-3` measured what it costs,
in `bugs/FORMAL_csel_in_the_model_costs_a_ternary_export_its_whole_proof.md`:
the three-line `arm64_step` branch *builds*, and adding it turns row 3 of that
document's table into a Lean **"excessive memory consumption"** failure out of
`_gen_run_cert`'s composed-state `hx30` proof. That is a Lean-side research
problem, not a merge decision, and a light merge worker is not permitted to run
Lean at all.

Removing the row restores the status quo the model states: CSEL is unmodelled on
BOTH sides, so `_step_branch_index` returns `None` and the generator's "the
model takes no step here" is true. That is honest — a limit, not a wrong answer —
and it is what `formal13-3`'s `_dylib_spec_lean` already assumed when it wrote
that these bodies "still get no PROVED contract".

Also removed, because they were reachable only through that index: the
`if idx == 52:` arm of `_step_rhs` (the CSEL effect) and `52` from
`_regs_written`'s one-register tuple.

## 4. The exact next step

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
   `check_step_conds` and `audit_step_table` then say so themselves.
3. Solve the `hx30` memory problem `bugs/FORMAL_csel_in_the_model_costs_a_ternary_export_its_whole_proof.md`
   records, or accept that a CSEL-carrying export still gets no proved contract
   and say which in the model rather than in the generator's table.
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
