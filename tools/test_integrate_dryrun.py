#!/usr/bin/env python3
"""integrate.py --dry-run must report and do nothing else: a conflicting candidate is left out, no merge fixer is
queued, and the registry is untouched (2026-11-12: a dry run enqueued a fixer task because only --no-fixers and
--probe guarded the conflict path — and the fixer landed in the live fleet queue, startable).

Throwaway repo + temporary registry: master in MAIN, a candidate branch that conflicts with it, a bugs/ doc so a
fixer would be allowed (proving the dry run, not the doc check, is what stops the enqueue). Runs integrate.main()
with argv=[--dry-run] and asserts nothing was queued and the task kept its state; the positive control (no
--dry-run) shows the same conflict DOES queue a fixer. Never touches the live registry: control.ctl_dir and
control.MAIN are pointed at the throwaway tree (the default is the absolute fleet path)."""
import json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control, integrate as I

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def write(p, s):
    open(p, "w").write(s)


def make_repo(d):
    repo = os.path.join(d, "repo"); integ = os.path.join(d, "integ")
    os.makedirs(os.path.join(repo, "bugs"))
    write(os.path.join(repo, "bugs", "TASKY" + ".md"), "# tasky\n")
    write(os.path.join(repo, "a.txt"), "master\n")
    g(repo, "init", "-q", "-b", "master"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "root")
    g(repo, "checkout", "-q", "-b", "work/tasky"); write(os.path.join(repo, "a.txt"), "candidate\n")
    g(repo, "commit", "-qam", "candidate")
    g(repo, "checkout", "-q", "master"); write(os.path.join(repo, "a.txt"), "master moved\n")
    g(repo, "commit", "-qam", "master moves")
    ctl = os.path.join(d, "control"); os.makedirs(os.path.join(ctl, "queue"))
    wt = os.path.join(d, "tasky-wt"); os.makedirs(wt)
    write(os.path.join(wt, "work.log"), "=== spawned tasky ===\nCONTROL-STATUS: DONE\n")
    reg = {"tasky": {"name": "tasky", "slot": 1, "worktree": wt, "branch": "work/tasky",
                     "claims": ["bug:TASKY"], "model": "m", "pid": 0,
                     "started": "2026-11-12 22:00:00", "state": "exited-ok", "summary": "tasky"}}
    write(os.path.join(ctl, "tasks.json"), json.dumps(reg))
    return repo, integ, ctl


def run_main(argv):
    old = sys.argv
    sys.argv = ["integrate.py"] + argv
    try:
        I.main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = old
    return 0


def stub_git(repo):
    """control.git's default cwd is bound at import time to the absolute fleet checkout; route every call that
    does not name an explicit cwd into the throwaway repo instead, or the test would read the fleet's real refs."""
    real_git = control.git
    def git(*a, cwd=None, check=True):
        return real_git(*a, cwd=cwd or repo, check=check)
    control.git = git
    return real_git


def main():
    with tempfile.TemporaryDirectory() as d:
        repo, integ, ctl = make_repo(d)
        saved = (control.MAIN, control.ctl_dir, control.git, I.INTEG)
        control.MAIN = repo
        control.ctl_dir = lambda: ctl          # never the absolute fleet registry
        real_git = stub_git(repo)              # never the absolute fleet checkout
        I.INTEG = integ                        # never ../work-integ
        try:
            code = run_main(["--dry-run"])
            assert code == 0, "dry-run exits 0"
            queue = os.listdir(os.path.join(ctl, "queue"))
            leaked = [n for n in queue if n.startswith("fix-merge")]
            assert not leaked, "a dry run must not queue a merge fixer: %r" % leaked
            t = json.load(open(os.path.join(ctl, "tasks.json")))["tasky"]
            assert t["state"] == "exited-ok" and "fixer" not in t, \
                "a dry run must not touch the registry: %r" % t
            # positive control: the same conflict without --dry-run DOES queue a fixer
            run_main([])
            queue = os.listdir(os.path.join(ctl, "queue"))
            assert any(n.startswith("fix-merge-tasky") for n in queue), \
                "expected a queued merge fixer, got %r" % queue
        finally:
            control.MAIN, control.ctl_dir, control.git, I.INTEG = saved
    print("test_integrate_dryrun: ok")


if __name__ == "__main__":
    main()
