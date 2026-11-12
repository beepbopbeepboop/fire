# SUITE_gimplerunner-part1-part1: Triage compilation failures in gimplerunner

Parent: `bugs/hard/SUITE_gimplerunner-part1.md` (split).

## Goal

Identify every `test_gimple_runner.py` case that currently fails with a
`gcc -fgimple` compilation error (exit 1 at compile time), capture the exact
failing test names and compiler diagnostics, and group them into root-cause
categories so the remaining compile-failure fixes can be targeted.

## Acceptance

- `## Compile-failure inventory` in this doc lists each compile-failing test
  name, its gcc error excerpt, and an assigned category.
- Each category has a short note on the suspected root cause and the files or
  codegen area likely involved.
- The inventory reflects a run of `python3 test_gimple_runner.py` on this tree.

## Done when

Run:
`python3 -c "import pathlib; t=pathlib.Path('bugs/mid/SUITE_gimplerunner-part1-part1.md').read_text(); assert '## Compile-failure inventory' in t; assert '| Test' in t or '- ' in t"`

The command exits 0 once the triage inventory has been recorded in this doc.
