#!/usr/bin/env python3
"""control.py status/prune: which registry entries are DONE-AND-GONE, and that prune never drops anything else.

Builds a throwaway git repo (control.MAIN pointed at it) and a registry, then checks each case."""
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
        g(repo, "branch", "work/merged")                       # merged: points at master
        g(repo, "branch", "work/ahead"); g(repo, "checkout", "-q", "work/ahead")
        g(repo, "commit", "-q", "--allow-empty", "-m", "x"); g(repo, "checkout", "-q", "master")
        wt = os.path.join(d, "work-live"); os.makedirs(wt)
        T = lambda slot, state, branch, worktree: {"slot": slot, "state": state, "branch": branch,
                                                   "worktree": worktree, "pid": 0, "claims": []}
        gone = os.path.join(d, "work-gone")
        reg = {
            "gone-merged": T(1, "integrated", "work/merged", gone),
            "gone-nobranch": T(2, "abandoned", "work/deleted", gone),
            "gone-superseded": T(3, "superseded", "work/merged", gone),
            "unmerged": T(4, "integrated", "work/ahead", gone),
            "has-worktree": T(5, "integrated", "work/merged", wt),
            "running-state": T(6, "exited-ok", "work/merged", gone),
            "failed": T(7, "integration-failed", "work/merged", gone),
            "held": T(8, "held", "work/merged", gone),
        }
        control.MAIN = repo
        os.environ["CONTROL_CTL_DIR"] = ctl
        os.makedirs(ctl)
        json.dump(reg, open(os.path.join(ctl, "tasks.json"), "w"))

        um = control.unmerged_branches()
        assert um == {"work/ahead"}, um
        expect_gone = {"gone-merged", "gone-nobranch", "gone-superseded"}
        assert {n for n, t in reg.items() if control.done_and_gone(t, um)} == expect_gone

        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_status(argparse.Namespace(all=False, verbose=False))
        out = buf.getvalue()
        for n in set(reg) - expect_gone: assert n in out, n
        for n in expect_gone: assert n not in out, n
        assert "+3 finished tasks hidden" in out, out
        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_status(argparse.Namespace(all=True, verbose=False))
        assert all(n in buf.getvalue() for n in reg) and "hidden" not in buf.getvalue()

        with redirect_stdout(io.StringIO()):
            assert set(control.cmd_prune(argparse.Namespace(dry_run=True))) == expect_gone
        assert set(control.load()) == set(reg), "dry-run must not write"
        with redirect_stdout(io.StringIO()):
            control.cmd_prune(argparse.Namespace(dry_run=False))
        assert set(control.load()) == set(reg) - expect_gone
    print("test_control_status: ok")


if __name__ == "__main__":
    main()
