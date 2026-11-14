# SUITE_silentnoop-part1-part1: Capture silentnoop run evidence

**Parent:** SUITE_silentnoop-part1 (concluded; its doc was removed on master)  
**Class:** easy

## Goal

Run the `silentnoop` job and capture its definitive outcome so the failure can be
classified without re-running exploratory commands. This part produces evidence
only; it does not interpret the result or change compiler/test code.

## Acceptance

- A committed file `bugs/SUITE_silentnoop-part1-run.txt` records the exact command
  run (`python3 tools/suite.py silentnoop` and/or
  `python3 test_silent_noop_iter.py` as appropriate), the exit code, and the full
  captured stdout/stderr (or a clearly labeled complete tail if the run is too
  large, with a note of any truncation).
- The evidence is sufficient for a reader to tell whether the run timed out,
  failed to build, or produced case-level mismatches.

## Done when

`python3 -m pytest tests/test_suite_silentnoop_part1_replan.py -k part1_capture -q`
passes.
