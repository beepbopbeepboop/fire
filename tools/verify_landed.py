#!/usr/bin/env python3
"""The full gate, run on a pinned commit of master in its own worktree whenever a landing since the last run needs one.

    verify_landed.py [--sha SHA] [--force]

The integrator lands on the cheap landing gate (tools/gates.json `landing`), so landings are not serialized behind the
full suite. The full suite (`suite.py gate`, minus every gate that is OFF) costs ~35 minutes and runs as long as at
least one first-parent commit since the last run touches something a gate reads (gate_ledger.pending): docs and the
orchestration tools do not count. The gate takes HOURS, so it must not hold anything the integrator needs: it runs in
../work-verify on the sha master had when it started (master marches on meanwhile, and landings continue), under its OWN
lock (verify.lock: one verifier at a time). Only the short step that lands its ledger commit takes the integrator lock.
Machine memory is bounded by memslot as for every suite run. Runs are spaced by gates.json `full_every_minutes`
(measured from the end of the last one). Its verdict goes to <common-git-dir>/control/verify.json and the per-job history to gate_ledger.json.

What a run does with its findings (gate_ledger.py):
  * a job red now that was green in the previous run is bisected over the commits between the two runs, so its report
    names the last commit it worked on and the first it did not;
  * that report is the `## Gate ledger` section of bugs/gate-<job>.md, and the job's registration in tools/suite.py
    gets `disabled='bugs/gate-<job>.md'`, so the job costs the gate no time while it is worked (the doc is the switch:
    the fixer who fixes it deletes the doc and the marker together);
  * a job that was red and passes again (the fixer re-enabled it) loses any leftover marker and doc; one that is
    re-enabled and still red is disabled again;
  * the marker/doc edits are one commit on branch `verify-ledger`, landed on master: fast-forwarded when master has not
    moved, otherwise merged onto the master of the day (it touches only suite.py markers and bugs/gate-*.md docs); a
    conflict leaves it on the branch.
Each failing job also becomes one fix task (`fix-gate-<job>`), claimed by the job's name, so a red job is repaired once,
not re-queued by every run."""
import argparse, fcntl, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import gate_ledger as G
import stash_ff as SF

VERIFY = os.path.join(C.PARENT, "work-verify")
VERDICT = os.path.join(C.ctl_dir(), "verify.json")


def last_verdict():
    try:
        return json.load(open(VERDICT))
    except (OSError, ValueError):
        return {}


def due(force, tip=None):
    """The commits that make a run due: those since the last run that touch something a gate reads."""
    if force:
        return [("forced", "")]
    return G.pending(last_verdict().get("sha"), tip or C.git("rev-parse", "master"))


def passed_jobs(tree):
    """Jobs the run saw PASS, from the suite's own log (build/suite.log: one PASS line per job)."""
    try:
        txt = open(os.path.join(tree, "build", "suite.log"), errors="replace").read()
    except OSError:
        return []
    return sorted(set(re.findall(r"^\[\s*\d+/\d+\] PASS\s+(\S+)", txt, re.M)))


def checkout(sha):
    """Put the verify tree on SHA. Nobody edits this tree, but something did (2026-11-12: a stray hand-edit of
    formal/build.py made `git checkout` abort, and the full gate silently did not run for 8 days while 239 landings
    piled up). So uncommitted tracked edits are SAVED as a patch under .git/control/ first (never lost), then the tree
    is reset: the verifier owns it, and a gate result on a tree with someone's edits in it would not be a result on SHA."""
    if C.git("status", "--porcelain", "--untracked-files=no", cwd=VERIFY, check=False):
        patch = os.path.join(C.ctl_dir(), "verify-dirty-%s.patch" % time.strftime("%Y%m%d-%H%M%S"))
        diff = subprocess.run(["git", "diff", "HEAD"], cwd=VERIFY, capture_output=True, text=True).stdout
        with open(patch, "w") as f:
            f.write(diff)
        print("verify tree %s had uncommitted edits: saved to %s (git apply to restore), tree reset" % (VERIFY, patch), flush=True)
        C.git("reset", "-q", "--hard", cwd=VERIFY)
    C.git("checkout", "-q", "--detach", sha, cwd=VERIFY)


def job_is_red_at(job, sha):
    """Does suite JOB fail at SHA? One job, alone, in the verify worktree."""
    checkout(sha)
    return subprocess.run(["python3", "tools/suite.py", job], cwd=VERIFY, capture_output=True).returncode != 0


def bisect_job(job, e, sha):
    """Fill e["first_bad"] (and bisect_note) for a job that is red at SHA, between its last_good and SHA."""
    if not e.get("last_good"):
        e["bisect_note"] = "no earlier full-gate run had this job green"
        return
    commits = G.commits_between(e["last_good"], sha, cwd=VERIFY)
    if not commits:
        e["bisect_note"] = "last_good is not an ancestor of the run"
        return
    e["first_bad"], probes = G.first_bad(commits, lambda c: job_is_red_at(job, c))
    e["bisect_note"] = "%d commit(s) between the runs, %d probe(s)" % (len(commits), probes)


