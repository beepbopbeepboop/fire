# SUITE: `test_conditional_conformance_synthesis_diagnostic.py` is run by no job, so `suite-self-test` is red

**Status (2026-11-13):** open. Two lanes found this independently the same
day and each filed this doc, so the two filings are consolidated here by the
merge: the `bug:gate-rthdrscan` lane found it while running `python3
test_suite.py` for an unrelated change, and the part-2 lane
(`bug:SUITE_trait_requirement_evidence_unregistered`) found it while
finishing its own bug (same failure shape, a different file). The file is in
neither claim, so it is filed rather than fixed. The trait-conformance lane
that produced it is still running (`bug:DIAGNOSTICS_trait_conformance-part5`
and `-part7` are claimed, `-part6` is open) and its documents tell their
workers NOT to register their test files, which is the contradiction the
Root cause section names.

## Repro

    python3 test_suite.py

ends

    Results: 371 passed, 3 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no
        declared family: test_conditional_conformance_synthesis_diagnostic.py
        (and test_module_globals_compiled.py, see below)

The other two rows are about `test_module_globals_compiled.py`, the analyzer
part3-part1 failing test its own doc says "is written and currently fails"
(`bugs/mid/COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part1.md`):
its three per-child budget literals have no row in the budgets residue
census, so both `budgets: the residue …` rows name it. It is the analyzer
lane's in-flight work, not this bug.

## What was measured

The file arrived in `65cee30d4` ("diagnostics: reject unsynthesizable copy/move
under conditional conformance (part 4)"), which added it and deleted the
part-4 trait-conformance document in the same commit, but registered nothing.
It runs green on its own:

    python3 tools/memslot.py --gb 8 --label synth-diagnostic -- \
        python3 test_conditional_conformance_synthesis_diagnostic.py
    # OK: 6 tests passed
    # peak 0.0 GB

It is a `compile_to_gimple`-only, no-build suite like the part-2 one in
`bug:SUITE_trait_requirement_evidence_unregistered`: cheap, so `expect=` /
`disabled=` are both wrong answers.

## Root cause: two instructions that contradict each other

The trait-conformance docs say, in their `## Acceptance check`:

    Add `test_..._diagnostic.py` (next to the other `test_*_diagnostic.py`
    files; do NOT register it in `tools/suite.py`).

That instruction predates (or ignores) `test_suite.py`'s estate check, which
requires every `test_*.py` on disk to be named by a spec, listed in
`UNREGISTERED`, or matched by a declared family. Each new
`test_*_diagnostic.py` this lane lands therefore turns `suite-self-test` red
the moment it merges. The part-2 half of the shape is resolved in this
merge: `test_trait_requirement_evidence_diagnostic.py` is registered as
`trait-requirement-evidence-diagnostic` in `check` (pinned by name in
`test_suite.py`), and the `UNREGISTERED` entry master added for it to keep
the estate row green while the lane finished is removed here, because the
registration supersedes it — the estate check's `resolved` row says so.
The pattern is ongoing: on the tip of master the part-7 fix (`ec12b76e1`)
landed its `test_downcast_witness_diagnostic.py` the same way — added, with
no spec naming it.

## Expected

`suite-self-test` (and therefore `check`/`gate`) is green, and the file's
six cases run on every gate.

## Exact next step

Pick one, for the whole family and not for this one file:

1. **Register them** (the part-2 precedent): a `test(...)` registration each,
   `mem='tiny'`, named in a bucket the gate expands. The part-2 file went
   into `check` beside `where-clause-call-site-diagnostic` (line ~4184);
   this file's own registration would be
   `test('reg-conditional-conformance-synthesis-diagnostic', [PY,
   'test_conditional_conformance_synthesis_diagnostic.py'], mem='tiny',
   desc=...)` beside `reg-conditional-conformance-declaration-diagnostic`
   (line ~4258) — but that sibling sits in the `regressions` bucket, which
   `gate` does not expand, so a registration there goes the estate row green
   without a run ever executing the cases; if the family goes to
   `regressions`, say so deliberately and name the explicit run. Either way,
   change the `## Acceptance check` sentence in
   `bugs/mid/DIAGNOSTICS_trait_conformance-part{3,5,6,7}.md` from
   "do NOT register it" to naming the registration; or
2. **Excuse them with a reason** in `test_suite.py`'s `UNREGISTERED` (the
   stopgap this merge used for the part-2 file before its registration
   landed), and change those documents to say which entry to add. This is
   the weaker answer: these suites are cheap and pin diagnostics that would
   otherwise not run.

Until one of those lands, `suite-self-test` stays red on every gate, which is
the same coverage hole the estate check exists to name.
