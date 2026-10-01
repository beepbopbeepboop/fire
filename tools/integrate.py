#!/usr/bin/env python3
"""The integrator: merge every finished worker branch, gate ONCE, then land on master.

    integrate.py [--dry-run] [--only NAME ...]

One round:
  1. Candidates = tasks whose worker has exited, with commits ahead of master and
     a clean worktree (a dirty tree is reported and skipped: unfinished work).
  2. ../work-integ is reset to master and each candidate is merged in (--no-ff).
     A candidate that conflicts is aborted, marked `conflict`, and left for the
     controller to hand back to a worker; the rest carry on.
  3. `make gate` runs in ../work-integ over everything merged, ONE time. Its
     output goes to ../work-integ/gate.log; the two judgement lines the gate
     cannot fail on (stdlib-dylib `skip` count, stdlib-syntax `FAILED:` line)
     are copied to gate-judgement.txt for a human/controller to compare.
  4. Green: master is fast-forwarded to integ, merged tasks are marked
     `integrated`. Red: master is untouched, merged tasks are marked
     `integration-failed`, and the failing jobs are printed. The controller then
     marks the culprit `superseded` and spawns a fix task
     (`control.py spawn --base work/<culprit>`); the next round is master + what
     is still outstanding, so one bad set never blocks the rest.
"""
import argparse, fcntl, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

INTEG = os.path.join(C.PARENT, "work-integ")


def run(cmd, cwd, log=None):
    if log:
        with open(log, "w") as f:
            return subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode
    return subprocess.run(cmd, cwd=cwd).returncode


# The jobs that catch nearly every bad branch in minutes: the self-host build (the compiler compiling
# itself), the bootstrap's first steps, and the fast compiled-path tests. A branch that is red here never
# reaches the ~20-40 minute full gate.
QUICK = ["mojoc", "selfhost", "bootstrap-stage1-transitive", "bootstrap-stage2-cc", "gimple", "runner"]


# Files the controller itself maintains on master (tools, docs). If master moved ONLY in these since
# `integ` was cut, a merge commit is safe and the gate's verdict still stands; anything else moving means
# master changed under the round and the round must be redone, not merged.
CONTROLLER_FILES = ("tools/control.py", "tools/control_prompt.md", "tools/gatewatch.py", "tools/integrate.py",
                    "tools/autointegrate.py", "CONTROL.html", "bugs/PERF_memory_over_4gb_is_a_bug.md")


# TEST INFRASTRUCTURE: code that only decides how, whether and with how much memory the project is TESTED. A
# change here cannot alter what the compiler produces, and the suite's own tests (test_suite.py,
# test_memslot.py, the changed test files) are the right check for it; gating it on the project gate costs
# hours and proves nothing more (owner's policy, 2026-09-30: turning a test off, changing 64 to 8, are
# inherently safe). A branch whose EVERY changed file is listed here lands through the fast lane.
INFRA_FILES = ("tools/suite.py", "tools/memslot.py", "tools/memcap.py", "tools/procrun.py", "tools/ab_run_one.py",
               "tools/gatewatch.py", "tools/control.py", "tools/control_prompt.md", "tools/integrate.py",
               "tools/autointegrate.py", "CLAUDE.md", "CONTROL.html", "checked_run.py")
INFRA_PREFIXES = ("bugs/", "doc/")


def is_infra_file(f):
    return (f in INFRA_FILES or f.startswith(INFRA_PREFIXES)
            or (f.startswith("test_") and f.endswith(".py") and "/" not in f))


def infra_only(branch):
    """True if every file `branch` changes relative to master is test infrastructure or docs."""
    r = subprocess.run(["git", "diff", "--name-only", "master..." + branch], cwd=C.MAIN, capture_output=True, text=True)
    files = r.stdout.split()
    return r.returncode == 0 and bool(files) and all(is_infra_file(f) for f in files)


def failed_job_names(log):
    """Job names from the FAILED section of a suite/gate log (real failures only, not EXPECTED/RESOURCE)."""
    try:
        txt = open(log, errors="replace").read()
    except OSError:
        return []
    m = re.search(r"^FAILED:\n(.*?)(?=^[A-Z][A-Z-]+.*:\n|^suite:)", txt, re.S | re.M)
    if not m:
        return []
    names = []
    for line in m.group(1).splitlines():
        t = line.strip().split()
        if t and re.fullmatch(r"[\w.:-]+", t[0]) and "(" in line:
            names.append(t[0].split(":")[0])
    return sorted(set(names))


