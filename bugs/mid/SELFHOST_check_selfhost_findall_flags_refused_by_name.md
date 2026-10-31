# GATE: `make check` job `selfhost` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
FAIL  findall_flags_refused_by_name  emitted C has no 'mojo_unsupported_iter'

The `findall` flags path should refuse the call by name and emit `mojo_unsupported_iter`. The emitted C does not contain that refusal.
```

Next step: reproduce the job on master (`python3 tools/suite.py selfhost` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
