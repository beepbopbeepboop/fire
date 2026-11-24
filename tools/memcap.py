#!/usr/bin/env python3
"""Run a command under a total-footprint ceiling, killing it if it goes over.

Why this exists rather than `ulimit -v` / RLIMIT_AS: on macOS neither is a
usable cap. RLIMIT_AS bounds address space, which the allocator is entitled to
reserve without faulting, so it either does not fire at all or fires on a
reserve the process never touches; and the honest reason is simpler, which is
that there is no dependable way here to make the OS bound one job's memory.
macOS will not reliably choose which process to kill when memory runs out, so
a runaway is stopped by a human watching it, and this script exists to make
that human unnecessary.

It also does not have to be accurate to be useful. The measured healthy peak
for the self-hosted whole-transitive-closure self-compile is ~55 GB (RSS), and
a runaway reached 192 GB before being stopped, so the ratio between "fine" and
"ruining the machine" is about 3.5x. A ceiling does not need to be tight to
separate those; it needs to be enforced against a process *we* own, so that the
kill is aimed correctly. That is the whole trick, and it is why this works
where rlimit does not.

    tools/memcap.py --limit-gb 55 -- ./mojoc fire.py --dump-full

There is also a WALL-CLOCK limit, and it always applies. It defaults to 20
minutes, and a job that legitimately runs longer must name its own
`--time-limit-min` rather than get an unbounded run. There is no way to switch
it off: a run that outlives its limit is killed with its whole tree, the same
as a breach of the memory ceiling.

    tools/memcap.py --limit-gb 55 --time-limit-min 90 -- ./mojoc fire.py --dump-full

Exit codes:
    0/1/...   the command's own exit status, passed through unchanged
    124       the wall-clock limit was exceeded and the process tree was killed
    125       the ceiling was exceeded and the process tree was killed
    2         usage error

The measurement and the kill both live in `tools/procrun.py` rather than
here, because `tools/suite.py` needs the same two — to kill a job's whole tree
on a timeout, and to read a peak — and a second copy of the process-walk and
kill order is a second copy of the ways to get them wrong. That file documents
the two approximations in the number (the figure is summed over the process
TREE, and summing double-counts shared pages, so the cap reads high — the safe
direction).

The figure is `phys_footprint` (resident + compressed + swapped), NOT RSS.
macOS compresses and swaps cold dirty pages out of RSS, so a runaway can read
1-2 GB of RSS at 35 GB of real cost and sail under any RSS ceiling while the
machine swaps itself to death (2026-11-15). See "Footprint" in procrun.py.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procrun                                                   # noqa: E402
from procrun import GB                                           # noqa: E402

POLL_SECONDS = 0.5
# The wall-clock limit a run gets when its caller names none. Twenty minutes is
# long enough for the everyday jobs and short enough that a wedge is caught
# while someone is still watching; anything longer has to say so itself.
DEFAULT_TIME_LIMIT_MIN = 20.0
# macOS `ps` costs ~50-100ms, and a 3-minute run is ~360 samples. Sampling
# more finely than this buys nothing: memory does not move fast enough between
# samples for the 3.5x margin to matter.


def _on_term(signum, _frame):
    """SIGTERM/SIGINT: take the tree down and REPORT it, in the handler.

    Installed rather than left to the default disposition, and the reason is
    the shape of this file's own contract: every outcome memcap can have is a
    line it prints, and a caller reads them to decide what happened
    (`procrun.memcap_verdict`, `procrun.memcap_wrapper_died`). A SIGTERM's
    default action skips all of that — the wrapper dies mid-poll with its
    banner on stdout and nothing else, which reads to every reader as "the
    wrapper was killed by something that left no trace", AND leaves the
    workload running unmonitored, which is the exact failure the ceiling
    exists to prevent.

    Who sends one: `tools/control.py reap` (SIGTERM to leftovers in finished
    workers' trees) and any operator or watchdog with the pid. Measured
    2026-10-02: six files per architecture reported a bare
    `memcap: <label> -- ceiling …` as their `codegen` "refusal" in a sweep,
    with the killer not established. Whether or not that run was one of these,
    handling the signal removes a whole class of the state rather than
    explaining one instance of it — and SIGKILL, the only signal that cannot be
    handled, is the only thing that can still produce it.

    Raising `KeyboardInterrupt` rather than returning: the `except` clauses
    below already do the tree-kill and the reporting for it, and a signal
    handler that raises keeps the cleanup in ONE place instead of two.
    """
    raise KeyboardInterrupt(signum)


def main(argv):
    ap = argparse.ArgumentParser(
        prog="memcap", description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit-gb", type=float, default=55.0,
                    help="total memory-footprint ceiling for the process tree, in GB "
                         "(default 55.0, the measured healthy peak)")
    ap.add_argument("--time-limit-min", type=float, default=DEFAULT_TIME_LIMIT_MIN,
                    help="wall-clock limit for the command, in minutes (default %g). "
                         "A run that needs longer must pass its own number; it cannot "
                         "be made unlimited." % DEFAULT_TIME_LIMIT_MIN)
    ap.add_argument("--label", default=None,
                    help="what to call the command in progress output")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv[1:])

    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("no command given (try: memcap.py --limit-gb 55 -- ./cmd)")
    # A time limit must be a real, finite number. `<= 0` and NaN would both
    # either kill the job at once or never fire, and neither is a cap.
    if not (args.time_limit_min > 0) or args.time_limit_min == float("inf"):
        ap.error("--time-limit-min must be a positive, finite number of minutes "
                 "(got %r)" % args.time_limit_min)

    limit = int(args.limit_gb * GB)
    time_limit_s = args.time_limit_min * 60.0
    label = args.label or cmd[0]
    print("memcap: %s -- ceiling %.1f GB across the process tree, time limit %.1f min"
          % (label, args.limit_gb, args.time_limit_min), flush=True)
    started = time.monotonic()

    # `start_new_session` so the whole subtree is in one process group we can
    # signal as a unit. procrun.kill_tree's walk is the precise path; the
    # group kill is the belt-and-braces fallback for a pid we lose track of.
    proc = subprocess.Popen(cmd, start_new_session=True)
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Installed AFTER the child exists: a SIGTERM arriving before this point
        # would kill memcap with no tree to kill, which is the safe direction, and
        # the window is microseconds wide.
        signal.signal(sig, _on_term)
    peak, peak_n = 0, 0
    try:
        while True:
            rc = proc.poll()
            total, n = procrun.tree_rss(proc.pid)
            if total > peak:
                peak, peak_n = total, n
            if total > limit:
                pct = 100.0 * total / limit if limit else 0.0
                print("\nmemcap: BREACH  %.1f GB > %.1f GB ceiling (%d%%), "
                      "%d procs -- killing %s"
                      % (total / GB, args.limit_gb, pct, n, label), flush=True)
                print("memcap: peak observed before the kill: %.1f GB"
                      % (peak / GB), flush=True)
                procrun.kill_tree(proc.pid)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                print("memcap: this is a RESOURCE failure, not a verdict on "
                      "the thing under test -- the process was killed for "
                      "memory before it finished.", flush=True)
                return 125
            if rc is not None:
                print("memcap: done, peak %.1f GB across up to %d procs "
                      "(ceiling %.1f GB), child exit %d"
                      % (peak / GB, peak_n, args.limit_gb, rc), flush=True)
                return rc
            ran_s = time.monotonic() - started
            if ran_s > time_limit_s:
                print("\nmemcap: TIMEOUT  ran %.1f min > %.1f min time limit -- killing %s"
                      % (ran_s / 60.0, args.time_limit_min, label), flush=True)
                print("memcap: peak observed before the kill: %.1f GB"
                      % (peak / GB), flush=True)
                procrun.kill_tree(proc.pid)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                print("memcap: this is a TIME failure, not a verdict on the thing "
                      "under test -- the process was killed at its wall-clock "
                      "limit before it finished.", flush=True)
                return 124
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt as exc:
        # The tree goes down and the outcome is REPORTED, in that order: the
        # point of the handler is that a signalled wrapper is not a silent one,
        # and a reader (`procrun.memcap_accounted`) is looking for a line that
        # says how this run ended. 130 for an interrupt, 143 for a SIGTERM —
        # the conventional 128+signum, so a caller that reads the exit code sees
        # "terminated by a signal" rather than "exited 130" for the case that was
        # not an interactive interrupt. Both are handled by the same `except`,
# so which one it was is carried in the MESSAGE.
        signum = getattr(exc, "args", [None])[0]
        # The outcome WORD is `interrupted` and not `terminated`, and that is
        # load-bearing rather than a style choice: `procrun.memcap_accounted`
        # reads a run's end off a line beginning `memcap: interrupted`, and a
        # word outside its set would leave a signalled wrapper still reading as
        # a silent one — the state this handler exists to remove. The signal
        # number and the exit code carry which signal it was.
        how = ("interrupted" if signum in (None, 2)
               else f"interrupted by signal {int(signum)}")
        print(f"\nmemcap: {how}, killing {label} -- nothing below this "
              f"wrapper is left running, and this run was NOT accounted for by "
              f"any ceiling", flush=True)
        procrun.kill_tree(proc.pid)
        return 130 if signum in (None, 2) else 143
    except BaseException as exc:            # noqa: BLE001
        # Fail CLOSED. This is a safety tool, so a bug in the watchdog must
        # not leave an unbounded, unmonitored process running -- that is the
        # exact failure it exists to prevent, and an earlier version of this
        # file had precisely that bug (`out` instead of `out.stdout`), which
        # left a test hog running to 3 GB after the watchdog had died.
        print("\nmemcap: WATCHDOG FAILED (%r) -- killing %s rather than "
              "leaving it unmonitored" % (exc, label), flush=True)
        procrun.kill_tree(proc.pid)
        raise


if __name__ == "__main__":
    sys.exit(main(sys.argv))
