# Gate: silentnoop is red on master

**Job:** `silentnoop`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py silentnoop`), then fix the cause. Do not skip or mark the test.

## Status 2026-11-20: red on master because of the build budget, not a wrong answer

Measured on master (clean worktree): `python3 tools/suite.py silentnoop` exits 1 after 306 s. The
failure is `subprocess.TimeoutExpired` from `_run([... 'build', ...])` in `test_silent_noop_iter.py`:
the test's own `TIMEOUT = 300` is a literal per-build budget, and one `fire.py build` ran past it.
No case produced a wrong stdout before the timeout.

- A trivial `fire.py build` (`print(1)`) takes 716 s in a cold worktree and 385 s in the main tree with
  warm caches, under the machine's current load (load average about 7). Both exceed 300 s.
- The job runs 26 cases serially (`CASES`) plus 2 codegen cases, each a full `fire.py build`. At the
  measured cost that is about 2.5 h, against the registry's `timeout=1500` for the job.

So the job cannot pass on this machine as written, whatever the compiler does. Raising the literal
`TIMEOUT` to the shared `exec_budget.COMPILE_TIMEOUT_S` (600) would not be enough: 385 s is already
close to it, and the job timeout would also have to grow to about 3 h. The change that fits a gate is
a test redesign, which is the owner's decision:

1. Check the 26 cases in one `fire.py` process, or with the in-process `compile_to_gimple` path where
   the case is a codegen check, and keep the `build` + run only for the cases that need a real binary.
2. Or split the cases into registered jobs with their own budgets.

Until one of those lands, this doc stays open. The job's red reflects the budget, not a regression.
