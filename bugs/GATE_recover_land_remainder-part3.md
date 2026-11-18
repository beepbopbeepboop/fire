# Formal jobs triage (replan part 3 of 5)

## Goal

Verify the formal proof jobs are green on current HEAD and remove them from the OFF entry in `tools/gates.json`. This includes `formal-sweep-truth` and `formal-sys`.

## Acceptance

- `python3 test_formal_sweep_truth.py` passes (formal sweep truth is green).
- `python3 test_formal_sys.py` passes (formal sys is green).
- The OFF entry regex in `tools/gates.json` no longer matches either of the formal job names.

## Done when

File: `tools/suite.py` (registry entry for the formal jobs; each job is the test).

Command: `python3 test_formal_sweep_truth.py && python3 test_formal_sys.py`

This runs the formal proof tests in one sequential command, verifying they pass and the OFF entry is narrowed accordingly.