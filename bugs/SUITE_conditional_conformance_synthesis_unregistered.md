# SUITE: `test_conditional_conformance_synthesis_diagnostic.py` is run by no job, so `suite-self-test` is red

**Status (2026-11-13):** open. Found while running `python3 test_suite.py` for an
unrelated change (`bug:gate-rthdrscan`). The test itself is green; the
registration is what is missing.

## Repro

    python3 test_suite.py

ends (with `bug:SUITE_trait_requirement_evidence_unregistered`'s row alongside)

    Results: 371 passed, 2 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no
        declared family: test_conditional_conformance_synthesis_diagnostic.py

The file arrived in commit `65cee30d4` ("diagnostics: reject unsynthesizable
copy/move under conditional conformance (part 4)"), which added it and
registered nothing.

## What was measured

    python3 tools/memslot.py --gb 8 --label synth-diagnostic -- \
        python3 test_conditional_conformance_synthesis_diagnostic.py
    # OK: 6 tests passed
    # peak 0.0 GB

It is cheap (`tiny`) and green, so `expect=` / `disabled=` are both wrong
answers.

## Expected

`suite-self-test` (and therefore `check`/`gate`) is green, and the file's six
cases run on every gate.

## Exact next step

Register it in `tools/suite.py` next to the other diagnostic regressions —
`test('reg-conditional-conformance-synthesis-diagnostic', [PY,
'test_conditional_conformance_synthesis_diagnostic.py'], mem='tiny',
desc=...)` beside `reg-conditional-conformance-declaration-diagnostic` (~line
4246), add that name to the `regressions` bucket list, then run
`python3 test_suite.py` to confirm the estate row is gone.