def subject(sha):
    return C.git("log", "-1", "--format=%s", sha, check=False) or "(not in this repository)"


def write_doc(job, e, sha, log):
    """bugs/gate-<job>.md in VERIFY: created if absent, and its `## Gate ledger` section replaced if present."""
    p = os.path.join(VERIFY, "bugs", "gate-%s.md" % job)
    sect = G.report_text(job, e, sha, log, subject)
    if os.path.exists(p):
        txt = open(p).read()
        m = re.search(r"^## Gate ledger\n.*?(?=^## |\Z)", txt, re.S | re.M)
        if m:
            rest = txt[m.end():]
            txt = txt[:m.start()] + sect + ("\n" + rest if rest.strip() else "")
        else:
            txt = txt.rstrip() + "\n\n" + sect
    else:
        txt = ("# Gate: %s is red on master\n\n**Job:** `%s`. Filed by the full gate at `%s`.\n"
               "**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green "
               "on master.\n\nReproduce on master (`python3 tools/suite.py %s`), then fix the cause.\n\n%s"
               % (job, job, sha[:10], job, sect))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(txt)


def apply_findings(st, newly, recovered, sha, log, failed=()):
    """Marker and doc edits for this run as one commit on `verify-ledger`, landed on master when it has not moved.
    Returns the commit sha or None."""
    C.git("switch", "-q", "-C", "verify-ledger", sha, cwd=VERIFY)
    sp = os.path.join(VERIFY, "tools", "suite.py")
    src = open(sp).read()
    notes = []
    # A job that is red AND runs is one a fixer re-enabled without finishing: it is skipped again, history kept.
    again = [j for j in failed if j not in newly and st["jobs"].get(j, {}).get("red") and not G.get_disabled(src, j)]
    for j in list(newly) + again:
        e = st["jobs"][j]
        out = G.set_disabled(src, j)
        e["marked"] = G.get_disabled(out, j) is not None
        src = out
        write_doc(j, e, sha, log)
        notes.append("%s: first bad %s, last good %s" % (j, (e.get("first_bad") or "?")[:10], (e.get("last_good") or "?")[:10]))
    for j in recovered:
        src = G.drop_disabled(src, j)
        d = os.path.join(VERIFY, "bugs", "gate-%s.md" % j)
        if os.path.exists(d) and "## Gate ledger" in open(d).read():
            C.git("rm", "-q", "-f", os.path.relpath(d, VERIFY), cwd=VERIFY)
        notes.append("%s: green again, marker and doc removed" % j)
    open(sp, "w").write(src)
    C.git("add", "-A", "tools/suite.py", "bugs", cwd=VERIFY)
    if not C.git("diff", "--cached", "--name-only", cwd=VERIFY):
        return None
    C.git("commit", "-q", "-m", "gate ledger: %d red, %d recovered at %s\n\n%s\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
          % (len(newly), len(recovered), sha[:10], "\n".join(notes)), cwd=VERIFY)
    new = C.git("rev-parse", "HEAD", cwd=VERIFY)
    if land_ledger(new, sha):
        return new
    for j in list(newly) + again:
        st["jobs"][j]["marked"] = False
    return None


def integrator_lock(wait_s=900):
    """The integrator's lock, WAITED for (the verifier runs for hours and must not hold it; it needs it only for the
    moment its ledger commit moves master). Returns the open lock file, or None if it could not be had in WAIT_S."""
    lock = open(os.path.join(C.ctl_dir(), "integrator.lock"), "w")
    end = time.time() + wait_s
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except OSError:
            if time.time() > end:
                lock.close()
                return None
            time.sleep(5)


def land_ledger(new, sha, wait_s=900):
    """Move master to include the ledger commit NEW (built on SHA, the commit the gate ran on). A gate takes hours, so
    master has almost always moved since SHA: then the commit is MERGED onto the master of the day, which is safe because
    it touches only suite.py's `disabled=` markers and bugs/gate-*.md docs; a conflict leaves it on branch verify-ledger.
    The integrator lock is held only for this step."""
    lock = integrator_lock(wait_s)
    if lock is None:
        print("ledger commit %s NOT landed: the integrator lock was busy for %ds; it stays on branch verify-ledger" % (new[:10], wait_s))
        return False
    try:
        if C.git("rev-parse", "master", cwd=C.MAIN) == sha:
            st, detail = SF.merge(C.MAIN, "--ff-only", "verify-ledger")
        else:
            st, detail = SF.merge(C.MAIN, "--no-edit", "-m", "gate ledger: merged onto the master of the day (the gate ran at %s)" % sha[:10],
                                  "verify-ledger")
        if st == "ok":
            return True
        print("ledger commit %s NOT landed (%s: %s); it stays on branch verify-ledger" % (new[:10], st, detail[:160]))
        return False
    finally:
        lock.close()


