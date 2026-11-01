# GATE: `make check` job `sqliteruntime` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
TIMEOUT sqliteruntime (600s) — still running after 600s, killed.

Inside the job's output: `Box[Int64] from runtime/el_boxfail.mojo: RuntimeError: forced: the instantiation could not be built`, and `reflect: client object is tiny — bodies live in the dylib`. The job never finishes.
```

Next step: reproduce the job on master (`python3 tools/suite.py sqliteruntime` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
