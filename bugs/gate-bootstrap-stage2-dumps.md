# Gate: bootstrap-stage2-dumps is red on master

**Job:** `bootstrap-stage2-dumps`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

## Status 2026-11-14 — the red verdict was a runner artifact; root cause fixed

The 2026-11-14 11:49 confirm gate (`work-integ/confirm.log`) reported
`ERROR bootstrap-stage2-dumps:abfulltest_driver.mojo (0s) dependency not
selected: ` — an EMPTY dependency list. Nothing was unselected. The chain
behind the job was red upstream (`mojoc` FAIL exit 2;
`bootstrap-stage1-transitive` RESOURCE, killed at its 4 GB `tiny` ceiling
after 396 s), and the whole cascade settled inside ONE scheduler pass.
`tools/suite.py::execute` classifies a job against its deps at the top of the
loop, so a dependent whose dep settled to a non-pass verdict LATER in that
same pass was still "pending" at classification time; when nothing was left
running or ready, the anti-hang branch then ERRORed it — and because the dep
now had a verdict, the missing list it printed was empty. ERROR rows count as
FAILED, so the gate reported the job red and wrote this doc for a job whose
only crime was sitting behind a red upstream chain (the same artifact did the
same to `bugs/gate-bootstrap-stage3-dumps.md`).

The fix: that branch now splits the deps. One with a settled non-pass verdict
gets the same SKIP the blocked branch gives its own dependants (`dependency
did not pass: <dep>=<state>`); only a dep with NO verdict at all — the shape
the branch exists for, e.g. filtered out by `--only`, a plan that would spin
forever — keeps the ERROR. Pinned by
`test_a_cascade_skip_is_a_skip_not_an_error` in `test_suite.py`, which fails
before the fix (`ERROR c (0s) dependency not selected: `, and the tally
counts the lost cascade as two failures) and passes after.

The job itself stays OFF in `tools/gates.json` until the real upstream chain
lands: the 4 GB `tiny` kill of `bootstrap-stage1-transitive` and the `mojoc`
failure are tracked by `bugs/hard/GATE_red_recover-land_2026-11-02.md` and
`bugs/mid/GATE_recover_land_remainder.md` /
`bugs/CODEGEN_container_kind_coerce_blocks_selfhost.md` — other workers'
claims, not this doc's bug. Re-enabling the entry and re-running the heavy
chain is the integrator's job.

## Done when

`python3 test_suite.py` passes
`test_a_cascade_skip_is_a_skip_not_an_error` (in `test_suite.py`): a
dependent of a dep that settled to SKIP in the same pass is itself SKIP
naming the dep (`dependency did not pass: b=skip`), the tally counts one
failure, not two, and no `dependency not selected: ` row with an empty list
is ever printed for a selected job.
