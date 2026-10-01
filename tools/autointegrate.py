#!/usr/bin/env python3
"""Run integration unattended, ONE BRANCH AT A TIME, passers first.

  1. SCREEN: every finished branch is merged ALONE onto the current master and run through the quick
     tier (integrate.QUICK: the self-host build + the fast jobs, minutes; `--jobs`, so nothing lands).
  2. LAND: the branches that passed, in priority order (`control.py priority`), each through the full gate
     before the next, so master moves one verified step at a time.
  3. FIX: the branches that failed their screen are not retried; each gets a fixer worker (once per
     head) carrying the failing jobs and the error excerpt.

Notes on why:  (Batching was tried first: a red round of eight branches says nothing about which one is bad,
conflicts between members spawn chains of merge fixes, and the set keeps changing so nothing lands.)

    autointegrate.py [--interval-min 10]

Every --interval-min it looks at the finished, clean, non-blocked branches (the integrator's own
`pick_candidates`) whose current head has not already been rejected.

Safeguards, because nobody is watching:
  * The integrator's own flock means a second round cannot start while one runs, and the gate's
    memory reservations (tools/memslot.py) queue it behind any other heavy job.
  * A branch that went RED is not retried until its head CHANGES (a new commit); a human/controller
    re-runs it after looking.
  * Conflicts are not left for a human: integrate.py enqueues a merge worker for each one and marks the
    conflicting task superseded, and the refill loop (control.py refill) starts it.
  * Master only ever moves by the integrator's fast-forward after a green full gate.
"""
import argparse, hashlib, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I

STATE = os.path.join(C.ctl_dir(), "autointegrate.json")


def log(msg):
    print("%s %s" % (time.strftime("%F %T"), msg), flush=True)


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"red_sets": []}


def head_sha(name):
    t = C.load()[name]
    return subprocess.run(["git", "rev-parse", "--short", t["branch"]], cwd=C.MAIN, capture_output=True, text=True).stdout.strip()


