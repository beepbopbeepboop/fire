#!/usr/bin/env python3
"""The full gate, run on a pinned commit of master in its own worktree whenever a landing since the last run needs one.

    verify_landed.py [--sha SHA] [--force]

The integrator lands on the cheap landing gate (tools/gates.json `landing`), so landings are not serialized behind the
full suite. The full suite (`suite.py gate`, minus every gate that is OFF) costs ~35 minutes and runs as long as at
least one first-parent commit since the last run touches something a gate reads (gate_ledger.pending): docs and the
orchestration tools do not count. The gate takes HOURS, so it must not hold anything the integrator needs: it runs in
../work-verify on the sha master had when it started (master marches on meanwhile, and landings continue), under its OWN
lock (verify.lock: one verifier at a time). Only the short step that lands its ledger commit takes master.lock (the lock every fast-forward takes).
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
import integrate as I
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


def passed_jobs(tree, since=None):
    """The registrations the run saw PASS, from the suite's own log (build/suite.log).

    The tag for a pass is `ok` (`suite.py::_TAG`, the one runner's spelling), NOT `PASS`: the reader here matched
    `PASS` and so returned [] for every run since the one runner landed, which means `reconcile`'s `passed` loop
    never saw a recovery and no `last_good` ever came from a run that watched the job pass. A fanout item's `ok` is
    not its parent's: only the registration's own PER-TEST row (the worst item) answers for it."""
    v = I.suite_verdicts(os.path.join(tree, "build", "suite.log"), since)
    return sorted({k for k, tag in v.items() if ":" not in k and I.tag_verdict(tag) == "green"})


def failed_jobs(log):
    """The failing JOBS a full-gate log reports, as the names the registry knows.

    A fanout ITEM (`bootstrap-stage2-dumps:hello.mojo`) is not a job: only the
    parent's `fanout(...)` call is a registration, and that is the one unit that
    can carry a `disabled=` marker, a `bugs/gate-<job>.md` doc and one fix task.
    The suite prints a `  FAIL     <job>  (0s)` progress line for every job while
    it runs — one PER ITEM for a fanout — so the screen lines cannot be the
    source of the ledger's job list: at c0182fd365 they turned one disabled
    producer's cascade into fifty docs and fifty dispatched workers. The
    `FAILED:` section names the registration, and `integrate.failed_job_names`
    is the reader the landing gate already uses (one implementation of "which
    jobs are red", not two). The per-job log lines add TIMEOUT/ERROR/RESOURCE,
    which the FAILED section does not carry (a RESOURCE is not a verdict on the
    output), so they are read too and their item suffix stripped the same way."""
    try:
        txt = open(log, errors="replace").read()
    except OSError:
        return []
    names = I.failed_job_names(log) + re.findall(
        r"^\[\s*\d+/\d+\] (?:TIMEOUT|ERROR|RESOURCE)\s+(\S+)", txt, re.M)
    return sorted({n.split(":")[0] for n in names})


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
    """The run's verdict on JOB at SHA, as 'green', 'red' or 'no-evidence': one job, alone, in the verify worktree.

    The verdict is the suite's own per-job line in build/suite.log, never the process exit code. A fanout ITEM name is
    rejected by the runner before it starts (`no such bucket or test`, exit 1 at EVERY commit), and a selection that
    SKIPs behind a disabled dep exits 0: reading either exit code as the job's answer is what collapsed `first_bad`
    to the first commit after `last_good` for all fifty `bootstrap-stage2-dumps:<item>` entries (2026-11-21)."""
    checkout(sha)
    since = time.time()
    subprocess.run(["python3", "tools/suite.py", job], cwd=VERIFY, capture_output=True)
    return I.job_verdict(os.path.join(VERIFY, "build", "suite.log"), job, since=since)


class _NoEvidence(Exception):
    """A probe produced no verdict for the job at a commit: the bisect has no answer there and must not guess one."""

    def __init__(self, sha):
        self.sha = sha


def bisect_job(job, e, sha):
    """Fill e["first_bad"] (and bisect_note) for a job that is red at SHA, between its last_good and SHA.

    A commit where the job did not run is NO EVIDENCE, not a red one: `first_bad` stops there and the note says
    "job did not run at <sha>; cannot bisect" instead of blaming the first commit in the range."""
    if not e.get("last_good"):
        e["bisect_note"] = e.get("bisect_note") or "no earlier full-gate run had this job green"
        return
    commits = G.commits_between(e["last_good"], sha, cwd=VERIFY)
    if not commits:
        e["bisect_note"] = "last_good is not an ancestor of the run"
        return

    def is_bad(c):
        v = job_is_red_at(job, c)
        if v == "no-evidence":
            raise _NoEvidence(c)
        return v == "red"

    try:
        e["first_bad"], probes = G.first_bad(commits, is_bad)
    except _NoEvidence as x:
        e["first_bad"] = None
        e["bisect_note"] = "job did not run at %s; cannot bisect" % x.sha[:10]
        return
    e["bisect_note"] = "%d commit(s) between the runs, %d probe(s)" % (len(commits), probes)


def subject(sha):
    return C.git("log", "-1", "--format=%s", sha, check=False) or "(not in this repository)"


def write_doc(job, e, sha, log):
    """bugs/gate-<job>.md in VERIFY: created if absent, and its `## Gate ledger` section replaced if present."""
    p = os.path.join(VERIFY, "bugs", "gate-%s.md" % job)
    sect = G.report_text(job, e, sha, log, subject)
    if e.get("registered") is False:
        # A fanout ITEM is not a registration: `python3 tools/suite.py <item>` is
        # rejected before the runner starts (`no such bucket or test`), and
        # `--only '<item>'` matches nothing. The runnable unit is the parent, and
        # the item's own verdict is one line in the log.
        repro = ("Reproduce on master by running its parent fanout (`python3 tools/suite.py %s`) and reading the "
                 "`%s` line out of `build/suite.log`: an item is expanded out of `fanout(...)` and is not a job "
                 "in `tools/suite.py`, so it cannot be run by name. Then fix the cause."
                 % (job.split(":", 1)[0], job))
    else:
        repro = "Reproduce on master (`python3 tools/suite.py %s`), then fix the cause." % job
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
               "on master.\n\n%s\n\n%s"
               % (job, job, sha[:10], repro, sect))
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
        e["registered"] = G.registered(src, j)     # a fanout ITEM has no marker to carry (see report_text)
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


def clear_untracked_twins(ledger):
    """Remove the MAIN-untracked bugs/gate-*.md copies that the ledger commit tracks, when their bytes are identical to
    the tracked copy. An untracked twin is what makes git refuse the merge ("would be overwritten by merge"), so every
    job's marker stayed on verify-ledger (2026-11-13). A twin whose bytes DIFFER is somebody's edit: it is kept, and the
    merge is refused and reported as before. Untracked docs the ledger does not track are never touched."""
    tracked = [p for p in C.git("ls-tree", "-r", "--name-only", ledger, "--", "bugs", cwd=C.MAIN).splitlines()
               if re.fullmatch(r"bugs/gate-[\w.-]+\.md", p)]
    untracked = set(C.git("ls-files", "--others", "--exclude-standard", "--", "bugs", cwd=C.MAIN).splitlines())
    for rel in tracked:
        if rel not in untracked:
            continue
        p = os.path.join(C.MAIN, rel)
        if open(p, "rb").read() == subprocess.run(["git", "show", "%s:%s" % (ledger, rel)], cwd=C.MAIN,
                                                 capture_output=True).stdout:
            os.remove(p)
            print("removed the untracked copy of %s: the ledger commit tracks the same bytes" % rel)
        else:
            print("untracked %s differs from the ledger's copy: kept (the merge will say so)" % rel)


def land_ledger(new, sha, wait_s=900):
    """Move master to include the ledger commit NEW (built on SHA, the commit the gate ran on). A gate takes hours, so
    master has almost always moved since SHA: then the commit is MERGED onto the master of the day, which is safe because
    it touches only suite.py's `disabled=` markers and bugs/gate-*.md docs; a conflict leaves it on branch verify-ledger.
    master.lock is held only for this step, the same lock every landing's fast-forward takes (integrate.master_lock),
    so the ledger commit waits for at most one fast-forward, never for a whole landing round."""
    try:
        with I.master_lock(wait_s):
            clear_untracked_twins(new)
            if C.git("rev-parse", "master", cwd=C.MAIN) == sha:
                st, detail = SF.merge(C.MAIN, "--ff-only", "verify-ledger")
            else:
                st, detail = SF.merge(C.MAIN, "--no-edit", "-m", "gate ledger: merged onto the master of the day (the gate ran at %s)" % sha[:10],
                                      "verify-ledger")
            if st == "ok":
                return True
            print("ledger commit %s NOT landed (%s: %s); it stays on branch verify-ledger" % (new[:10], st, detail[:160]))
            return False
    except TimeoutError:
        print("ledger commit %s NOT landed: master.lock was busy for %ds; it stays on branch verify-ledger" % (new[:10], wait_s))
        return False


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
    jobs = failed_jobs(log)
    passed = [j for j in passed_jobs(VERIFY, since=t0) if j not in jobs]
    verdict = dict(sha=sha, ok=rc == 0 and not jobs, rc=rc, failed=jobs, passed=passed,
                   gates_off=list(C.gates_cfg().get("off", {})),
                   log=log, secs=round(time.time() - t0), at=time.strftime("%F %T"), epoch=time.time())
    # A job that was OFF in the previous run did not run there, so it is not in that run's `passed` set and cannot be
    # its last_good: reconcile's passed-set test excludes it (the patch this replaces had to claim it failed to do so).
    st = G.load()
    newly, recovered = G.reconcile(st, sha, jobs, passed, prev)
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
