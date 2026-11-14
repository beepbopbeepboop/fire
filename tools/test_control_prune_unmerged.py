#!/usr/bin/env python3
"""Regression test: when the merge check cannot be read, prune drops nothing.

2026-11-11: the task registry was cleaned before the orchestrator restart and 572 entries whose
branches held commits master does not have were removed from the registry (the only record mapping
entry -> branch/worktree/claims). The branches and worktrees were left alone; only the registry rows
were lost.

Root cause: `unmerged_branches()` ran `git for-each-ref --no-merged master` and discarded the exit
code, so an unreadable merge state (master unresolvable in the worktree context) came back as an
EMPTY set — every branch read as "merged". `done_and_gone()` then called a terminal entry with a
missing worktree DONE-AND-GONE, and `cmd_prune` dropped it, unlanded commits and all. A failed merge
check must mean "keep", never "merged".

This test builds a repo where `master` does not resolve (exactly the worktree-context failure mode)
and points control.MAIN at it:

  * `unmerged_branches()` must report the merge state as unreadable (None), not as an empty set.
  * `cmd_prune` must KEEP a terminal registry entry whose branch has commits outside the default
    branch, even though its worktree directory is gone.
  * `cmd_status` must not crash on the same unreadable merge state, and must keep showing the entry.

On the pre-fix code the entry was pruned (and, with the first fix but without the cmd_status guard,
status crashed with TypeError), so this test fails there and passes only with the complete fix.
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
        # A repo whose default branch is not master: `git for-each-ref --no-merged master` fails,
        # the "merge check can't be read" case.
        repo = os.path.join(d, "repo")
        os.makedirs(repo)
        g(repo, "init", "-q", "-b", "main")
        g(repo, "commit", "-q", "--allow-empty", "-m", "root")
        g(repo, "branch", "work/fix-some-feature")
        g(repo, "checkout", "-q", "work/fix-some-feature")
        g(repo, "commit", "-q", "--allow-empty", "-m", "unlanded work")
        g(repo, "checkout", "-q", "main")

        gone = os.path.join(d, "work-gone")  # worktree directory does NOT exist: prune's target

        ctl = os.path.join(d, "ctl")
        os.makedirs(ctl)
        os.environ["CONTROL_CTL_DIR"] = ctl
        tasks_json = os.path.join(ctl, "tasks.json")
        with open(tasks_json, "w") as f:
            json.dump({
                "test-task-1": {
                    "slot": 1,
                    "state": "abandoned",  # terminal
                    "worktree": gone,
                    "branch": "work/fix-some-feature",
                    "claims": [],
                    "pid": 0,
                }
            }, f)

        control.MAIN = repo

        um = control.unmerged_branches()
        if um is not None:
            print("BUG: unreadable merge check reported as %r, not None" % (um,))
            return 1

        a = argparse.Namespace(dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_prune(a)
        with open(tasks_json) as f:
            tasks = json.load(f)
        if "test-task-1" not in tasks:
            print("BUG: terminal entry with unlanded commits was pruned when the merge check "
                  "could not be read! Output:", buf.getvalue())
            return 1

        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                control.cmd_status(argparse.Namespace(all=False, verbose=False))
        except TypeError as e:
            print("BUG: cmd_status crashed on an unreadable merge state: %s" % e)
            return 1
        if "test-task-1" not in buf.getvalue():
            print("BUG: cmd_status hid a live entry when the merge check could not be read! "
                  "Output:", buf.getvalue())
            return 1
        print("test_control_prune_unmerged: ok")
        return 0


if __name__ == "__main__":
    sys.exit(main())
