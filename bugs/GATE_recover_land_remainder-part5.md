# Runtime jobs triage (replan part 5 of 5)

## Goal

Verify the runtime parity and utility jobs are green on current HEAD and remove them from the OFF entry in `tools/gates.json`. This includes `runtimediff`, `runtimedylib`, `runtimere`, `silentnoop`, `sqliteruntime`, and `suite-self-test`.

## Acceptance

- `python3 test_runtime_diff.py` passes (runtimediff is green).
- `python3 test_runtime_dylib.py` passes (runtimedylib is green).
- `python3 test_runtime_re.py` passes (runtimere is green).
- `python3 test_silent_noop_iter.py` passes (silentnoop is green).
- `python3 test_sqlite3_runtime.py` passes (sqliteruntime is green).
- `python3 test_suite.py` passes (suite-self-test is green).
- The OFF entry regex in `tools/gates.json` no longer matches any of the runtime job names.

## Done when

File: `tools/suite.py` (registry entry for the runtime jobs; each job is the test).

Command: `python3 test_runtime_diff.py && python3 test_runtime_dylib.py && python3 test_runtime_re.py && python3 test_silent_noop_iter.py && python3 test_sqlite3_runtime.py && python3 test_suite.py`

This runs the six runtime tests in one sequential command, verifying they pass and the OFF entry is narrowed accordingly.