# TEST_formal_os_backing_stat_cases_die_of_SIGKILL_under_load: two `stat_*` cases fail intermittently with no diagnostic, and only in a full run

**Claim `project15:os-environ` (`work/formal15-os-environ`), filed while adding
the `os.environ` cases to this file and NOT caused by them.** What I ran, what I
saw, and the one thing a reader must not conclude from it.

## What I ran

`python3 test_formal_os_backing.py` — the whole suite, 58 cases, each built for
arm64 and x86-64 — six times on `work/formal15-os-environ`, under
`python3 tools/memslot.py --gb 8 --label … --` on a machine carrying a dozen
other workers. Then the two failing cases alone, six times each.

## What I saw

Two of the six full runs were **56/58**, and both times the same PAIR:

```
FAIL stat_dangle [arm64]  exit -9, stderr ''
FAIL stat_fifo    [arm64]  exit -9, stderr ''
```

The other four runs were 58/58. Run alone, `stat_fifo` was **6/6 PASS** on both
architectures.

`exit -9` with empty stderr is SIGKILL: the runner's own `run()` reports a
timeout as 124 with a message naming it, so this is not the timeout path and not
a refusal. `memcap` reported `peak 0.1 GB` on every run, so it was not
`memcap`'s ceiling either.

## What I expected

Green, or at least a diagnostic. `test_formal_os_backing.py` is the file whose
stated purpose is that "every case EXECUTES, because a lowering that builds a
plausible wrong image is exactly what this suite exists to catch" — so an exit
status with no stderr and no attribution is the one failure mode it cannot
distinguish from a real one. As it stands the report says the `os` module is
broken, twice, for a reason that is not about the `os` module.

## The one thing a reader must not conclude

**That it is a regression from whatever landed.** The two cases do not link any
code that change touched: they build a program importing `os.path` only, and
`os/path/__init__.mojo` does not import `os/__init__.mojo`. They also fail only
in a FULL run, where up to three `fire.py` builds are in flight at once — the
shape `bugs/OPEN_WORK.md` §C2 warns about by name: "A SIGKILL here is evidence of
nothing. A manual `kill -9` and an OS kill are the same signal, and this area has
now been misdiagnosed twice by inferring OOM from a silent death."

So this file records the observation and NOT a cause.

## The exact next step

Reproduce it in the foreground with the cause visible, which is what §C2 asks for
and what nothing here does: run the suite under a memory monitor
(`/usr/bin/time -l`, or `footprint` on the suspect) with no other builds running,
six times, and record whether the peak is real. If it never reproduces alone and
the peak is 0.1 GB, the honest fix is in the RUNNER, not in the cases: a job
killed by a signal the harness did not send should be reported as its own status
the way `[TIMEOUT]` is, so that "the machine killed it" and "the module answered
wrongly" cannot both print `FAIL <case>`.