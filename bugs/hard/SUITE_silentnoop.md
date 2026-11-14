# SUITE_silentnoop: make check failure

SPLIT: SUITE_silentnoop-part1, SUITE_silentnoop-part2

**Status:** OPEN — surfaced by `make check` run on 2026-11-08 (suite: 35 passed, 23 failed).

Not a timeout: the job runs 644 s against its registered `timeout=1500` and
still fails. Part 1 (investigation) is closed — it found exactly two failing
cases sharing one build-time refusal — and the defect is filed as
`bugs/CODEGEN_param_container_kind_across_call_sites_refused.md`. The fix is
`bugs/SUITE_silentnoop-part2.md`.
