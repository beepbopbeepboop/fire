#!/usr/bin/env python3
"""Process-tree inspection, killing, and supervised spawning — shared.

This exists because two callers need the *same* answer to questions that are
easy to get subtly wrong, and a third (`tools/memcap.py`) is a safety tool
whose whole value is that its kill is aimed correctly:

  * `tools/suite.py` needs to kill a runaway job's whole tree on a timeout,
    and to read what the job printed.
  * `tools/memcap.py` needs to measure a tree's RSS and kill it at a ceiling.
  * `tools/ab_run_one.py` and `tools/suite.py` need to read that ceiling run's
    verdict — the peak it saw, and whether it was the ceiling that stopped it —
    so a per-file A/B job and a whole suite test report a memory kill the same
    way. `memcap_verdict` is that reader.
  * `formal/lean.py`'s launcher needs the other two columns of the same table:
    a process's CUMULATIVE CPU (a wall bound alone does not stop a process
    burning every core it can find, and `RLIMIT_CPU` charges each descendant
    separately rather than the tree), and the PROCESS GROUP (the handle that
    still finds a descendant whose parent has been killed and reparented to
    init — which is what a `SIGXCPU` from inside the process leaves behind).

Duplicating the process-table walk and the kill order in both would be exactly
the failure this file prevents. There was a real instance of it: an earlier
memcap had a bug in its watchdog and left a test hog running to 3 GB *after*
the monitor had already died, and the only reason that was noticed is that a
human happened to look. One implementation, used by both, with the reasoning
next to it.

Two facts about this platform shape the whole file:

- **macOS will not reliably choose what to kill when memory runs out.** So a
  runaway is stopped by aiming a SIGKILL at a process we spawned ourselves,
  which is deterministic, rather than by relying on the OS, which is not. It
  also means `ulimit`/RLIMIT_AS is not a substitute: it bounds address space,
  which the allocator may reserve without ever faulting, so it either never
  fires or fires on a reservation that costs nothing.
- **`ps` is the only process table available here**, and it costs ~50-100ms.
  That is why POLL_SECONDS is not smaller: RSS does not move meaningfully
  between samples.

Signals are SIGKILL, never SIGTERM. Every caller of the kill path is killing
something that is already in a state where cooperative shutdown is not
arriving — that is the reason the ceiling and the timeout exist — so a TERM
that gets ignored is the same as no TERM at all.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import threading

GB = 1024 ** 3


# ── The process table ────────────────────────────────────────────────────────
def ps_table():
    """`(ppid, rss)` dicts for every process — the two columns most callers want.

    rss is in KB, as macOS `ps` reports it. See `ps_snapshot` for what is
    returned when `ps` is unavailable, which is the same here.
    """
    ppid, rss, _cpu, _pgid = ps_snapshot()
    return ppid, rss


def ps_snapshot():
    """`(ppid, rss, cpu, pgid)` dicts for every process, from ONE `ps` call.

    `cpu` is CUMULATIVE CPU SECONDS across every thread (macOS `ps`'s `time`
    column, which is user+sys and so already answers "all threads"), and `pgid`
    is the process group — the only handle left on a descendant whose parent has
    been killed and reparented to init, which is exactly the case a tree walk
    cannot find and a group kill can.

    All four come from one call because `ps` is the expensive part (~50-100ms
    on this platform), not the parsing: a poller that wanted CPU and RSS could
    otherwise only have one of them per `ps`, or pay two.

    Returns empty dicts if `ps` is unavailable or times out — callers treat that
    as "no information", never as "zero", so a missing sample can never read as
    a healthy one.
    """
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,ppid=,rss=,time=,pgid="],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}, {}, {}, {}
    ppid, rss, cpu, pgid = {}, {}, {}, {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            pid, parent, resident = (int(x) for x in parts[:3])
            spent = ps_time(parts[3])
            group = int(parts[4])
        except ValueError:
            continue
        ppid[pid] = parent
        rss[pid] = resident
        cpu[pid] = spent
        pgid[pid] = group
    return ppid, rss, cpu, pgid


def ps_time(s):
    """macOS `ps`'s `time`/`etime` field in seconds. `[[dd-]hh:]mm:ss[.ff]`.

    One parser for the two spellings and the three shapes, because the day a
    process has been up long enough to need the day field is exactly the day a
    runaway's CPU figure stops fitting in an int and the guard that reads it
    either raises or reads `None`. Also used for `etime` (wall clock), which has
    the same grammar.
    """
    days = 0.0
    if "-" in s:
        d, s = s.split("-", 1)
        try:
            days = float(d)
        except ValueError:
            return 0.0
    parts = s.split(":")
    try:
        nums = [float(x) for x in parts]
    except ValueError:
        return 0.0
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return days * 86400 + nums[0] * 3600 + nums[1] * 60 + nums[2]


def _children(ppid):
    kids = {}
    for pid, parent in ppid.items():
        kids.setdefault(parent, []).append(pid)
    return kids


def tree_pids(root, ppid=None):
    """`root` and every descendant, parents before children."""
    if ppid is None:
        ppid, _ = ps_table()
    if root not in ppid:
        return []
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        out.append(pid)
        stack.extend(_children(ppid).get(pid, ()))
    return out


def tree_rss(root, ppid=None, rss=None):
    """`(bytes, n_procs)` for `root`'s whole subtree — the RSS half of
    `tree_usage`, which is the general form."""
    _cpu, total, count = tree_usage(root, ppid, rss)
    return total, count


def tree_usage(root, ppid=None, rss=None, cpu=None):
    """`(cpu_seconds, bytes, n_procs)` for `root`'s whole subtree.

    The tree, not the process: `mojoc` spawns `gcc -fgimple` children, and a
    measurement that ignored them would let the real cost hide in a child.  For
    CPU that is not tidiness but the whole point — a child's CPU is NOT charged
    to its parent by `RLIMIT_CPU` (each process gets its own limit), so a
    launcher that wants "this run did not burn more than N CPU-seconds" has to
    sum the tree itself.

    Summing RSS also double-counts pages shared between processes (chiefly the
    copy-on-write runtime image), so the true total is somewhat *below* this
    figure — which makes a ceiling read high rather than low, the safe
    direction: it errs toward killing early.

    A caller that passes `ppid`/`rss` from its own snapshot but leaves `cpu` at
    `None` gets 0.0 CPU seconds, because there is no table to read them from;
    `ps_snapshot` hands out all four together so that cannot happen by accident.
    """
    if ppid is None or rss is None:
        ppid, rss, cpu, _pgid = ps_snapshot()
    if root not in ppid:
        return (0.0, 0, 0)
    kids = _children(ppid)
    spent, total, count, stack = 0.0, 0, 0, [root]
    while stack:
        pid = stack.pop()
        count += 1
        spent += (cpu or {}).get(pid, 0.0)
        total += rss.get(pid, 0)
        stack.extend(kids.get(pid, ()))
    return (spent, total * 1024, count)


def group_pids(pgid, skip=(), tables=None):
    """Live pids in one process GROUP, minus `skip`.

    The handle that survives the parent. `tree_pids` walks ppid, so it finds
    nothing once the parent is gone and the children have been reparented to
    init — which is precisely the state a `RLIMIT_CPU` SIGXCPU leaves behind,
    because the limit is enforced inside the process it applies to and the
    launcher never gets to choose the moment. A process group, by contrast, is
    inherited by every descendant and outlives the process that created it, so
    this is how a caller discovers that the elaboration it bounded left a
    compiler running.
    """
    ppid, _rss, _cpu, pgids = tables if tables is not None else ps_snapshot()
    skip = set(skip)
    return [pid for pid, group in pgids.items()
            if group == pgid and pid not in skip and pid != os.getpid()]


# ── Killing ──────────────────────────────────────────────────────────────────
def kill_tree(root, table=None):
    """SIGKILL `root`'s whole subtree, children first, then reap `root`.

    Children first matters because the memory is in the children: `mojoc`'s
    `gcc` processes hold most of it, and killing the parent first would leave
    them running and keep the allocation the kill was meant to release.
    """
    ppid = table if table is not None else ps_table()[0]
    pids = tree_pids(root, ppid)
    for pid in reversed(pids):                     # children before parents
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.waitpid(root, 0)
    except (ChildProcessError, OSError):
        pass


def kill_group(proc: subprocess.Popen):
    """SIGKILL a Popen's whole process TREE, then its group, then reap it.

    The walk comes FIRST, and it is not belt-and-braces: it is the only part
    that reaches a nested wrapper's children. `tools/memcap.py` starts the
    command it supervises with `start_new_session=True` (so it can signal the
    subtree as a unit), which puts that subtree in a process group of its own
    — so a group kill aimed at the wrapper's group stops AT the wrapper. Since
    every capped job is `memcap <workload>`, a timeout that only killed the
    group would SIGKILL memcap and leave the real workload running,
    unmonitored, still allocating: exactly the runaway the ceiling exists to
    prevent, re-created by the mechanism meant to stop it. Walking `ps` while
    the parent is still alive is what makes the ppid chain available at all,
    and `kill_tree` already kills children before parents, so the memory is
    released before the process holding it dies.

    The group kill stays, for the pid that arrives between the walk and the
    reap, and as the path that works when `ps` is unavailable.
    """
    kill_tree(proc.pid)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


# ── Reading a memcap run's verdict ──────────────────────────────────────────
# One parser, two callers: `tools/suite.py` needs the peak of every job it
# runs (which is how a job's measured peak gets into the log and the run's
# summary) and needs to tell "the child exited 125" from "memcap killed it";
# `tools/ab_run_one.py` needs the same two facts per A/B file, to record a
# memory kill in its meta.json rather than reporting it as a compiler failure.
# Both are the same two lines of memcap's output, so they are parsed here
# rather than twice.
_MEMCAP_PEAK = re.compile(r'peak (?:observed before the kill: )?([\d.]+) GB')
_MEMCAP_BREACH = 'memcap: BREACH'


def memcap_verdict(text):
    """`(breached, peak_gb)` from a memcap-wrapped run's output.

    `breached` is read from memcap's own words rather than from exit code 125,
    because exit 125 is only memcap's while the wrapper is the one that
    started the child: a workload that exits 125 by itself is a workload that
    failed, and calling that a memory cap is how a real failure gets filed
    under a machine problem. A run whose output carries no memcap lines at all
    (a `checked_run` cache hit, which never starts the child) is not a breach.

    `peak_gb` is None when memcap printed nothing measurable.
    """
    text = text or ''
    found = _MEMCAP_PEAK.findall(text)
    return (_MEMCAP_BREACH in text, float(found[-1]) if found else None)


# ── A bounded capture buffer ─────────────────────────────────────────────────
class Tail:
    """The last `limit` bytes of a stream, in order.

    A test's verdict can depend on what it printed — `mojo_unsupported_iter` is
    a real codegen gap that does NOT abort the compiler — so the runner keeps
    the output even when it is streaming it live. Bounded, because a runaway
    40 MB dump per parallel job would otherwise be the runner's own memory
    problem.
    """
    __slots__ = ('limit', '_chunks', '_size')

    def __init__(self, limit=4 << 20):
        self.limit, self._chunks, self._size = limit, [], 0

    def append(self, data: bytes):
        self._chunks.append(data)
        self._size += len(data)
        while self._size > self.limit and len(self._chunks) > 1:
            self._size -= len(self._chunks.pop(0))

    def text(self) -> str:
        return b''.join(self._chunks).decode('utf-8', 'replace')


class Run:
    __slots__ = ('rc', 'out', 'timed_out')

    def __init__(self, rc, out, timed_out):
        self.rc, self.out, self.timed_out = rc, out, timed_out


def spawn(argv, cwd=None, env=None, timeout=None, stream=False,
          keep_bytes=4 << 20, on_start=None):
    """Run argv to completion, capturing its combined output.

    stream=True prints each chunk to our stdout as it arrives (and still keeps
    a bounded copy, per `Tail`); otherwise the output goes to a temp file, so
    a test that prints without limit cannot grow the runner's own memory.

    The child gets its own process group (`start_new_session`), so a timeout
    can take the whole tree down rather than orphaning a `gcc` child.

    `on_start(child_pid)` is called with the child's pid as soon as it has
    been started, i.e. while it is alive. `tools/suite.py` uses it to record
    the pid on its memory-ledger reservation, so that a reservation survives
    the death of the process that took it for exactly as long as the job it
    started is still running.

    Returns a `Run`; `rc` is None when `timed_out`.
    """
    stream = stream or False
    if stream:
        return _spawn_stream(argv, cwd, env, timeout, keep_bytes, on_start)
    with tempfile.TemporaryFile(mode='w+b') as buf:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=buf,
                             stderr=subprocess.STDOUT, start_new_session=True)
        if on_start:
            on_start(p.pid)
        try:
            rc = p.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            kill_group(p)
            rc, timed_out = None, True
        buf.seek(0)
        out = buf.read().decode('utf-8', 'replace')
    return Run(rc, out, timed_out)


def _spawn_stream(argv, cwd, env, timeout, keep_bytes, on_start=None):
    keep = Tail(keep_bytes)
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    if on_start:
        on_start(p.pid)

    def pump():
        for chunk in iter(lambda: p.stdout.read(4096), b''):
            sys.stdout.write(chunk.decode('utf-8', 'replace'))
            sys.stdout.flush()
            keep.append(chunk)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        rc = p.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        kill_group(p)
        rc, timed_out = None, True
    t.join(timeout=5)
    return Run(rc, keep.text(), timed_out)
