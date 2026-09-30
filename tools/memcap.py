#!/usr/bin/env python3
"""Run a command under a total-RSS ceiling, killing it if it goes over.

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

Exit codes:
    0/1/...   the command's own exit status, passed through unchanged
    125       the ceiling was exceeded and the process tree was killed
    2         usage error

The measurement and the kill both live in `tools/procrun.py` rather than
here, because `tools/suite.py` needs the same two — to kill a job's whole tree
on a timeout, and to read a peak — and a second copy of the process-walk and
kill order is a second copy of the ways to get them wrong. That file documents
the two approximations in the number (RSS is summed over the process TREE, and
summing double-counts shared pages, so the cap reads high — the safe
direction).
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
# macOS `ps` costs ~50-100ms, and a 3-minute run is ~360 samples. Sampling
# more finely than this buys nothing: RSS does not move fast enough between
# samples for the 3.5x margin to matter.


def main(argv):
    ap = argparse.ArgumentParser(
        prog="memcap", description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit-gb", type=float, default=55.0,
                    help="total RSS ceiling for the process tree, in GB "
                         "(default 55.0, the measured healthy peak)")
    ap.add_argument("--label", default=None,
                    help="what to call the command in progress output")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv[1:])

    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("no command given (try: memcap.py --limit-gb 55 -- ./cmd)")

    limit = int(args.limit_gb * GB)
    label = args.label or cmd[0]
    print("memcap: %s -- ceiling %.1f GB across the process tree"
          % (label, args.limit_gb), flush=True)

    # `start_new_session` so the whole subtree is in one process group we can
    # signal as a unit. procrun.kill_tree's walk is the precise path; the
    # group kill is the belt-and-braces fallback for a pid we lose track of.
    proc = subprocess.Popen(cmd, start_new_session=True)
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
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nmemcap: interrupted, killing %s" % label, flush=True)
        procrun.kill_tree(proc.pid)
        return 130
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
