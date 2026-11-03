#!/usr/bin/env python3
"""The fleet's only record of processes it may signal, and the only code that signals them.

RULE. The fleet signals a process only when that process is recorded here: a worker it spawned (cpu_cap wrap of
the worker's `opencode`/`claude`), in the process group the spawn created. Nothing is matched by working directory,
command name, or port. A process started by anyone else, including a user's own opencode session, a claim the user
made, or a session a user is driving, is never signalled, whatever directory it runs in.

KILL. A group is signalled SIGTERM first, so the workload can flush and save. SIGKILL only if the group is still
alive after GRACE seconds. A group whose leader has exited is NOT signalled: its members are logged and left alone,
because a recycled pid could make an unrelated process look like ours.

LOG. Every spawn is appended to spawned.jsonl; every signal, every skip and every refusal is appended to kills.log.
"""
import json, os, signal, subprocess, time

GRACE_S = 20
SPAWN_LEDGER = "spawned.jsonl"
KILL_LOG = "kills.log"


def _now():
    return time.strftime("%F %T")


def _log(ctl_dir, msg):
    line = "%s %s" % (_now(), msg)
    with open(os.path.join(ctl_dir, KILL_LOG), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def _lstart(pid):
    """Start time of `pid` as ps prints it, or None if no such process. Pins a pid to one process."""
    r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip() or None


def group_members(pgid):
    """(pid, command) of every LIVE process in process group `pgid`. A zombie (exited, not yet reaped by its parent)
    is not live: signalling a group that holds one fails with EPERM on macOS, and it has nothing left to save."""
    out = subprocess.run(["ps", "-axww", "-o", "pid=,pgid=,stat=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[1] == str(pgid) and not parts[2].startswith("Z"):
            rows.append((int(parts[0]), parts[3] if len(parts) > 3 else ""))
    return rows


def _signal_group(ctl_dir, pgid, sig, task):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as e:
        _log(ctl_dir, "FAILED task=%s pgid=%d signal=%d: %s" % (task, pgid, sig, e))
        return False


def record_spawn(ctl_dir, task, pid, worktree, argv):
    """Called right after the fleet starts a worker. Records the pid, its process group and its start time."""
    pgid = os.getpgid(pid)
    entry = {"task": task, "pid": pid, "pgid": pgid, "lstart": _lstart(pid), "worktree": worktree,
             "argv": [str(x) for x in argv[:3]], "at": _now()}
    with open(os.path.join(ctl_dir, SPAWN_LEDGER), "a") as f:
        f.write(json.dumps(entry) + "\n")
    _log(ctl_dir, "spawn task=%s pid=%d pgid=%d lstart=%s" % (task, pid, pgid, entry["lstart"]))
    return entry


def entries(ctl_dir, task=None):
    path = os.path.join(ctl_dir, SPAWN_LEDGER)
    if not os.path.exists(path):
        return []
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return [e for e in rows if task is None or e["task"] == task]


def _leader_is_ours(e):
    """True only if the recorded leader is still alive AND is the very process that was recorded (same start time)."""
    return e["lstart"] is not None and _lstart(e["pid"]) == e["lstart"]


def kill_group(ctl_dir, task, reason, grace=GRACE_S):
    """Signal the process groups recorded for `task`. Returns the list of pgids signalled."""
    signalled = []
    for e in entries(ctl_dir, task):
        members = group_members(e["pgid"])
        if not members:
            continue
        if not _leader_is_ours(e):
            _log(ctl_dir, "REFUSED task=%s pgid=%d: the recorded leader pid %d is gone or is not the process recorded; "
                          "%d member(s) left alone: %s" % (task, e["pgid"], e["pid"], len(members),
                                                         "; ".join("%d %s" % (p, c[:60]) for p, c in members)))
            continue
        _log(ctl_dir, "TERM task=%s pgid=%d reason=%s members=%s" % (
            task, e["pgid"], reason, "; ".join("%d %s" % (p, c[:60]) for p, c in members)))
        if not _signal_group(ctl_dir, e["pgid"], signal.SIGTERM, task):
            continue
        signalled.append(e["pgid"])
        deadline = time.time() + grace
        while time.time() < deadline and group_members(e["pgid"]):
            time.sleep(1)
        left = group_members(e["pgid"])
        if left:
            _log(ctl_dir, "KILL task=%s pgid=%d (still alive after %ds of TERM) members=%s" % (
                task, e["pgid"], grace, "; ".join("%d %s" % (p, c[:60]) for p, c in left)))
            _signal_group(ctl_dir, e["pgid"], signal.SIGKILL, task)
        else:
            _log(ctl_dir, "EXITED task=%s pgid=%d after TERM" % (task, e["pgid"]))
    return signalled


def group_rss_kb(pgid):
    """Resident size of the members of a group, in KiB."""
    out = subprocess.run(["ps", "-axww", "-o", "pgid=,rss="], capture_output=True, text=True).stdout
    total = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(pgid):
            total += int(parts[1])
    return total
