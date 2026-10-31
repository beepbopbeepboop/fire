# GATE: `make check` job `gimplerunner` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
FAIL gimple_mixed_kind_flat_list_param_loop: expected stdout '1\n2\na\nb\n2.5\np\nq\n1.5\n2.5\n', got '1\n2\n4303114800\n4303114832\n4303121328\n...'

The loop over a flat list with mixed element kinds prints raw pointer values where the elements should be. This is the generator test group (`gimplegenerators`).
```

Next step: reproduce the job on master (`python3 tools/suite.py gimplerunner` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
