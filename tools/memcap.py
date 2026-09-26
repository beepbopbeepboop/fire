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

Two approximations, both stated because they affect how much the number means:

- RSS is summed over the process TREE, not the process alone. `mojoc` spawns
  `gcc -fgimple` subprocesses, and a cap that ignored them would let the real
  cost hide in a child.
- Summing RSS double-counts pages shared between processes (the copy-on-write
  runtime image, chiefly), so the true total is somewhat below this figure.
  That makes the cap read high rather than low, which is the safe direction:
  it errs toward killing early.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

GB = 1024 ** 3
POLL_SECONDS = 0.5
# macOS `ps` costs ~50-100ms, and a 3-minute run is ~360 samples. Sampling
# more finely than this buys nothing: RSS does not move fast enough between
# samples for the 3.5x margin to matter.


def _ppid_rss_by_pid():
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,ppid=,rss="],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}, {}
    ppid, rss = {}, {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            try:
                pid, parent, resident = (int(x) for x in parts)
            except ValueError:
                continue
            ppid[pid] = parent
            rss[pid] = resident
    return ppid, rss


def _tree_rss(root):
    """`(bytes, n_procs)` for `root` and everything under it."""
    ppid, rss = _ppid_rss_by_pid()
    if root not in ppid:
        return (0, 0)
    kids = {}
    for pid, parent in ppid.items():
        kids.setdefault(parent, []).append(pid)
    total, count, stack = 0, 0, [root]
    while stack:
        pid = stack.pop()
        count += 1
        total += rss.get(pid, 0)
        stack.extend(kids.get(pid, ()))
    return (total * 1024, count)


def _kill_tree(root):
    """SIGKILL the subtree, children first, then reap.

    SIGKILL rather than SIGTERM: the ceiling exists precisely because the
    process is in a state where cooperative shutdown is not arriving, and a
    TERM that a runaway ignores is the same as no TERM. Killing children
    before the parent matters because `mojoc`'s `gcc` children hold their own
    RSS — leaving them running would keep most of the memory allocated after
    the parent is gone.
    """
    ppid, _ = _ppid_rss_by_pid()
    kids = {}
    for pid, parent in ppid.items():
        kids.setdefault(parent, []).append(pid)
    order, stack = [], [root]
    while stack:
        pid = stack.pop()
        order.append(pid)
        stack.extend(kids.get(pid, ()))
    for pid in reversed(order):                      # children before parents
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.waitpid(root, 0)
    except (ChildProcessError, OSError):
        pass


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
    # signal as a unit. The `_kill_tree` walk is the precise path; the group
    # kill is the belt-and-braces fallback for a pid we lose track of.
    proc = subprocess.Popen(cmd, start_new_session=True)
    peak, peak_n = 0, 0
    try:
        while True:
            rc = proc.poll()
            total, n = _tree_rss(proc.pid)
            if total > peak:
                peak, peak_n = total, n
            if total > limit:
                pct = 100.0 * total / limit if limit else 0.0
                print("\nmemcap: BREACH  %.1f GB > %.1f GB ceiling (%d%%), "
                      "%d procs -- killing %s"
                      % (total / GB, args.limit_gb, pct, n, label), flush=True)
                print("memcap: peak observed before the kill: %.1f GB"
                      % (peak / GB), flush=True)
                _kill_tree(proc.pid)
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
        _kill_tree(proc.pid)
        return 130
    except BaseException as exc:            # noqa: BLE001
        # Fail CLOSED. This is a safety tool, so a bug in the watchdog must
        # not leave an unbounded, unmonitored process running -- that is the
        # exact failure it exists to prevent, and an earlier version of this
        # file had precisely that bug (`out` instead of `out.stdout`), which
        # left a test hog running to 3 GB after the watchdog had died.
        print("\nmemcap: WATCHDOG FAILED (%r) -- killing %s rather than "
              "leaving it unmonitored" % (exc, label), flush=True)
        _kill_tree(proc.pid)
        raise


if __name__ == "__main__":
    sys.exit(main(sys.argv))
