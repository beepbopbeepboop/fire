# Gimple jobs triage (replan part 4 of 5)

## Goal

Verify the gimple codegen jobs are green on current HEAD and remove them from the OFF entry in `tools/gates.json`. This includes `gimplegenerators`, `gimplerunner`, `globcompiled`, `linkmode`, and `modcache`.

## Acceptance

- `python3 test_gimple_generator_runner.py` passes (gimplegenerators is green).
- `python3 test_gimple_runner.py` passes (gimplerunner is green).
- `python3 test_glob_compiled.py` passes (globcompiled is green).
- `python3 test_link_mode.py` passes (linkmode is green).
- `python3 test_module_cache.py` passes (modcache is green).
- The OFF entry regex in `tools/gates.json` no longer matches any of the gimple job names.

## Done when

File: `tools/suite.py` (registry entry for the gimple jobs; each job is the test).

Command: `python3 test_gimple_generator_runner.py && python3 test_gimple_runner.py && python3 test_glob_compiled.py && python3 test_link_mode.py && python3 test_module_cache.py`

This runs the five gimple tests in one sequential command, verifying they pass and the OFF entry is narrowed accordingly.