def run_integrate(*args):
    r = subprocess.run([sys.executable, os.path.join(C.MAIN, "tools", "integrate.py")] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def failed_jobs(tree_log):
    """The FAILED section of a suite/gate log, as text, for a fixer's task."""
    try:
        txt = open(tree_log, errors="replace").read()
    except OSError:
        return ""
    m = re.search(r"^FAILED:\n(.*?)(?=^[A-Z-]+.*:\n|^suite:)", txt, re.S | re.M)
    return (m.group(1) if m else "")[:1500].strip()


def enqueue_fixer(name, why):
    t = C.load()[name]
    if name.startswith("fix-screen-fix-screen-"):
        log("%s failed its screen again after two fix attempts: leaving it for a human" % name); return
    import argparse as _ap
    task = ("Branch %s (a finished worker branch; its task: %s) FAILS the integrator's quick tier ON ITS OWN, merged alone onto the "
            "current master. Failing jobs: %s. You start on the branch. Reproduce the failing job(s) narrowly (for the self-host "
            "build: python3 tools/memslot.py --gb 8 --label repro -- python3 fire.py build fire.py -o .tmp/mojoc; for the "
            "others run the named job's own test file, each under memslot --gb 8), find the change in the branch that causes it "
            "(`git diff master...HEAD`, bisect its commits), and fix it properly without losing what the branch delivers; the "
            "branch's own tests must still pass. Light worker: no gate. Never use git stash. Commit; finish with the REPORT block "
            "and a CONTROL-STATUS line. Excerpt of the failure:\n%s" % (t["branch"], t["summary"][:150], why.splitlines()[0] if why else "?", why))
    fname = "fix-screen-" + name
    if fname in C.load():
        fname += "-%d" % int(time.time() % 100000)
    C.cmd_enqueue(_ap.Namespace(name=fname[:60], claim=t["claims"] or ["task:" + fname], task=task, task_file=None, file=[],
                                base=t["branch"], needs=[], model=None))
    with C.registry() as reg:
        reg[name]["state"] = "superseded"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval-min", type=float, default=5, help="sleep this long only when there is nothing to do or the integrator is busy")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--screen", action="store_true",
                    help="screen each branch through the quick tier before the full gate (off by default: the full gate "
                         "contains the same jobs, so for a branch that passes the screen is pure added time)")
    a = ap.parse_args()
    while True:
        st = load_state()
        screen = st.setdefault("screen", {})
        busy = False
        # FAST LANE FIRST: test-infrastructure-only branches need no project gate (owner's policy) and cost minutes.
        for name in sorted(I.pick_candidates(quiet=True), key=C.priority_key):
            if name in I.pick_candidates(quiet=True) and I.infra_only(C.load()[name]["branch"]):
                log("%s touches only test infrastructure: fast lane (no project gate)" % name)
                rc, out = run_integrate("--only", name, "--fast")
                tail = [l for l in out.splitlines() if l.startswith(("GREEN", "RED", "NOT test", "CONFLICT", "merged", "fast lane"))]
                log("%s: rc=%d %s" % (name, rc, " | ".join(tail)[:300]))
                if "another integrator" in out:
                    busy = True; break
        # Then exactly ONE branch per iteration: the highest-priority eligible candidate, RE-CHOSEN each time (so a
        # priority change applies at once, and a branch that just landed or conflicted changes what is next).
        did = False
        if not busy:
            elig = [n for n in sorted(I.pick_candidates(quiet=True), key=C.priority_key)
                    if not I.infra_only(C.load()[n]["branch"])
                    and not (screen.get(n, {}).get("head") == head_sha(n) and not screen[n].get("pass"))]
            if elig:
                name = elig[0]; head = head_sha(name); did = True
                if a.screen and screen.get(name, {}).get("head") != head:
                    log("screening %s alone (quick tier)" % name)
                    rc, out = run_integrate("--only", name, "--jobs", *I.QUICK)
                    if "another integrator" in out:
                        busy = True
                    elif "--jobs run finished" not in out:
                        log("%s: did not reach the quick tier: %s" % (name, " | ".join(l for l in out.splitlines() if "CONFLICT" in l)[:200]))
                    else:
                        ok = rc == 0
                        screen[name] = {"head": head, "pass": ok, "why": "" if ok else failed_jobs(os.path.join(I.INTEG, "gate.log")), "t": time.time()}
                        json.dump(st, open(STATE, "w"))
                        log("%s: quick tier %s" % (name, "PASS" if ok else "FAIL"))
                elif not busy:
                    log("LANDING %s (merged alone onto master; full gate, failed jobs confirmed alone)" % name)
                    rc, out = run_integrate("--only", name)
                    tail = [l for l in out.splitlines() if l.startswith(("GREEN", "RED", "CONFLICT", "merged", "gate exited", "the red did NOT"))]
                    log("%s: rc=%d %s" % (name, rc, " | ".join(tail)[:400]))
                    if "another integrator" in out:
                        busy = True
                    elif rc != 0 and name in I.pick_candidates(quiet=True):     # red (a conflict supersedes the branch itself)
                        screen[name] = {"head": head_sha(name), "pass": False, "t": time.time(),
                                        "why": "full gate red: " + failed_jobs(os.path.join(I.INTEG, "gate.log"))}
                        json.dump(st, open(STATE, "w"))
        # A branch that failed on its own is handed to a fixer, once per head.
        for name in sorted(I.pick_candidates(quiet=True), key=C.priority_key):
            r = screen.get(name)
            if r and r["head"] == head_sha(name) and not r["pass"] and not I.infra_only(C.load()[name]["branch"]):
                log("%s failed on its own: queueing a fixer" % name)
                enqueue_fixer(name, r["why"])
        if a.once:
            return
        if busy or not did:
            time.sleep(a.interval_min * 60)


if __name__ == "__main__":
    main()
