#!/usr/bin/env python3
"""Regression test: prune never drops entries whose branch ref exists with commits outside master.

Previously, when `unmerged_branches()` returned an empty set (because the git command failed or
master was unresolvable in the worktree context), `done_and_gone` treated every branch as merged
and pruned terminal entries whose worktree dir no longer matched. This test simulates that scenario:
a throwaway git repo acts as `MAIN`, `control.MAIN` is pointed at it, and an unmerged branch with a
commit not on master exists. `cmd_prune` must keep the terminal registry entry.

The fix: `unmerged_branches()` returns None when the merge check can't be read, and
`done_and_gone()` refuses to prune when `unmerged` is None.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
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
        g(repo, "init", "-q", "-b", "master")
        g(repo, "commit", "-q", "--allow-empty", "-m", "root")

        # A worktree detached at master, like the fleet worktree
        wt = os.path.join(d, "work-1")
        g(repo, "worktree", "add", "-q", "--detach", wt, "master")

        # A registry entry for a terminal task whose branch has unmerged commits
        ctl = os.path.join(d, "ctl")
        os.makedirs(ctl)
        os.environ["CONTROL_CTL_DIR"] = ctl
        tasks_json = os.path.join(ctl, "tasks.json")
        with open(tasks_json, "w") as f:
            json.dump({
                "test-task-1": {
                    "slot": 1,
                    "state": "finished",   # terminal state
                    "worktree": wt,
                    "branch": "work/fix-some-feature",
                    "claims": [],
                }
            }, f)

        control.MAIN = repo

        # Create an unmerged branch with a commit outside master
        g(repo, "branch", "work/fix-some-feature")
        g(repo, "checkout", "-q", "work/fix-some-feature")
        g(repo, "commit", "-q", "--allow-empty", "-m", "feature commit")
        g(repo, "checkout", "-q", "master")

        # Verify the fix: unmerged_branches() must see the branch as unmerged
        um = control.unmerged_branches()
        assert um == {"work/fix-some-feature"}, um

        # Prune: the terminal entry must be KEPT (branch has unmerged commits)
        a = argparse.Namespace(dry_run=False, branches=False, prune=True, jobs=16)
        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_prune(a)
        out = buf.getvalue()

        with open(tasks_json, "r") as f:
            tasks = json.load(f)

        if "test-task-1" not in tasks:
            print("BUG: terminal entry with unmerged branch was pruned! Output:", out)
            return 1
        print("test_control_prune_unmerged: ok")
        return 0


if __name__ == "__main__":
    sys.exit(main())