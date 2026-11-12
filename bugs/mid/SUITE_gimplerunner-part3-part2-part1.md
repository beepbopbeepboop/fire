# SUITE_gimplerunner-part3-part2-part1: Triage stdout-mismatch gimplerunner cases

Parent: `bugs/hard/SUITE_gimplerunner-part3-part2.md` (split). Sibling context:
`bugs/hard/SUITE_gimplerunner-part3-part1.md` (return-value half),
`bugs/hard/SUITE_gimplerunner_21_failing.md` (2026-11-11 inventory).

## Goal

Identify every `gimplerunner`-flavoured compile-and-execute case in scope of
the stdout-mismatch half (cases that exit 0 but print incorrect text: wrong
string formatting, raw address, wrong line endings, or missing output) and
record, per case, the expected vs actual stdout and a determination of whether
the generated GIMPLE code's stdout is wrong or the recorded expectation is
wrong.

## Acceptance

- `## Stdout-mismatch inventory` in this doc lists each in-scope stdout-mismatch
  case with: test name, expected stdout, actual stdout (from a run on this
  tree), and classification `compiler bug` or `wrong expected stdout` (with a
  short rationale).
- Cases from `SUITE_gimplerunner_21_failing.md` that are not "exit 0 but prints
  incorrect text" (compile refusals, RSS-only failures, build-time refusals, or
  cases whose CPython/program exit status differs) are explicitly called out as
  out of scope for this part with a reason.
- The inventory reflects a run/check on this tree (e.g. `python3
  test_gimple_runner.py` or targeted case runs) and is sufficient to drive the
  fix parts.

## Done when

- File path: `bugs/mid/SUITE_gimplerunner-part3-part2-part1.md` (this doc).
- Command (cheap): `python3 -c "from pathlib import Path; t=Path('bugs/mid/SUITE_gimplerunner-part3-part2-part1.md').read_text(); assert '## Stdout-mismatch inventory' in t; assert 'compiler bug' in t or 'wrong expected stdout' in t; assert 'expected' in t.lower() and 'actual' in t.lower()"`

The command exits 0 once the triage inventory with per-case expected/actual and
classification has been recorded in this doc.
