#!/usr/bin/env python3
"""The full gate takes hours and must not stop landings: master marches on while it runs.

(1) the verifier's lock is its OWN: holding the integrator lock does not stop a verifier, a second verifier is refused;
(2) land_ledger: when master has moved since the gate's sha, the ledger commit is MERGED onto the master of the day and
    both changes are there; a conflicting move leaves master untouched; a busy integrator lock leaves it on its branch."""
import fcntl, os, subprocess, sys, tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C, verify_landed as V

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def w(repo, f, text):
    open(os.path.join(repo, f), "w").write(text)


def fresh(d, n):
    repo = os.path.join(d, "repo%d" % n); os.makedirs(repo)
    g(repo, "init", "-q", "-b", "master"); w(repo, "suite.py", "line1\nMARK = None\nline3\n"); w(repo, "other.txt", "o\n")
    g(repo, "add", "."); g(repo, "commit", "-q", "-m", "root"); sha = g(repo, "rev-parse", "HEAD")
    g(repo, "checkout", "-q", "-b", "verify-ledger"); w(repo, "suite.py", "line1\nMARK = 'disabled'\nline3\n")
    w(repo, "gate-x.md", "# gate\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "ledger")
    new = g(repo, "rev-parse", "HEAD"); g(repo, "checkout", "-q", "master")
    return repo, sha, new


def main():
    with tempfile.TemporaryDirectory() as d:
        ctl = os.path.join(d, "ctl"); os.makedirs(ctl)
        with mock.patch.object(C, "ctl_dir", lambda: ctl):
            integ = open(os.path.join(ctl, "integrator.lock"), "w"); fcntl.flock(integ, fcntl.LOCK_EX)   # the integrator is landing
            v1 = V.verify_lock(); assert v1 is not None, "a verifier must run while the integrator holds ITS lock"
            assert V.verify_lock() is None, "but only one verifier at a time"
            v1.close(); integ.close()
            # (2) master moved in an unrelated file: merged
            repo, sha, new = fresh(d, 1)
            w(repo, "other.txt", "another lane landed\n"); g(repo, "commit", "-qam", "lane")
            with mock.patch.object(C, "MAIN", repo):
                assert V.land_ledger(new, sha, wait_s=0) is True
            assert "disabled" in open(os.path.join(repo, "suite.py")).read() and os.path.exists(os.path.join(repo, "gate-x.md"))
            assert open(os.path.join(repo, "other.txt")).read() == "another lane landed\n", "the other lane's change is kept"
            # master unmoved: fast-forward
            repo, sha, new = fresh(d, 2)
            with mock.patch.object(C, "MAIN", repo):
                assert V.land_ledger(new, sha, wait_s=0) is True and g(repo, "rev-parse", "HEAD") == new
            # master moved with a CONFLICT on the marker line: untouched
            repo, sha, new = fresh(d, 3)
            w(repo, "suite.py", "line1\nMARK = 'someone else'\nline3\n"); g(repo, "commit", "-qam", "conflicting"); before = g(repo, "rev-parse", "HEAD")
            with mock.patch.object(C, "MAIN", repo):
                assert V.land_ledger(new, sha, wait_s=0) is False and g(repo, "rev-parse", "HEAD") == before
            # integrator lock busy: stays on its branch
            repo, sha, new = fresh(d, 4)
            integ = open(os.path.join(ctl, "integrator.lock"), "w"); fcntl.flock(integ, fcntl.LOCK_EX)
            with mock.patch.object(C, "MAIN", repo):
                assert V.land_ledger(new, sha, wait_s=0) is False and g(repo, "rev-parse", "HEAD") == sha
            integ.close()
    print("test_verify_lock: ok")


if __name__ == "__main__":
    main()
