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

# Two aliases for the two a build-and-run suite actually has, because "which of
# these is the child I am about to spawn" is the first question a call site asks
# and the answer is the same two constants. `BUILD_TIMEOUT` is a COMPILATION, so
# it is the compile budget; `RUN_TIMEOUT` is an execution. A file that had its
# own `BUILD_TIMEOUT = 300` / `RUN_TIMEOUT = 60` was a file that had answered
# that question locally, which is the thing `tools/suite.py`'s `STALE_PER_CHILD_
# BUDGETS` census cannot see — it walks `timeout=` keywords, not constants.
BUILD_TIMEOUT = COMPILE_TIMEOUT_S
RUN_TIMEOUT = RUN_TIMEOUT_S

# ── how a child ENDED, as its own status rather than an exit number ────────
#
# A negative `subprocess` return code is the ONLY record of which signal killed
# a child, and printing it as a number is how "the machine killed it" and "the
# module answered wrongly" come to print the same line. Measured, on
# `test_formal_os_backing.py`: two of six full runs were 56/58 and both times the
# same pair of `stat_*` cases died with `exit -9, stderr ''` and nothing else —
# which reads as a defect in the `os` module and is not one. `bugs/OPEN_WORK.md`
# §C2 says it by name ("a SIGKILL here is evidence of nothing: a manual `kill -9`
# and an OS kill are the same signal"), and this is the mechanical half of that
# sentence: name the signal, and say that nothing in a test harness signals a
# child it launched for a timeout (it reports `TIMEOUT_RC` and stops waiting, or
# sends SIGTERM and then SIGKILL — which is stated where it happens, not
# here).
#
# Four suites hand-rolled this with four different wordings, one of which printed
# a bare `signal 9`; one implementation is the point.

# What `run_child` below reports for a child that exceeded its budget, chosen to
# be a status no compiled program of ours returns and distinct from every signal.
TIMEOUT_RC = 124


def signal_name(rc: int) -> str:
    """`"SIGSEGV"` for `-11`, `"signal 11"` for a signal this host has no name for."""
    import signal as _signal
    try:
        return _signal.Signals(-rc).name
    except (ValueError, AttributeError):
        return f"signal {-rc}"


def child_died_by_signal(rc: int) -> bool:
    """Whether `rc` says a SIGNAL ended the child, rather than an exit status.

    `rc == 0` and any positive `rc` are the child's own exit status; a negative
    one is `-signal`. `TIMEOUT_RC` is deliberately NOT a signal — it is the
    harness's own convention for a child it stopped waiting for, and calling it
    one would put a budget in the same class as a crash.
    """
    return isinstance(rc, int) and rc < 0


def child_exit_reason(rc: int, stderr: str = "", tail: int = 300,
                      subject: str = "the process") -> str:
    """One sentence naming HOW a child ended, for a failure message.

    The three cases a reader has to be able to tell apart, because each needs a
    different next step and none of them is "look at the module":

      * `the image exited 7` — it ran and chose 7. A wrong answer, or a refusal
        it does not print. Look at the module.
      * `the image was killed by SIGSEGV (wait status -11)` — a fault in the
        compiled image. Look at the module, and this is the one the bare number
        used to hide.
      * `the image was killed by SIGKILL … nothing this harness sends` — a
        resource death. Look at the machine, and re-run it alone before reading
        anything into it.

    `subject` is the noun so the sentence composes at every call site — a suite
    that reports "the build" and one that reports "the image" can both use it,
    and quoting the result keeps its subject. `stderr` is appended when there is
    any, truncated to `tail` characters, because a crash's stderr is often where
    its reason is and an empty one is itself the information (a SIGKILL prints
    nothing).
    """
    err = (stderr or "").strip()
    tail_text = f", stderr: {err[-tail:]}" if err else ", with no stderr"
    if child_died_by_signal(rc):
        name = signal_name(rc)
        who = ("nothing this harness sends a child it launched for a timeout: "
               "the harness reports %d and stops waiting, or sends SIGTERM "
               "first" % TIMEOUT_RC) if name in ("SIGKILL", "SIGTERM") else \
            "a signal the image itself raised"
        return (f"{subject} was killed by {name} (wait status {rc}), which is "
                f"{who}{tail_text}")
    if rc == TIMEOUT_RC:
        return (f"{subject} did not finish within its budget "
                f"({TIMEOUT_RC}){tail_text}")
    return f"{subject} exited {rc}{tail_text}"
