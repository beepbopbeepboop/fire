# FORMAL_the_spill_canary_is_red_and_the_row_it_names_is_stale

**Area:** FORMAL / the arm64 proof generator's own canary.
`test_formal_eval_eq_mojo_bridge.py::TestAConditionalExpressionIsAValue::
test_a_spill_is_not_attributed_to_the_conditional_expression` — a suite that is
**not registered** in `tools/suite.py` (it is in `test_suite.py`'s
`UNREGISTERED`, see
commit d8ef058d4), so no gate
reports it.

**Status: OPEN, measured 2026-10-13 (`work/formal394-docs`), found while
running the narrow suites for the eq/bridge documents. Not this task's to fix,
and filed rather than edited for that reason** — two documents that are not in
this task's list own the subject.

## What I ran

```
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_eval_eq_mojo_bridge.py
…
FAIL: test_a_spill_is_not_attributed_to_the_conditional_expression
AssertionError: '/…/.tmp/spill-arm64-…/spill_arm64_proof.lean' is not None :
  a spilling function now generates an arm64 proof, so
  bugs/FORMAL_arm64_instruction_coverage.md's LDUR/STUR row is stale and this
  row should be re-measured
Ran 23 tests in 1.675s
FAILED (failures=1, skipped=3)
```

## What I saw

The canary builds a twelve-local spilling function, `_generate`s it with
`compile_formal(prove=True, check=False)`, and asserts the generator REFUSES
(`path is None`) because the frame access at a negative offset reaches the
unscaled `LDUR`/`STUR`, which the step table did not have. On this tree the
generator EMITS a proof, so the assertion fails. The generator half is correct:
`LDUR`/`STUR` are modelled now (`formal/arm64_proof_gen.py`'s `_STEP_CONDS` rows
64/65, `work_step_ldur`/`work_step_stur`, added by `35fd4186`, *"arm64: model the
twelve narrower/unscaled memory forms and the two flag-setting compares"*), and
that commit updated neither this canary nor the row it names.

**And the one check I ran did not verify the emitted proof.** Generated with
`check=False` to `.tmp/spill/spill_arm64_proof.lean`, then read through
`formal/lean.py::check_proof(…, timeout=1400)`:

```
Lean ok: False 1400.8s
lean exceeded 1400s wall (limit 1400s) — killed, and this is NOT a verdict on
the proof
```

So the honest statement is **narrower than "the limitation is fixed"**: the
generator no longer refuses, and whether the proof typechecks is UNMEASURED — my
one run breached a 1400 s wall bound (the launcher's own default is 1500 s) and
was killed, which is a fact about the cost and not a verdict. A straight-line
twelve-local function being at the wall is surprising enough to be worth the
next reader's attention; the certificate-cost family it may belong to is
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`.

## What the next step is

1. **Re-measure the spill proof through `formal/lean.py::run_lean` with the full
   1500 s bound** (`check_proof(…, timeout=1500)`), so the answer is a verdict
   rather than a breach. One Lean run; the library is a CAS hit
   (`ensure_library` was 0.4 s here).
2. **If it checks**: delete the canary assertion and correct the two stale
   claims it points at — `bugs/FORMAL_arm64_instruction_coverage.md`'s
   `**LDUR` / `STUR**` row (line ~488, still written as if unmodelled) and §0 of
   `bugs/FORMAL_a_conditional_expression_has_no_value_in_the_semantic_model.md`
   (which lists the spill family as a refusal and cites the canary).
3. **If it does not check**: the generator emitting a proof nothing can verify
   in-budget is the defect, and it belongs with the certificate-cost document
   above rather than here; the canary should then pin the new truth (a proof is
   emitted; checking it does not finish) rather than the old refusal.

The canary is left RED and unmarked on purpose: it fails with a message that
says what stopped happening, and neither editing the assertion nor marking it
would record the measurement this needs.