def test_failures(tree):
    """The set of 'FAIL  <check>' names test_suite.py reports in `tree` (its own registry-of-checks)."""
    r = subprocess.run(["python3", "test_suite.py"], cwd=tree, capture_output=True, text=True)
    return set(re.findall(r"^FAIL\s+(.+?)(?::|$)", r.stdout, re.M)), r


def land_on_master():
    r = subprocess.run(["git", "merge", "--ff-only", "integ"], cwd=C.MAIN, capture_output=True, text=True)
    if r.returncode == 0:
        return
    base = C.git("merge-base", "master", "integ")
    moved = C.git("diff", "--name-only", base, "master").splitlines()
    if moved and all(f in CONTROLLER_FILES for f in moved):
        C.git("merge", "--no-edit", "-m", "integrate: merge gated tree over controller-tool commits", "integ")
        return
    sys.exit("master moved under the round (%s): cannot fast-forward; redo the round" % ", ".join(moved[:5]))


def pick_candidates(only=None, allow_dirty=(), quiet=False):
    """Tasks whose worker has exited with commits, a clean tree and no NEEDS-INFO/BLOCKED verdict."""
    cands = []
    say = (lambda *_: None) if quiet else print
    for name, t in sorted(C.load().items(), key=lambda kv: kv[1]["slot"]):
        if only and name not in only:
            continue
        st = C.state_of(t)
        if st not in ("exited-ok", "exited-err", "integration-failed"):
            continue
        if C.verdict(t) in ("NEEDS-INFO", "BLOCKED"):
            say("skip %s: worker says %s" % (name, C.verdict(t))); continue
        if not C.ahead(t):
            say("skip %s: no commits" % name); continue
        if C.git("status", "--short", cwd=t["worktree"]) and name not in allow_dirty:
            say("skip %s: dirty worktree (unfinished)" % name); continue
        cands.append(name)
    return cands


def enqueue_merge_fix(name, t, conflict_text):
    """A branch that cannot merge onto master is handed back to a worker, not left for a human: queue a
    merge task that starts from the branch, merges master into it, resolves, and verifies narrowly."""
    import argparse as _ap
    files = sorted(set(l.split("Merge conflict in ")[-1].strip() for l in conflict_text.splitlines() if "Merge conflict in" in l))
    task = ("Branch %s (a finished, verified worker branch; original task: %s) conflicts with current master in: %s. "
            "You start on that branch. Run `git merge master`, resolve every conflict by reading BOTH sides and keeping both "
            "sides' intent (never take one side wholesale, never drop a test; a doc a branch git rm'd because its bug is fixed "
            "stays removed), then make the merged tree COHERENT, not just textually merged (two fixes for one thing: consolidate, "
            "CLAUDE.md). Verify with the narrow tests that cover the files involved and the branch's own new tests, each wrapped in "
            "python3 tools/memslot.py --gb 8 --label x --. You are a light worker: no gate, no self-host build. Never use git stash. "
            "Commit the merge. Finish with the REPORT block and a CONTROL-STATUS line."
            % (t["branch"], t["summary"][:150], ", ".join(files) or "see `git merge master`"))
    mname = "fix-merge-" + name
    if mname in C.load():
        mname += "-%d" % int(time.time() % 100000)
    C.cmd_enqueue(_ap.Namespace(name=mname[:60], claim=t["claims"] or ["task:" + mname], task=task, task_file=None,
                                file=[], base=t["branch"], needs=[], model=None))
    with C.registry() as reg:
        reg[name]["state"] = "superseded"


