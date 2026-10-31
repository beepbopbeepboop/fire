# GATE: `make check` job `silentnoop` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
Traceback: RuntimeError: lean exceeded 1800s wall (limit 1800s) — killed, and this is NOT a verdict on the proof

The Lean step hit its 1800 s wall, and the job exits 1 with no verdict. Also shows `findall_flags_refused_by_name` in the same block, which may be the selfhost job's output (check the block header).
```

Next step: reproduce the job on master (`python3 tools/suite.py silentnoop` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
