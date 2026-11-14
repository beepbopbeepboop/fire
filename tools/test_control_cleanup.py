#!/usr/bin/env python3
"""control.py cleanup: never removes a work-* tree that a live process is working in
(bugs/ORCH_cleanup_removes_a_worktree_under_a_running_test).

2026-11-10 a full gimple-runner run in a detached worktree at master was removed mid-run by
`cleanup`: the registry knows only workers it started, the session list only opencode sessions,
and outside claims only what someone registered — a hand-started run is none of those, the tree
is merged and clean (a run writes only ignored files), so every check passed and `git worktree
remove` agreed. The protection now is the process table: a tree whose directory is a live
process's cwd (or holds one) is kept, even at the moment of removal.

Builds a throwaway git repo (control.MAIN pointed at it) and a detached worktree, runs a real
process in it, and checks each half: with the process the tree survives; without it, cleanup
removes the tree as before."""
import argparse, io, json, os, subprocess, sys, tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control


def g(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def main():
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(repo)
        ctl = os.path.join(d, "ctl")
        g(repo, "init", "-q", "-b", "master"); g(repo, "commit", "-q", "--allow-empty", "-m", "root")
        # a detached tree at master, exactly like the incident's work-gr-master: merged, clean,
        # no registry entry, no opencode session, no outside claim
        wt = os.path.join(d, "work-1")
        g(repo, "worktree", "add", "-q", "--detach", wt, "master")

        os.environ["CONTROL_CTL_DIR"] = ctl
        os.makedirs(ctl)
        json.dump({}, open(os.path.join(ctl, "tasks.json"), "w"))
        control.MAIN = repo
        control.live_session_dirs = lambda *a, **k: set()   # the session check is tested on its own; isolate the process check

        a = argparse.Namespace(dry_run=False, branches=False, prune=False, jobs=16)

        # 1. a plain process working in the tree keeps it alive
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=wt)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                control.cmd_cleanup(a)
            out = buf.getvalue()
            assert os.path.isdir(wt), "cleanup removed a worktree with a live process in it:\n" + out
            assert "live process in tree" in out, out
        finally:
            p.terminate(); p.wait()

        # 2. once nothing is in it, the same tree is removed as before
        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_cleanup(a)
        out = buf.getvalue()
        assert not os.path.exists(wt), "a free merged clean worktree must still be removed:\n" + out
        assert "removed 1 worktrees" in out, out
    print("test_control_cleanup: ok")


if __name__ == "__main__":
    main()
