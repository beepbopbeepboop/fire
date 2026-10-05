#!/usr/bin/env python3
"""Per-child subprocess budgets for the test suites, and why they are large.

Every one of these numbers was originally 10, 20 or 30 seconds, chosen as "much
more than a tiny program needs" and therefore meaning nothing. They are not
meaningless now, but only because of what they cost: on a loaded machine they
were firing, and a timeout inside a test file is reported as an ordinary FAIL,
i.e. as a compiler bug.

Measured, in one full `make gate` at `-j18`:

    runner            FAIL int_is_64bit          timed out after 10 seconds
    modcache          traceback, TimeoutExpired  timeout=20
    gimplegenerators  FAIL 4 cases               timed out after 10 seconds

All three pass standalone -- `runner` 17/17, `modcache` 83/83,
`gimplegenerators` 155/155 -- so none of them was a miscompile. The cause is
structural, not bad luck: a test's total duration includes every compile AND
every run, and under `-j18` with the machine-wide memslot queue a single
`gcc -fgimple` or a single process launch can exceed a budget sized for a
program that runs in milliseconds. This box also hosts other worktrees, so the
baseline load is not zero.

## Why the fix is layering and not forgiveness

There is exactly one hang detector that can be trusted to be *labelled*: the
suite's per-job timeout, which kills the job and records it as a failure in its
own class tagged `[TIMEOUT]`. `tools/suite.py` now arms that for every
registered test that does not name its own (`DEFAULT_JOB_TIMEOUT_S`, 3600 s --
~6x the slowest healthy test measured). So the inner budgets below no longer
have to carry that job at all. They only have to be:

  * far above the healthy case, so load cannot reach them, and
  * far below the job timeout, so a wedged child is still reaped long before
    the job is killed and the whole job's other results are lost.

Nothing here absorbs a hang: `expect=` does not forgive a timeout (a job killed
at its timeout has reported nothing, so forgiving it would be a way to not run a
test and call the run green), and a job that exceeds the suite timeout is still
a red run.

## Using these

    from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

Prefer these over a literal. A literal is how this defect spread across 29
files in the first place, and a reader has no way to tell a deliberate 5-second
budget from a stale one.
"""

# A single `gcc -fgimple` over one module, or the link of the result. Measured
# individually in the tens of seconds when several run at once; 600 s is ~50x the
# observed worst case and still 6x inside DEFAULT_JOB_TIMEOUT_S.
COMPILE_TIMEOUT_S = 600

# Linking a produced executable is cheaper than compiling it but shares the same
# contention, so it gets the same budget rather than a second guess.
LINK_TIMEOUT_S = 600

# Running a compiled program. These are snippets that execute in milliseconds;
# 120 s is four orders of magnitude above the healthy case, so nothing short of a
# genuine wedge gets near it.
RUN_TIMEOUT_S = 120

# Building the stdlib, or any other whole-tree sweep that compiles hundreds of
# files in one child. Far above any healthy observation, and still well inside
# the job timeout.
SWEEP_TIMEOUT_S = 1800