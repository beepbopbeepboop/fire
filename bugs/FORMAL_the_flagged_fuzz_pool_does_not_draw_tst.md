# FORMAL_the_flagged_fuzz_pool_does_not_draw_tst

**Area:** FORMAL, the arm64 model-vs-hardware fuzzer's instruction pool
(`tools/formal_model_fuzz.py::gen_flagged_alu`) and the ISA census that reads
it (`tools/formal_isa_census.py`).

**Status: OPEN, diagnosed, not fixed. Pre-existing on this tree and found while
landing `FORMAL_arm64_smulh_has_no_model_arm.md` — which is the same defect
one row over.**

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_isa_census.py
    FAIL: test_every_emitted_form_has_a_model_a_fuzz_case_and_an_as_check
    AssertionError: Lists differ: [] != [('encode_tst_xn_xm', ['fuzz'])]
    FAIL: test_the_arm64_backend_has_no_unexplained_gap_at_all
    AssertionError: Lists differ: [] != ['encode_tst_xn_xm']
    Ran 7 tests
    FAILED (failures=2)

and the row itself:

    $ python3 tools/formal_isa_census.py --arch arm64 | grep encode_tst
       encode_tst_xn_xm               yes   NO   yes  ?     arm64_codegen.py x2

`yes` = an encoder, `NO` = **no fuzz case draws it**, `yes` = `as` checks it.

## What is seen

`encode_tst_xn_xm` is EMITTED — `formal/arm64_codegen.py`'s
`_emit_branch_unless_and_test` calls it, twice (`if x & y:` and
`not (x & y)`), which is what the `x2` in the EX column counts — and
`lib/ProofLib.lean` has modelled it for weeks (`work_step_tst`, step-table
entry 67, `arm64_logic_flags`). So the LEAN column reads `yes` and the
`as` column reads `yes`.

**The FUZZ column reads `NO`, and it is the pool's own omission.**
`gen_flagged_alu`'s six arms are `adds`, `smulh`, two scaled register adds and
two scaled immediates; none of them is `tst`, and no other generator in
`tools/formal_model_fuzz.py` spells it either. So the one instruction the
`flagged` mix exists to draw — the LOGICAL flag test, whose NZCV semantics are
`arm64_logic_flags` with C and V clear — is drawn by nothing, and
`formal_model_fuzz.py` has never once compared the model against hardware on it.

## Why it is the same defect as the SMULH row, and why that matters

`bugs/FORMAL_arm64_instruction_coverage.md` records the TST/CMN wiring
(`encode_tst_xn_xm`, `encode_cmn_xn_xm`: encoders, `arm64_step` arms,
`work_step_tst`/`work_step_cmn`, `_STEP_CONDS` 67/66) and its own measurement
that "no lowering emits either" — which was then corrected when the lowering
landed. **The wiring's fourth thing was never done: the fuzz pool still draws
neither.** The census is what noticed, and it noticed it as a red test rather
than as a finding, because by then the row had stopped being a gap in the MODEL
and had become a gap in the HARNESS — the two are different subjects and the
census's `FUZZ` column is the one that separates them.

So this row is the mirror image of the SMULH one that was fixed in the same
commit: there, an emitted instruction had no model arm (the model was the
hole); here, an emitted instruction has a model arm and no fuzz case (the
harness is the hole). Both are invisible to "does the corpus still pass",
because in both cases the answer is yes.

## What is expected

`gen_flagged_alu` draws `tst x%d, x%d, x%d` / `cmn x%d, x%d, x%d` — `cmn` is
already modelled (entry 66) and equally undrawn, so the census will name it
next — and the row reads `yes yes yes`. The two are natural additions to this
generator: both set NZCV, both have `work_step_*` lemmas, and both are the
flags half of what the generator is for.

The measurement that says the addition is right is
`python3 tools/formal_model_fuzz.py --mix flags --cases 200` (or
`--mix flagged`), which is cheap: `--cases 400 --length 1` runs in 41 s.

## The exact next step

1. Add the two arms to `gen_flagged_alu` (two `if k ==` cases each, next to
   `k == 0`'s `adds` and `k == 1`'s `smulh` — the generator's
   `encode_tst_xn_xm`/`encode_cmn_xn_xm` are already imported as `A.`).
2. `python3 tools/formal_isa_census.py --arch arm64 | grep -E "tst|cmn"` and
   require `yes yes yes` for both rows.
3. `python3 tools/memslot.py --gb 8 --label fuzz -- python3
   tools/formal_model_fuzz.py --mix flagged --cases 400 --length 1` — and
   **require the tally to be AGREE with no NOSTEP**, which is the part a new
   pool arm usually gets wrong: `work_step_tst`'s answer is
   `arm64_logic_flags (Xn &&& Xm)` with C and V CLEAR, and a pool arm that
   disagreed with the hardware here would be the finding.

**Not fixed in the branch that found it:** `tools/formal_model_fuzz.py` is
inside the area `bug:FORMAL_model_fuzz_ledger` and `bug:FORMAL_fuzz_ledger`
(worker `formal28-4`) hold, so adding two generators to their pool from here is
the merge conflict this project's rules exist to avoid. The finding is exact
enough to be twenty minutes of work, and the census test that reports it is
already red so it cannot rot unnoticed.
