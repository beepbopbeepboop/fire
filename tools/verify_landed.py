#!/usr/bin/env python3
"""The full gate, run once per interval on master, under the integrator's lock.

    verify_landed.py [--sha SHA] [--force]

The integrator lands on the cheap landing gate (tools/gates.json `landing`), so landings are not serialized behind the
full suite. The full suite (`suite.py gate`, minus every gate that is OFF) costs ~35 minutes, so it runs at most once
per `full_every_minutes` and never beside another suite run: it takes the SAME lock as the integrator (integrator.lock).
Its verdict goes to <common-git-dir>/control/verify.json. Each failing job becomes one fix task (`fix-gate-<job>`),
claimed by the job's name, so a red job is repaired once, not re-queued by every run."""
import argparse, fcntl, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

VERIFY = os.path.join(C.PARENT, "work-verify")
VERDICT = os.path.join(C.ctl_dir(), "verify.json")


def last_verdict():
    try:
        return json.load(open(VERDICT))
    except (OSError, ValueError):
        return {}


def due(force):
    cfg = C.gates_cfg()
    age = time.time() - last_verdict().get("epoch", 0)
    return force or age >= cfg["full_every_minutes"] * 60


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", default=None)
    ap.add_argument("--force", action="store_true", help="ignore the interval")
    a = ap.parse_args()
    if not due(a.force):
        print("full gate not due (last %s); next in %d min" % (last_verdict().get("at", "never"),
              int((C.gates_cfg()["full_every_minutes"] * 60 - (time.time() - last_verdict().get("epoch", 0))) / 60)))
        return 0
    lock = open(os.path.join(C.ctl_dir(), "integrator.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("the integrator is running a suite now; one suite run at a time: not due yet")
        return 0
    sha = a.sha or C.git("rev-parse", "master")
    if not os.path.isdir(VERIFY):
        C.git("worktree", "add", "--detach", VERIFY, sha)
    else:
        C.git("checkout", "-q", "--detach", sha, cwd=VERIFY)
    log = os.path.join(VERIFY, "verify-%s.log" % sha[:8])
    skips = C.gate_skip_args()
    cmd = ["python3", "tools/suite.py", "gate"] + skips
    t0 = time.time()
    with open(log, "w") as f:
        f.write("$ %s\n" % " ".join(cmd)); f.flush()
        rc = subprocess.run(cmd, cwd=VERIFY, stdout=f, stderr=subprocess.STDOUT).returncode
    txt = open(log, errors="replace").read()
    jobs = sorted(set(re.findall(r"^\s+FAIL\s+(\S+)", txt, re.M) + re.findall(r"^\[\s*\d+/\d+\] (?:TIMEOUT|ERROR|RESOURCE)\s+(\S+)", txt, re.M)))
    off = list(C.gates_cfg().get("off", {}))
    verdict = dict(sha=sha, ok=rc == 0 and not jobs, rc=rc, failed=jobs, gates_off=off, log=log,
                   secs=round(time.time() - t0), at=time.strftime("%F %T"), epoch=time.time())
    json.dump(verdict, open(VERDICT, "w"), indent=1)
    print("full gate %s: %s, %ds, log %s" % ("GREEN" if verdict["ok"] else "RED", ", ".join(jobs) or "rc=%d" % rc,
                                             verdict["secs"], log))
    for job in jobs:
        name = ("fix-gate-" + re.sub(r"[^a-z0-9]+", "-", job.lower()))[:60].rstrip("-")
        if name in C.load() or any(f == name + ".json" for f in os.listdir(C.qdir())):
            continue                      # already being worked or queued: one fix per job
        task = ("The full gate (%s) is red on master in job `%s`. Read the failing output in %s (search for %r). Find the "
                "root cause and fix it; a job that passes alone on master is a load problem, say so and stop. Narrow tests "
                "only (no gate: the integrator runs the suite once). Commit, clean tree, CONTROL-STATUS line."
                % (sha[:8], job, log, job))
        C.cmd_enqueue(argparse.Namespace(name=name, claim=["gate:" + job], task=task, task_file=None, file=[],
                                         base="master", needs=[], model=None, pool=None))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
