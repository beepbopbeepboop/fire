# SUITE: `test_trait_requirement_evidence_diagnostic.py` is run by no job, so `suite-self-test` is red

**Status (2026-11-13):** open. Found while running the fast-tier gate job
`python3 test_suite.py` for an unrelated docs-only change. The test itself is
green; the registration is what is missing.

## Repro

    python3 test_suite.py

ends

    Results: 372 passed, 1 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no
        declared family: test_trait_requirement_evidence_diagnostic.py

The file arrived in commit `06ea5b0ef` ("compiler: enforce trait method
requirement evidence (part 2)"), which added it and removed the part-2
trait-conformance doc, but registered nothing.

## What was measured

    python3 test_trait_requirement_evidence_diagnostic.py
    # ok test_positive_moco_compile_returns_normally
    # ...
    # all tests passed

It is cheap (`tiny`, 0.1 GB measured, sub-second here) and green, so
`expect=` / `disabled=` are both wrong answers.

## Expected

`suite-self-test` (and therefore `check`/`gate`) is green, and the file's
eight cases run on every gate.

## Exact next step

Register it in `tools/suite.py` next to the other diagnostic regressions —
`test('trait-requirement-evidence-diagnostic', [PY,
'test_trait_requirement_evidence_diagnostic.py'], mem='tiny', desc=...)` beside
`where-clause-call-site-diagnostic` (line ~4184) — and add that name to the
bucket list that holds those diagnostic tests (`check`), then run
`python3 test_suite.py` to confirm the estate row is gone.
