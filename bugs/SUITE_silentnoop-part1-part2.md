# SUITE_silentnoop-part1-part2: Classify silentnoop failure and record cases

**Parent:** SUITE_silentnoop-part1 (concluded; its doc was removed on master)  
**Depends on:** bugs/SUITE_silentnoop-part1-part1.md  
**Class:** easy

## Goal

Using the captured evidence from part 1, determine the `silentnoop` failure mode
and record the exact failing cases or errors so follow-up fix work
(`bugs/SUITE_silentnoop-part2.md`) has concrete inputs.

## Acceptance

- A findings record in this doc contains:
  - a `## Classification` section stating whether the failure is a timeout, a
    build error, or specific compiled-case divergence from the CPython
    reference (or a combination, if evidenced), with brief justification citing
    the captured run.
  - a `## Cases` section listing the exact cases that fail (or stating "none" if
    the failure is purely a timeout/build-level issue) and, for each, the
    observed error/output mismatch.
- If the failure is purely a timeout, the findings explicitly say so and note
  that the fix is tracked by `bugs/SUITE_silentnoop-part2.md`. If specific cases
  fail, the findings include enough detail for part 2 to be updated with those
  exact cases and errors.

## Done when

`python3 -m pytest tests/test_suite_silentnoop_part1_replan.py -k part1_classify -q`
passes.
