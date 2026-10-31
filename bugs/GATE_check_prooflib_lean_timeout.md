# GATE: `make check` job `prooflib` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
Traceback: RuntimeError: lean exceeded 1800s wall (limit 1800s) — killed, and this is NOT a verdict on the proof

`prooflib` builds `lib/ProofLib.olean` under a 1800 s Lean wall and was killed. The build is a dependency of the proof jobs, so every one of them is blocked behind it.
```

Next step: reproduce the job on master (`python3 tools/suite.py prooflib` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
