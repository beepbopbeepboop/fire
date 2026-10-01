#!/usr/bin/env python3
"""Run integration unattended. THE ALGORITHM: merge EVERY finished branch into the integrator, gate it ONCE, fix what
breaks, and land everything when it is green. One run clears the whole backlog; serial one-at-a-time grows it.

  1. BATCH   all finished branches (priority order) are merged onto master and the full gate runs once, with any red job
             confirmed by re-running just those jobs alone (load flakes are not verdicts). Green: the whole batch lands.
  2. BISECT  only if it goes wrong. The jobs that failed ARE the test case: probe the first half of the merge order with
             just those jobs (right track / wrong track, minutes, no side effects), then half of what is left, ... ~log2(n)
             probes name the first bad branch. That branch is set aside and handed to a fixer; everything else is
             re-batched and lands in one gate. Each red batch removes at least one culprit, so it always terminates.
  3. FAST LANE  test-infrastructure-only branches skip the project gate (owner's policy) and land first.

Conflicting branches are not blockers: integrate.py leaves them out and queues a merge fixer for each, and they join a
later batch.

    autointegrate.py [--interval-min 3]

Safeguards, because nobody is watching:
  * The integrator's own flock means a second round cannot start while one runs, and the gate's
    memory reservations (tools/memslot.py) queue it behind any other heavy job.
  * A branch set aside as the first bad one is not retried until its head CHANGES (a new commit); its fixer
    produces that commit.
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


def parse(out, key):
    for line in out.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].split()
    return []


def probe(prefix, failed_jobs_):
    """Right track / wrong track: merge exactly `prefix` and run ONLY the jobs that failed. Minutes, no side effects."""
    rc, out = run_integrate("--only", *prefix, "--jobs", *failed_jobs_, "--no-fixers")
    return rc == 0 and "--jobs run finished" in out


def bisect_first_bad(merged, failed_jobs_):
    """`merged` (ordered) fails `failed_jobs_` as a whole. Return k with merged[:k] passing them and merged[:k+1] failing:
    merged[k] is the first branch that breaks them. Each probe tests half of what is left (100%, 50%, 25%, 12%, ...), so ~log2(n)
    probes of just the failing jobs find it."""
    lo, hi = 0, len(merged)            # invariant: prefix lo passes (the empty one does), prefix hi fails
    while hi - lo > 1:
        mid = (lo + hi) // 2
        ok = probe(merged[:mid], failed_jobs_)
        log("  probe %d/%d branches on %s: %s" % (mid, len(merged), ",".join(failed_jobs_), "right track" if ok else "WRONG track"))
        if ok:
            lo = mid
        else:
            hi = mid
    return lo


SUSPECT = None


def fix_forward(merged, failed, gate_log, attempts=2, timeout_min=180):
    """THE PIECE-FIX RULE. A red batch is usually a handful of small, customary breakages where many branches meet (a
    half-applied conflict resolution, a helper renamed in one branch and still called by its old name in another, an
    unregistered test file, a stale marker or hard-coded count, two fixes of one thing). An agent working on the MERGED tree fixes
    five twenty-line problems in ~10 minutes; ONE bisect step costs 3-8 min per probe x log2(n) probes, then a gate on the good
    half (15-20 min), then a re-batch gate (15-20 min): 45-80 min per culprit. So fix forward first; bisect only if this fails.

    The merged tree is snapshotted as a branch, a worker starts ON it with the failing jobs as its acceptance test, and its
    branch (which contains the whole batch plus the fixes) is probed with just those jobs and then gated: green lands EVERYTHING."""
    import argparse as _ap
    ts = int(time.time() % 1000000)
    base = "batchfix-%d" % ts
    C.git("branch", "-f", base, "HEAD", cwd=I.INTEG)             # the exact tree the red gate ran on
    excerpt = failed_jobs(gate_log)
    for attempt in range(1, attempts + 1):
        name = "%s-a%d" % (base, attempt)
        task = ("The integrator merged %d finished branches onto master in ONE batch and the full gate is RED. You start on branch %s: "
                "EXACTLY that merged tree. Jobs failing (confirmed by re-running them alone, so not load): %s.\n\nFailure excerpt:\n%s\n\n"
                "Make each of them pass. Fixes of ANY size are fine: thousands of lines is normal when many branches meet, so do not hold back "
                "or bail out because a repair is big. The usual and customary breakages: a conflict resolved wrongly or left half-applied; a "
                "helper renamed or moved by one branch and still called by its old name from another; a registration or estate entry missing "
                "for a new test file; a stale expected-failure marker, hard-coded count or table row; two branches fixing the same thing two "
                "ways (consolidate to one, CLAUDE.md); an index/doc conflict. Use `git log --merges --oneline master..HEAD` to see which "
                "branch each file came from. HARD problems you SHOULD debug yourself, properly: a crash or SIGSEGV, a wrong value, a hang. "
                "Use HOW-TO-DEBUG.html (the iota + rolling-hash bisection, section 8b) and tools/gdbtool (persistent lldb) and the "
                "failing job's own test case: find the root cause, do not paper over it. You may run EXACTLY the failing jobs to verify: "
                "python3 tools/suite.py %s (they reserve their own memory; one at a time). Do NOT revert or disable a branch's behaviour, and "
                "do NOT delete or skip a test to get green. Commit each fix on its own with a message naming the branch it repairs. "
                "ONLY if there is ONE hard issue that you cannot crack after a real, sustained effort: ISOLATE it, do not abandon the rest. "
                "Finish the other repairs, then finish with CONTROL-STATUS: BLOCKED and a QUESTION: line that names the single failing test "
                "case and the ONE branch (use its exact task name) or commit responsible and what you established; the integrator will "
                "split that branch off and land everything else. Otherwise finish with the REPORT block and CONTROL-STATUS: DONE once ALL "
                "of those jobs pass."
                % (len(merged), base if attempt == 1 else prev, ", ".join(failed), excerpt, " ".join(failed)))
        ns = _ap.Namespace(name=name, claim=["task:" + name], task=task, task_file=None, file=[], base=(base if attempt == 1 else prev), model=None)
        try:
            C.cmd_spawn(ns)
        except SystemExit as e:
            log("could not start the batch fixer: %s" % e); return False
        log("PIECE-FIX attempt %d: %s started on the merged tree (failing: %s)" % (attempt, name, ",".join(failed)))
        wait_family(name)                                      # unstick restarts a stalled one as NAME-rN; no wall-clock cap
        tasks = C.load()
        family = sorted((n for n in tasks if n == name or n.startswith(name + "-r")), key=lambda n: tasks[n]["slot"])
        for n in family:
            if C.state_of(tasks[n]) == "running":
                try: os.killpg(tasks[n]["pid"], 15)
                except OSError: pass
            snapshot_tree(tasks[n], "the fixer exited with uncommitted work")
        done = [n for n in family if C.ahead(tasks[n]) > 0 and tasks[n].get("state") != "abandoned"]
        qtext = " ".join(q for n in family for q in C.questions(tasks[n]))
        global SUSPECT
        SUSPECT = next((m for m in merged if m in qtext), None)
        if SUSPECT:
            log("PIECE-FIX attempt %d isolated ONE hard issue; suspect branch: %s (%s)" % (attempt, SUSPECT, qtext[:160]))
        if not done:
            log("PIECE-FIX attempt %d produced no commits (%s)" % (attempt, "BLOCKED" if any(C.verdict(tasks[n]) == "BLOCKED" for n in family) else "timeout/none"))
            return False
        fixname = done[-1]
        prev = tasks[fixname]["branch"]
        log("PIECE-FIX attempt %d: %s has %d commit(s); probing just the failing jobs on it" % (attempt, fixname, C.ahead(tasks[fixname])))
        if not probe([fixname], failed):
            log("  the fixes do not yet make %s pass" % ",".join(failed))
            continue
        log("  right track: the failing jobs pass. Full gate on the whole batch + fixes now.")
        rc, out = run_integrate("--only", fixname)
        log("  batch+fixes: rc=%d %s" % (rc, " | ".join(l for l in out.splitlines() if l.startswith(("GREEN", "RED")))[:200]))
        if rc == 0 and "GREEN" in out:
            return True
    return False


def snapshot_tree(t, why):
    """Commit whatever a worker left uncommitted, so its branch is integrable (the integrator refuses a dirty tree)."""
    wt = t["worktree"]
    C.git("add", "-A", cwd=wt, check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt).returncode != 0:
        C.git("commit", "-q", "-m", "WIP snapshot by controller: " + why, cwd=wt, check=False)


def family_running(name):
    tasks = C.load()
    return any(C.state_of(tasks[n]) == "running" for n in tasks if n == name or n.startswith(name + "-r"))


def wait_family(name, cap_h=12):
    """Wait for a worker (and any -rN restart of it) while it is alive. NOT a time-box: the cap is a 12 h backstop only; a
    stalled or network-killed worker is restarted by `unstick`. (A 3 h cap once killed a merger 13 of 27 merges in.)"""
    t0 = time.time()
    while time.time() - t0 < cap_h * 3600 and family_running(name):
        time.sleep(20)


def settle(st, red, merged, failed, rc, out):
    """Everything after a batch's gate: green lands; red -> piece-fix on the merged tree -> (only then) isolate and bisect.
    Returns True if the integrator was busy."""
    tail = [l for l in out.splitlines() if l.startswith(("GREEN", "RED", "CONFLICT", "the red did NOT"))]
    log("batch result rc=%d merged=%d failed jobs=%s %s" % (rc, len(merged), failed or "-", " | ".join(tail)[:200]))
    if "another integrator" in out:
        return True
    if "nothing to integrate" in out:
        log("ERROR: the integrator refused what it was given (nothing to integrate): not treating that as success")
        for n in merged: red[n] = head_sha(n)
        json.dump(st, open(STATE, "w"))
        return False
    if rc != 0 and merged:
        if not failed:
            log("red but no failing job could be named: setting the whole batch aside for a human")
            for n in merged: red[n] = head_sha(n)
        elif fix_forward(merged, failed, os.path.join(I.INTEG, "gate.log")):
            log("PIECE-FIX landed the whole batch (%d branches + the fixes)" % len(merged))
        else:
            log("piece-fix did not get it green: isolating the one hard issue")
            if SUSPECT and SUSPECT in merged and probe([n for n in merged if n != SUSPECT], failed):
                k = merged.index(SUSPECT)
                log("confirmed: without %s the failing jobs pass" % SUSPECT)
            else:
                k = bisect_first_bad(merged, failed)
            culprit = merged[k]
            log("first bad branch: %s (the %d before it pass %s)" % (culprit, k, ",".join(failed)))
            red[culprit] = head_sha(culprit)
            why = "breaks " + ",".join(failed) + " when merged after " + (merged[k - 1] if k else "master")
            try:
                enqueue_fixer(culprit, why + "\n" + failed_jobs(os.path.join(I.INTEG, "gate.log")))
            except Exception as e:
                log("could not queue a fixer for %s: %s" % (culprit, e))
        json.dump(st, open(STATE, "w"))
    return False


def merge_conflicts(M, X, timeout_min=180):
    """Conflicts BETWEEN branches belong in ONE place: an agent on the merged tree merges the branches that conflicted, one after
    another, so each resolution sees the ones before it. (Resolving each against master separately, one fixer per branch, makes
    results that conflict with each other all over again: 25 fixers for 25 conflicts, none of them able to land.)"""
    import argparse as _ap
    ts = int(time.time() % 1000000)
    base = "batchmerge-%d" % ts
    C.git("branch", "-f", base, "HEAD", cwd=I.INTEG)             # master + every branch that merged cleanly
    tasks = C.load()
    name = base
    lines = "\n".join("  %s   (branch %s; its task: %s)" % (n, tasks[n]["branch"], tasks[n]["summary"][:90]) for n in X)
    task = ("You start on branch %s: master plus %d finished branches that merged cleanly (the integrator merged them all in one batch). "
            "These %d branches CONFLICTED when merged onto that tree. Merge each of them into your branch, ONE AT A TIME, in this order, "
            "with `git merge <branch>`:\n%s\n\nResolve every conflict by reading BOTH sides and keeping both sides' intent: never take "
            "one side wholesale, never drop a test, a doc a branch git rm'd because its bug is fixed stays removed with its row removed "
            "from index tables, a set/table edited by several branches (HOST_MODELLED, registries, estate lists) keeps every branch's "
            "edit. After each merge make the tree COHERENT, not just textually merged: two branches fixing one thing two ways -> "
            "consolidate to one (CLAUDE.md); a helper renamed by one and called by the old name from another -> fix the call. After each "
            "merge run the narrow tests for the files involved (under python3 tools/memslot.py --gb 8 --label x --); commit. A branch whose "
            "conflict is a genuine DESIGN conflict you cannot reconcile after a real effort (not merely large: thousands of lines is fine): skip just that one (git merge --abort), say which and why, and go on. "
            "Never use git stash. At the end run python3 test_suite.py, python3 test_memslot.py and python3 tools/suite.py smoke -j2 and "
            "report. Finish with the REPORT block and CONTROL-STATUS: DONE (or PARTIAL naming what you skipped)."
            % (base, len(M), len(X), lines))
    ns = _ap.Namespace(name=name, claim=["task:" + name], task=task, task_file=None, file=[], base=base, model=None)
    try:
        C.cmd_spawn(ns)
    except SystemExit as e:
        log("could not start the conflict merger: %s" % e); return None
    log("CONFLICT-MERGE: %s started on the merged tree to merge %d conflicting branches: %s" % (name, len(X), ", ".join(X)[:200]))
    wait_family(name)
    tasks = C.load()
    family = sorted((n for n in tasks if n == name or n.startswith(name + "-r")), key=lambda n: tasks[n]["slot"])
    for n in family:
        if C.state_of(tasks[n]) == "running":
            try: os.killpg(tasks[n]["pid"], 15)
            except OSError: pass
        snapshot_tree(tasks[n], "the merger exited with uncommitted work")
    done = [n for n in family if C.ahead(tasks[n]) > 0]
    if not done:
        log("CONFLICT-MERGE produced no commits"); return None
    log("CONFLICT-MERGE finished: %s (%d commits)" % (done[-1], C.ahead(tasks[done[-1]])))
    return done[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval-min", type=float, default=3, help="sleep only when there is nothing to do or the integrator is busy")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        st = load_state()
        red = st.setdefault("red", {})
        busy = False
        # FAST LANE FIRST: test-infrastructure-only branches need no project gate (owner's policy) and cost minutes.
        for name in sorted(I.pick_candidates(quiet=True), key=C.priority_key):
            if name in I.pick_candidates(quiet=True) and I.infra_only(C.load()[name]["branch"]):
                log("%s touches only test infrastructure: fast lane (no project gate)" % name)
                rc, out = run_integrate("--only", name, "--fast")
                log("%s: rc=%d %s" % (name, rc, " | ".join(l for l in out.splitlines() if l.startswith(("GREEN", "RED", "NOT test", "CONFLICT")))[:240]))
                if "another integrator" in out:
                    busy = True; break
        did = False
        if not busy:
            # ADOPT: a merger/fixer that is still working (or finished) when this loop (re)starts is NOT thrown away and redone.
            pend = [n for n, t in sorted(C.load().items(), key=lambda kv: kv[1]["slot"])
                    if re.match(r"batchmerge-\d+(-r\d+)*$", n) and t.get("state") not in ("integrated", "abandoned", "superseded")
                    and (C.state_of(t) == "running" or C.ahead(t) > 0) and red.get(n) != head_sha(n)]
            if pend:
                name = pend[-1]; did = True
                log("ADOPT: merger %s (%s)" % (name, "still working: waiting for it" if family_running(name) else "finished"))
                wait_family(name)
                for n in [x for x in C.load() if x == name or x.startswith(name + "-r")]:
                    snapshot_tree(C.load()[n], "the merger exited with uncommitted work")
                fam = sorted((x for x in C.load() if x == name or x.startswith(name + "-r")), key=lambda x: C.load()[x]["slot"])
                tgt = [x for x in fam if C.ahead(C.load()[x]) > 0][-1:]
                if tgt:
                    rc, out = run_integrate("--only", *tgt)
                    if settle(st, red, parse(out, "MERGED"), parse(out, "FAILED_JOBS"), rc, out):
                        busy = True
                    continue
            # THE ALGORITHM: merge EVERY finished branch (priority order), run the gate ONCE, land everything if it is green.
            batch = [n for n in sorted(I.pick_candidates(quiet=True), key=C.priority_key)
                     if not I.infra_only(C.load()[n]["branch"]) and red.get(n) != head_sha(n)]
            if batch:
                did = True
                log("BATCH: all %d finished branches merged, one gate: %s" % (len(batch), ", ".join(batch)[:300]))
                # 1. merge them all (no side effects) to learn which merge cleanly (M) and which conflict (X)
                rc, out = run_integrate("--only", *batch, "--no-fixers", "--dry-run")
                if "another integrator" in out:
                    busy = True
                    merged, failed, rc, out = [], [], 1, out
                else:
                    M = parse(out, "MERGED")
                    X = [l.split()[1].rstrip(":") for l in out.splitlines() if l.startswith("(probe) ") and "conflicts" in l]
                    target = list(M)
                    if X and M:
                        # 2. the conflicts are resolved in ONE place: an agent on the merged tree merges them in turn
                        B = merge_conflicts(M, X)
                        if B:
                            target = [B]
                    elif X and not M:
                        target = []
                    if not target:
                        log("nothing mergeable this round (all conflicted, no merger result)")
                        for n in X: red[n] = head_sha(n)
                        json.dump(st, open(STATE, "w"))
                        rc, out, merged, failed = 0, "", [], []
                    else:
                        rc, out = run_integrate("--only", *target)
                        merged, failed = (parse(out, "MERGED"), parse(out, "FAILED_JOBS"))
                if settle(st, red, merged, failed, rc, out):
                    busy = True
        if a.once:
            return
        if busy or not did:
            time.sleep(a.interval_min * 60)


if __name__ == "__main__":
    main()
