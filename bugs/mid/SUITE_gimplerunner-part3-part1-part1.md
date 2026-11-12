# SUITE_gimplerunner-part3-part1-part1: Triage wrong return-value cases in gimplerunner

Parent: `bugs/hard/SUITE_gimplerunner-part3-part1.md` (split of the "wrong return values" half of part 3). Sibling: `bugs/hard/SUITE_gimplerunner-part3-part2.md` covers stdout/representation mismatches.

## Goal

Produce a concrete inventory of the `test_gimple_runner.py` failures that are
value-correctness mismatches: cases that compile and exit 0 but produce a wrong
computed, stored, looked-up, or returned value (as observed in the program's
result/output), as opposed to stdout formatting/representation-only issues (raw
addresses, repr shape) or to compile refusals and RSS-only failures.

For each case, record the expected vs actual values and a verdict of **compiler
bug** or **wrong expected value**, with a short rationale (including a check
against CPython/reference behavior where the test intent is ambiguous).

## Acceptance

- `## Return-value inventory` in this doc lists each in-scope failing test name
  (from the current gimplerunner failures, e.g. as tracked in
  `bugs/hard/SUITE_gimplerunner_21_failing.md`), its expected vs actual values,
  and a verdict (`compiler bug` or `wrong expected value`) with rationale.
- Cases that are representation/stdout-only, compile refusals, or RSS-only are
  explicitly marked out-of-scope for this part with a pointer to the
  appropriate sibling/parent doc or group.
- The inventory states the evidence source (log path or command) used to read
  expected/actual values.

## Done when

Run:
`python3 -c "import pathlib; t=pathlib.Path('bugs/mid/SUITE_gimplerunner-part3-part1-part1.md').read_text(); assert '## Return-value inventory' in t; assert '| Test' in t; assert 'compiler bug' in t or 'wrong expected value' in t"`

The command exits 0 once the return-value triage inventory, with verdicts, has
been recorded in this doc.
