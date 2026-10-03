# FORMAL_sweep_sigterm_drains_the_whole_scope: the "clean drain" builds every file the run was told to stop building, and does not report the ones it built

**Class:** instrument defect (`tools/formal_sweep.py::_stream_results`).
**Effect:** a sweep that is asked to stop keeps **building the entire rest of
its scope** — every queued file, not just the builds in flight — prints nothing
more, and when it finally exits reports only the files it had classified when
the signal arrived. **Measured** on the `-b6` sweep of 2026-10-02: the arms
stopped printing at once, were still starting builds more than ten minutes
later, and needed a second `SIGTERM` to die.
**Companion:** `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md`, found in
the same sweep; both are in the same file and neither is claimed.

## What the code says it does

`tools/formal_sweep.py:2604`, on the SIGINT/SIGTERM handler:

> the pool is shut down **without waiting for the builds still in flight** (they
> are the slow part, and the caller has already decided they are not wanted),
> whatever had finished is published, and the exit status says the run was cut
> short.

and the module docstring, on exit status 3:

> Everything it classified was printed and published, and the summary says how
> much of the scope it reached.

## What it does

```python
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(run_one, p, timeout, flags, mem_gb): p
                    for p in files}                      # ALL of them, up front
            for fut in concurrent.futures.as_completed(futs):
                ...
                if stop.is_set():
                    return True
```

Two things make the drain do the opposite of what the docstring says.

1. **Every file is submitted before the first one is classified.** `futs` is a
   dict comprehension over the whole scope, so the executor's queue holds the
   entire run, not the next `-j` files.
2. **`return True` leaves the `with` block, and `ThreadPoolExecutor.__exit__`
   calls `shutdown(wait=True)`** — which does **not** cancel: `cancel_futures`
   defaults to False, so each worker keeps pulling the next queued file until it
   reaches the sentinel `None` that `shutdown` appends after the queue. The
   scope is walked to the end anyway, one file per worker per iteration, and
   `shutdown` then joins the threads.

So a signalled run stops **printing** immediately and stops **nothing else**.
The signal handler's `stop` flag only decides when the *reporting* loop leaves.

## What was seen

The `-b6` sweep (`-j 8 -t 600`, both arms, 652 files each) was signalled and
reported no further lines, which is what a working drain looks like — the log
stopped at 164 lines per arm and stayed there. It was also still starting
builds. `ps` of the sweep's children, taken about ten minutes after the signal:

```
$ ps -Ao pid,ppid,stat,etime,time,command | awk '$2==<arm64 sweep pid>'
 8290 Ss 03:15 0:00.76  ...        <- started 3 minutes AFTER the signal
18774 Ss 02:17 0:00.55  ...
19384 Ss 02:13 0:00.53  ...
19908 Ss 02:07 0:00.51  ...
20800 Ss 01:58 0:00.48  ...
(13 children in all; the oldest, at 9:56, predates the signal and is a build
 that was in flight, and every other one is younger than the signal)
```

A queue being drained, not work in flight: every one of those children is
younger than the signal, and each has a fresh start time with almost no CPU. A
second `SIGTERM` (the handler's documented "an operator who wants out NOW gets
out" path) killed both arms.

## The second half: work that is done is not reported

The builds the shutdown goes on to run **publish their verdicts to the CAS** —
`run_one` publishes before it returns — and then the run exits without ever
putting them in `results`. `_report_partial` reports
`{rel(p): results[p].cls for p in done}` where `done` is what `results` holds,
so:

* the partial ledger and the summary undercount by every file built during the
  shutdown; and
* those files' verdicts are in the CAS but invisible in the run's own output,
  so a reader comparing the log with the cache finds verdicts with no line.

That second half is why this session's numbers are reconstructed from the CAS
rather than read off the log — see
`bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §2.3, which reconstructs each
file's class by recomputing the cache key and re-running the classifier over the
stored verdict, exactly as a run does on a hit.

## The fix

Small, and it belongs where the handler already is:

```python
                if stop.is_set():
                    # An interrupted run must not go on to BUILD the rest of
                    # the scope: every file was submitted up front, so the
                    # queue is the whole run and `__exit__`'s shutdown(wait=True)
                    # would execute all of it. Cancel what has not started; the
                    # builds in flight finish, which is the wait the docstring
                    # already accepts.
                    ex.shutdown(wait=False, cancel_futures=True)
                    return True
```

`__exit__`'s own `shutdown(wait=True)` then joins only the `-j` builds that were
already running, so the exit is bounded by the slowest one rather than by the
rest of the scope. Two things to decide in the same change, and both are
judgement calls worth writing down rather than leaving to the next reader:

* **the delay that remains.** `cancel_futures=True` still waits for the builds in
  flight, because the process cannot exit while its own worker threads run
  (`concurrent.futures.thread._python_exit` joins them at exit). Making the exit
  prompt means keeping each build's `Popen` and `procrun.kill_group`-ing it, as
  the timeout path already does — a bigger change, and it kills work that may
  have been seconds from a verdict. The honest intermediate is what the fix
  above gives: stop building, keep the in-flight results, exit within one `-t`.
* **what the summary should say.** A run that stops printing but keeps building
  is in a state the tool has no name for. Either the builds during the shutdown
  are counted (they are done, and their verdicts are published) or the shutdown
  is quick enough that there are none to count.

## What to test

`test_formal_sweep.py::TestResultsSurviveAnInterruptedRun` is the class that
owns this behaviour. One case pins the fix without a slow sweep: patch
`S.ThreadPoolExecutor` (or `concurrent.futures.ThreadPoolExecutor` as the module
holds it) with a fake whose `shutdown` records its arguments, set the stop flag
the handler sets, and assert `shutdown` was called with `cancel_futures=True`.
One case pins the half that is NOT changed: a run that is not signalled still
classifies every file and still prints the summary.

## Cost of not fixing it

Every interrupted sweep on this machine pays for it twice: once in the CPU it
spends building files nobody asked for after it was told to stop, and once in
the numbers, because the report and the cache disagree. The 2026-10-01 arm64
sweep that was SIGKILLed (and the two runs this bug's predecessor session left
running, `bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §1.1) are the expensive
case: a SIGKILLed run cannot publish anything, so its partial work is lost even
though the builds themselves finished.