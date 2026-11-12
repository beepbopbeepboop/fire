# TEST: four formal tests are registered on master in no bucket

Found 2026-11-09 by the recover-apply worker while checking recover row 12
(`737b5b00e`), whose subject is the same bug class: a registered test that
no bucket ever runs.

## What was run
- `git archive master | tar -x -C .tmp/mexp` (export of master, no checkout)
- `python3 -I tools/suite.py -j1 --list` in the export

The bucket column prints `[]` for:

    formal-eh-tables
    formal-once-bound-strings
    formal-str-trim-runtime
    formal-try-model

Their registrations on master are `tools/suite.py:2855`, `:2860`, `:2964`,
`:2967`, all with `cmd` and `mem=tiny`, and none is named in any bucket
(`check`, `gate`, `x86`, ...). The `--list` output also shows `prooflib`
with `[]`, which is correct: it is `dep=True`.

## What was expected
CLAUDE.md, "Known-failing tests": every registered test is in a bucket unless
it declares `dep=True`, and `test_suite.py`'s `the buckets:` checks enforce
it. These four should either be in a bucket or fail the self-test. They were
registered by `0bf96e814` (`formal-try-model`, `formal-eh-tables`, 2026-11-05),
`c7f641b19` (`formal-once-bound-strings`) and `4f0755020` (`formal-str-trim-runtime`,
2026-11-06), all after the 2026-10-01 bucket rule.

## Not yet established
- Whether `test_suite.py`'s bucket self-test currently fails on master. It was
  not run here: the gate is the integrator's job, and a self-test run is not
  needed to name the four tests.
- Which bucket each should join (`check` if cheap, `formal` / a host-module
  row otherwise). That is a measurement per test: run each once under
  `python3 tools/memslot.py --gb 8 --label <name> -- python3 <file>` and read
  the peak and wall time, as row 12's commit did.

## Next step
1. On a branch off master, run `python3 -I tools/suite.py -j1 --list` and
   confirm the four rows above.
2. Confirm `test_suite.py` (`the buckets:` check) fails for them; if it does
   not, fix the check so it does, because a registration in no bucket must be
   a self-test failure (CLAUDE.md).
3. Measure each test once (above), then add each to a bucket with its measured
   `mem=`, and rerun `python3 -I test_suite.py` for the buckets check.
4. Delete this doc in the same commit as the fix.
