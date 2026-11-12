#!/usr/bin/env python3
"""control.py cleanup retires work/* branches nothing will land, and loses no commit doing it.

Builds a throwaway repo (control.MAIN pointed at it) with: a chain of attempt branches (a <- b <- c, each cut from
the last; c has no task, so it is archived and a/b with it), a held/abandoned dead branch, an orphan branch the registry forgot, an abandoned-NOT-held branch
(`continue` cuts its successor from it), a running branch, and a young branch. Checks that subsumed branches are
deleted, dead ones archived under refs/archive/ (recoverable), clean idle trees of those go too, and the rest stay."""
import argparse, io, json, os, subprocess, sys, tempfile, time
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a, **kw):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env={**ENV, **kw}).stdout.strip()


def commit(repo, branch, msg, base=None, date=None):
    g(repo, "checkout", "-q", *(["-b", branch, base] if base else [branch]))
    extra = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else {}
    g(repo, "commit", "-q", "--allow-empty", "-m", msg, **extra)
    g(repo, "checkout", "-q", "master")


def branches(repo):
    return set(g(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/work/").split())


def main():
    old = "2020-01-01T00:00:00"
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(repo)
        ctl = os.path.join(d, "ctl"); os.makedirs(ctl)
        g(repo, "init", "-q", "-b", "master"); g(repo, "commit", "-q", "--allow-empty", "-m", "root")
        commit(repo, "work/a", "a", "master", old)
        commit(repo, "work/b", "b", "work/a", old)          # a continuation of a: a is SUBSUMED by b
        commit(repo, "work/c", "c", "work/b", old)          # and b by c
        commit(repo, "work/dead", "dead", "master", old)    # abandoned + held: archived
        commit(repo, "work/orphan", "orphan", "master", old)  # no registry entry: archived
        commit(repo, "work/cont", "cont", "master", old)    # abandoned, NOT held: a continuation may be cut from it
        commit(repo, "work/run", "run", "master", old)      # running
        commit(repo, "work/young", "young", "master")       # too young to touch
        wt = os.path.join(d, "work-a")
        g(repo, "worktree", "add", "-q", wt, "work/a")      # the subsumed branch has a clean, idle tree
        reg = {"t-dead": {"branch": "work/dead", "worktree": os.path.join(d, "nowhere"), "state": "abandoned", "hold": True},
               "t-cont": {"branch": "work/cont", "worktree": os.path.join(d, "nowhere"), "state": "abandoned"},
               "t-run": {"branch": "work/run", "worktree": os.path.join(d, "nowhere"), "state": "running"}}
        json.dump(reg, open(os.path.join(ctl, "tasks.json"), "w"))
        os.makedirs(os.path.join(ctl, "queue"), exist_ok=True)
        os.environ["CONTROL_CTL_DIR"] = ctl
        control.MAIN = repo
        control.live_session_dirs = lambda *a, **k: set()
        control.live_cwds = lambda *a, **k: set()
        control._claimed_by_outside = lambda p: False

        a = argparse.Namespace(dry_run=False, branches=True, prune=False, jobs=4)
        buf = io.StringIO()
        with redirect_stdout(buf):
            control.cmd_cleanup(a)
        out = buf.getvalue()
        left = branches(repo)
        assert left == {"work/cont", "work/run", "work/young"}, (left, out)
        assert not os.path.exists(wt), "the clean idle tree of a subsumed branch must go:\n" + out
        archived = set(g(repo, "for-each-ref", "--format=%(refname:short)", "refs/archive/").split())
        assert archived == {"archive/work/c", "archive/work/dead", "archive/work/orphan"}, archived   # c: no task, tip of the a<-b<-c chain
        # nothing lost: every commit is still reachable from a branch or an archive ref
        reach = g(repo, "log", "--format=%s", "--branches", "--glob=refs/archive/*").split()
        assert {"a", "b", "c", "dead", "orphan", "cont", "run", "young"} <= set(reach), reach
    print("test_control_branch_retire: ok")


if __name__ == "__main__":
    main()
