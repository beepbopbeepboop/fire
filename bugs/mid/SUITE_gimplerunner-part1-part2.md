# SUITE_gimplerunner-part1-part2: Fix gimplerunner compile failures

Parent: `bugs/hard/SUITE_gimplerunner-part1.md` (split). Depends on the triage
in `bugs/mid/SUITE_gimplerunner-part1-part1.md`.

## Goal

Eliminate all `gcc -fgimple` compilation failures in the `gimplerunner` suite
(`test_gimple_runner.py`) so that no test case fails at the compile step.
(Runtime crashes and output mismatches remain tracked by
`bugs/hard/SUITE_gimplerunner-part2.md` and
`bugs/hard/SUITE_gimplerunner-part3.md`.)

## Acceptance

- Running `python3 test_gimple_runner.py` produces no failures whose cause is
  `gcc -fgimple compilation failed`.
- Any fix is covered by the existing gimplerunner cases (or a narrow added
  regression test next to the affected area) and does not regress passing cases.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/gimplerunner-part1-part2.log; ! grep -q "gcc -fgimple compilation failed" .tmp/gimplerunner-part1-part2.log`

The command exits 0 when there are no compile-failure cases remaining in the
gimplerunner suite.
