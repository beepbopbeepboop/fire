#!/usr/bin/env python3
"""integrate.land_on_master: master moving while a round gates must not strand the round.

Throwaway repo: master checked out in MAIN, the round on `integ` in a second worktree. Cases:
(1) master gained a merge commit that changes no file: the gated tree lands over it;
(2) master gained a real file from another lane: master is merged into the round, the landing gate re-runs ONCE on
    that result, and the round lands with both changes;
(3) the same, but the re-gate is red: SystemExit, master untouched;
(4) master's new change conflicts with the round: SystemExit, master untouched."""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control, integrate as I

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def write(cwd, f, text):
    open(os.path.join(cwd, f), "w").write(text)


def fresh(d, n):
    repo = os.path.join(d, "repo%d" % n); integ = os.path.join(d, "integ%d" % n)
    os.makedirs(repo)
    g(repo, "init", "-q", "-b", "master"); write(repo, "a.txt", "a\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "root")
    g(repo, "worktree", "add", "-q", "-b", "integ", integ, "master")
    write(integ, "round.txt", "the round\n"); g(integ, "add", "."); g(integ, "commit", "-q", "-m", "round")
    control.MAIN = repo; I.C.MAIN = repo; I.INTEG = integ
    return repo, integ


def raises(fn):
    try:
        fn()
    except SystemExit:
        return True
    return False


def main():
    with tempfile.TemporaryDirectory() as d:
        repo, integ = fresh(d, 1)                                        # (1) a move that changes no file
        g(repo, "commit", "-q", "--allow-empty", "-m", "another lane's empty merge")
        I.land_on_master(); assert os.path.exists(os.path.join(repo, "round.txt")), "round must land over an empty move"

        repo, integ = fresh(d, 2)                                        # (2) a real file landed by another lane
        write(repo, "other.txt", "other lane\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "other lane")
        calls = []
        I.land_on_master(lambda: calls.append(1) or 0)
        assert calls == [1], "the landing gate re-runs exactly once on the merged round: %r" % calls
        assert all(os.path.exists(os.path.join(repo, f)) for f in ("round.txt", "other.txt")), "both changes on master"

        repo, integ = fresh(d, 3)                                        # (3) re-gate red: master untouched
        write(repo, "other.txt", "x\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "other lane")
        before = g(repo, "rev-parse", "master")
        assert raises(lambda: I.land_on_master(lambda: 1)) and g(repo, "rev-parse", "master") == before

        repo, integ = fresh(d, 4)                                        # (4) conflict with the round: master untouched
        write(integ, "same.txt", "round side\n"); g(integ, "add", "."); g(integ, "commit", "-q", "-m", "round same")
        write(repo, "same.txt", "master side\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "other same")
        before = g(repo, "rev-parse", "master")
        assert raises(lambda: I.land_on_master(lambda: 0)) and g(repo, "rev-parse", "master") == before
    print("test_land_master_moved: ok")


if __name__ == "__main__":
    main()
