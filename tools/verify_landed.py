#!/usr/bin/env python3
"""Post-landing verifier for the light-gate swarm: `make check` and the stdlib dylib build, on what master now is.

    verify_landed.py [--sha SHA]

`integrate.py --stdlib` lands a branch after only the stdlib compile; this is the rest of the quality check, run
AFTER the landing so landing is not serialized behind it. It runs in its own worktree (../work-verify) at the
commit, one verifier at a time (flock), and writes the verdict to <common-git-dir>/control/verify.json. On red it
queues a `fix-landed-*` task naming the failed jobs and the commit, for the swarm's workers to repair."""
import argparse, fcntl, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

VERIFY = os.path.join(C.PARENT, "work-verify")


def run(cmd, log):
    with open(log, "a") as f:
        f.write("$ %s\n" % " ".join(cmd)); f.flush()
        return subprocess.run(cmd, cwd=VERIFY, stdout=f, stderr=subprocess.STDOUT).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", default=None)
    a = ap.parse_args()
    lock = open(os.path.join(C.ctl_dir(), "verify.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("another verifier is running")
    sha = a.sha or C.git("rev-parse", "master")
    if not os.path.isdir(VERIFY):
        C.git("worktree", "add", "--detach", VERIFY, sha)
    else:
        C.git("checkout", "-q", "--detach", sha, cwd=VERIFY)
    log = os.path.join(VERIFY, "verify-%s.log" % sha[:8])
    open(log, "w").close()
    t0 = time.time()
    steps = [("make check", ["make", "check"]), ("stdlib-dylib", ["python3", "tools/suite.py", "stdlib-dylib"])]
    res = {n: run(c, log) for n, c in steps}
    failed = [n for n, rc in res.items() if rc]
    jobs = sorted(set(re.findall(r"^\s+FAIL\s+(\S+)", open(log, errors="replace").read(), re.M)))
    verdict = dict(sha=sha, ok=not failed, failed=failed, jobs=jobs, secs=round(time.time() - t0), log=log, at=time.strftime("%F %T"))
    json.dump(verdict, open(os.path.join(C.ctl_dir(), "verify.json"), "w"), indent=1)
    print("verify %s: %s (%s) %ds, log %s" % (sha[:8], "GREEN" if not failed else "RED " + ", ".join(failed + jobs), res, verdict["secs"], log))
    if failed:
        import argparse as _ap
        name = "fix-landed-%s" % sha[:8]
        task = ("Master at %s went RED in the post-landing check (%s; failing jobs: %s; log %s). Find which recently landed commit "
                "broke it (`git log --oneline -15`, then run just the failing job on a suspect), and fix it at the root, with a "
                "narrow test. Light worker rules apply: no full gate. Commit, clean tree, CONTROL-STATUS line."
                % (sha[:8], ", ".join(failed), ", ".join(jobs) or "see log", log))
        C.cmd_enqueue(_ap.Namespace(name=name, claim=["task:" + name], task=task, task_file=None, file=[], base="master",
                                    needs=[], model=None))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