def main():
    sys.stdout.reconfigure(line_buffering=True)  # progress must be visible in a redirected log
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="merge and report, do not gate or land")
    ap.add_argument("--only", nargs="*", help="restrict to these task names")
    ap.add_argument("--jobs", nargs="*", metavar="JOB",
                    help="verify with just these suite jobs (e.g. bootstrap-stage1-transitive bootstrap-stage2-cc) "
                         "instead of the full `make gate`: the way a branch's heavy verification is done, by the "
                         "one integrator, never by a worker. Landing still requires the FULL gate; a --jobs run "
                         "only reports (it never fast-forwards master).")
    ap.add_argument("--no-fixers", action="store_true",
                    help="a conflicting branch is merely left out: no merge fixer is queued and nothing is superseded "
                         "(used by the bisect probes, which re-merge the same branches many times)")
    ap.add_argument("--fast", action="store_true",
                    help="FAST LANE for a branch that touches only test infrastructure/docs (infra_only): no project gate; "
                         "run the suite's own tests and the changed test files, and land on green")
    ap.add_argument("--quick", action="store_true",
                    help="run the quick tier first (self-host build + the fast jobs, minutes) and stop at the first red, "
                         "so a bad branch is rejected without paying for the full gate")
    ap.add_argument("--allow-dirty", nargs="*", default=[], metavar="NAME",
                    help="integrate these tasks although their worktree has uncommitted files (only COMMITTED "
                         "work is merged; save the stray edits first, e.g. as a patch under ../control-stray/)")
    a = ap.parse_args()

    # ONE integrator, ever. It is the single mass consumer of CPU and memory on the machine (a gate's
    # program-class jobs need 55 GB; a second gate beside it is 110), so being careful with it means
    # there is only one of it. flock, kernel-released when this process dies, so a crash cannot wedge it.
    lock = open(os.path.join(C.ctl_dir(), "integrator.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("another integrator is already running (lock %s/integrator.lock): there is only ever one" % C.ctl_dir())

    cands = pick_candidates(a.only, a.allow_dirty)
    if a.only:                                       # the caller's order is the merge order (a bisect depends on it)
        cands = sorted(cands, key=lambda n: a.only.index(n))
    if not cands:
        print("nothing to integrate"); return

    if not os.path.isdir(INTEG):
        C.git("worktree", "add", "-B", "integ", INTEG, "master")
    else:
        C.git("switch", "-C", "integ", "master", cwd=INTEG)
    tasks = C.load()
    merged = []
    for name in cands:
        r = subprocess.run(["git", "merge", "--no-ff", "-m", "integrate %s" % name, tasks[name]["branch"]],
                           cwd=INTEG, capture_output=True, text=True)
        if r.returncode:
            subprocess.run(["git", "merge", "--abort"], cwd=INTEG)
            print("CONFLICT %s:\n%s" % (name, r.stdout[-600:]))
            if a.no_fixers:                          # a bisect probe: just leave it out, no side effects
                print("(probe) %s conflicts: left out" % name)
            else:
                enqueue_merge_fix(name, tasks[name], r.stdout)   # marks the task superseded, queues its fixer
        else:
            merged.append(name); print("merged %s" % name)
    print("MERGED: %s" % " ".join(merged))
    if not merged or a.dry_run:
        print("merged: %s (dry-run or nothing to gate)" % merged); return

    if a.fast:
        bad = [f for f in C.git("diff", "--name-only", "master...integ", cwd=INTEG).splitlines() if not is_infra_file(f)]
        if bad:
            print("NOT test infrastructure (%s): the fast lane refuses; use the gate" % ", ".join(bad[:5])); sys.exit(1)
        changed = [f for f in C.git("diff", "--name-only", "master...integ", cwd=INTEG).splitlines()
                   if f.startswith("test_") and f.endswith(".py")]
        checks = [["python3", "test_suite.py"], ["python3", "tools/suite.py", "smoke", "-j2"]]
        checks += [["python3", "tools/memslot.py", "--gb", "8", "--label", "fast:" + f, "--", "python3", f]
                   for f in changed if f != "test_suite.py"]
        print("fast lane for %s: %d check(s)" % (merged, len(checks)))
        base_fail, _ = test_failures(C.MAIN)          # what test_suite.py already reports red on master itself
        for c in checks:
            if c == ["python3", "test_suite.py"]:
                now_fail, r = test_failures(INTEG)
                open(os.path.join(INTEG, "fast.log"), "w").write(r.stdout + r.stderr)
                if now_fail - base_fail or (r.returncode != 0 and not now_fail):
                    print("RED in the fast lane: test_suite.py has NEW failures vs master: %s" % sorted(now_fail - base_fail))
                    with C.registry() as reg:
                        for n in merged: reg[n]["state"] = "integration-failed"
                    sys.exit(1)
                print("test_suite.py: no new failures vs master (still red on master itself: %s)" % sorted(base_fail & now_fail))
                continue
            if run(c, INTEG, os.path.join(INTEG, "fast.log")) != 0:
                with C.registry() as reg:
                    for n in merged: reg[n]["state"] = "integration-failed"
                print("RED in the fast lane: %s (see %s/fast.log); master untouched" % (" ".join(c[:4]), INTEG)); sys.exit(1)
        land_on_master()
        with C.registry() as reg:
            for n in merged: reg[n]["state"] = "integrated"
        print("GREEN (fast lane): master is now %s; integrated %s" % (C.git("rev-parse", "--short", "master"), merged))
        return
    if a.quick and not a.jobs:
        print("quick tier for %s: %s" % (merged, " ".join(QUICK)))
        qrc = run(["python3", "tools/suite.py"] + QUICK, INTEG, os.path.join(INTEG, "quick.log"))
        if qrc != 0:
            with C.registry() as reg:
                for n in merged: reg[n]["state"] = "integration-failed"
            print("RED in the quick tier (exit %d): master untouched; tasks marked integration-failed: %s" % (qrc, merged))
            print(subprocess.run("sed -n '/^FAILED:/,/^suite:/p' quick.log | head -12", shell=True, cwd=INTEG,
                                 capture_output=True, text=True).stdout)
            sys.exit(1)
    gate_cmd = ["python3", "tools/suite.py"] + a.jobs if a.jobs else ["make", "gate"]
    print("gating %s: %s in %s (log %s/gate.log) ..." % (merged, " ".join(gate_cmd), INTEG, INTEG))
    rc = run(gate_cmd, INTEG, os.path.join(INTEG, "gate.log"))
    if a.jobs:
        print("--jobs run finished with exit %d; master NOT touched (only a full gate lands)" % rc)
        sys.exit(rc)
    if rc != 0 and not a.jobs:
        # A red gate under load is often a timeout, not a verdict (2026-09-30: gimplegenerators 450-616 s, runner's
        # 10 s per-program limit, each spawning a pointless fixer). Confirm it the way a human would: re-run exactly
        # the jobs that failed, ALONE, on the same tree. If they pass alone the red was contention, not the branch.
        failed = failed_job_names(os.path.join(INTEG, "gate.log"))
        if failed:
            print("gate red on %s: confirming by re-running them alone" % ", ".join(failed))
            if run(["python3", "tools/suite.py"] + failed, INTEG, os.path.join(INTEG, "confirm.log")) == 0:
                print("the red did NOT reproduce when the failed jobs ran alone (load): treating the gate as green")
                rc = 0
            else:
                failed = failed_job_names(os.path.join(INTEG, "confirm.log")) or failed
            print("FAILED_JOBS: %s" % " ".join(failed))
    judg = subprocess.run("grep -h -E '^skip [a-z_./]+:|FAILED: [0-9]+' build/suite.log gate.log | sort | uniq -c | tail -20",
                          shell=True, cwd=INTEG, capture_output=True, text=True).stdout
    open(os.path.join(INTEG, "gate-judgement.txt"), "w").write(judg)
    # The gate's exit code is not enough: 2026-09-29 it exited 0 with a job TIMEOUT that its own tally
    # had silently dropped. Any TIMEOUT/ERROR job line in suite.log makes the round red, whatever `make` said.
    bad = subprocess.run(r"grep -E '^\[ *[0-9]+/[0-9]+\] (TIMEOUT|ERROR) ' build/suite.log", shell=True, cwd=INTEG,
                         capture_output=True, text=True).stdout.strip()
    if rc == 0 and bad:
        print("gate exited 0 but suite.log records:\n" + bad + "\ntreating the round as RED")
        rc = 1
    if rc == 0:
        land_on_master()
        with C.registry() as reg:
            for n in merged: reg[n]["state"] = "integrated"
        print("GREEN: master fast-forwarded to %s; integrated %s" % (C.git("rev-parse", "--short", "master"), merged))
    else:
        with C.registry() as reg:
            for n in merged: reg[n]["state"] = "integration-failed"
        print("RED (exit %d): master untouched. tasks marked integration-failed: %s" % (rc, merged))
        print(subprocess.run("grep -E 'FAIL|ERROR|RESOURCE' build/suite.log | head -20", shell=True, cwd=INTEG,
                             capture_output=True, text=True).stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