def verify_lock():
    """One verifier at a time, on its OWN lock: the integrator keeps landing while a gate runs. None if one is running."""
    lock = open(os.path.join(C.ctl_dir(), "verify.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", default=None)
    ap.add_argument("--force", action="store_true", help="run even when no landing since the last run needs a gate")
    a = ap.parse_args()
    prev = last_verdict()
    pend = due(a.force)
    gap = C.gates_cfg().get("full_every_minutes", 0) * 60
    if pend and not a.force and prev.get("epoch") and time.time() - prev["epoch"] < gap:
        print("full gate due but spaced: the last run ended %d min ago (full_every_minutes %d)"
              % ((time.time() - prev["epoch"]) // 60, gap // 60))
        return 0
    if not pend:
        print("full gate not due: nothing since %s touches a gate (last run %s)"
              % ((prev.get("sha") or "never")[:10], prev.get("at", "never")))
        return 0
    print("full gate due: %d landing(s) need it: %s"
          % (len(pend), "; ".join("%s %s" % (s[:8], t[:50]) for s, t in pend[:5])))
    lock = verify_lock()                  # its own lock: landings continue for the hours the gate takes
    if lock is None:
        print("another verifier is running (verify.lock); this one is not needed")
        return 0
    sha = a.sha or C.git("rev-parse", "master")
    if not os.path.isdir(VERIFY):
        C.git("worktree", "add", "--detach", VERIFY, sha)
    else:
        checkout(sha)
    log = os.path.join(VERIFY, "verify-%s.log" % sha[:8])
    cmd = ["python3", "tools/suite.py", "gate"] + C.gate_skip_args()
    t0 = time.time()
    with open(log, "w") as f:
        f.write("$ %s\n" % " ".join(cmd)); f.flush()
        rc = subprocess.run(cmd, cwd=VERIFY, stdout=f, stderr=subprocess.STDOUT).returncode
    txt = open(log, errors="replace").read()
    jobs = sorted(set(re.findall(r"^\s+FAIL\s+(\S+)", txt, re.M)
                      + re.findall(r"^\[\s*\d+/\d+\] (?:TIMEOUT|ERROR|RESOURCE)\s+(\S+)", txt, re.M)))
    passed = [j for j in passed_jobs(VERIFY) if j not in jobs]
    verdict = dict(sha=sha, ok=rc == 0 and not jobs, rc=rc, failed=jobs, gates_off=list(C.gates_cfg().get("off", {})),
                   log=log, secs=round(time.time() - t0), at=time.strftime("%F %T"), epoch=time.time())
    # A job that was OFF in the previous run was not tested there: it cannot be that run's "last good".
    off_then = prev.get("gates_off", [])
    prev_ok = dict(prev, failed=list(prev.get("failed", [])) + [j for j in jobs if any(re.search(p, j) for p in off_then)])
    st = G.load()
    newly, recovered = G.reconcile(st, sha, jobs, passed, prev_ok)
    for j in newly:
        bisect_job(j, st["jobs"][j], sha)
    checkout(sha)
    landed = apply_findings(st, newly, recovered, sha, log, jobs)
    G.save(st)
    json.dump(verdict, open(VERDICT, "w"), indent=1)
    print("full gate %s: %s, %ds, log %s" % ("GREEN" if verdict["ok"] else "RED", ", ".join(jobs) or "rc=%d" % rc,
                                             verdict["secs"], log))
    for j in newly:
        e = st["jobs"][j]
        print("  NEW RED %s: last good %s, first bad %s (%s)" % (j, (e.get("last_good") or "unknown")[:10],
              (e.get("first_bad") or "unknown")[:10], e.get("bisect_note", "")))
    for j in recovered:
        print("  RECOVERED %s" % j)
    if landed:
        print("ledger commit landed on master: %s" % landed[:10])
    for job in jobs:
        name = ("fix-gate-" + re.sub(r"[^a-z0-9]+", "-", job.lower()))[:60].rstrip("-")
        if name in C.load() or any(f == name + ".json" for f in os.listdir(C.qdir())):
            continue                      # already being worked or queued: one fix per job
        e = st["jobs"].get(job, {})
        task = ("The full gate (%s) is red on master in job `%s`. Last working commit: %s. First not working: %s. Read "
                "the failing output in %s (search for %r) and bugs/gate-%s.md. Find the root cause and fix it; a job that "
                "passes alone on master is a load problem, say so and stop. Narrow tests only (no gate: the integrator "
                "runs the suite once). Commit, clean tree, CONTROL-STATUS line."
                % (sha[:8], job, (e.get("last_good") or "unknown")[:10], (e.get("first_bad") or "unknown")[:10],
                   log, job, job))
        C.cmd_enqueue(argparse.Namespace(name=name, claim=["gate:" + job], task=task, task_file=None, file=[],
                                         base="master", needs=[], model=None, pool=None))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
