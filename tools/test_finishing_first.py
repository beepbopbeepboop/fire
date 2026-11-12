#!/usr/bin/env python3
"""Two flow fixes found by the 2026-11-12 review of the live swarm:
(1) the verifier's private tree must never block its own checkout: uncommitted edits are saved as a patch, then reset;
(2) refill starts the tasks that FINISH done work (fix-merge-/fix-proof-/fix-orch-/fix-red-) before fresh docs."""
import os, subprocess, sys, tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C, verify_landed as V

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def main():
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(repo)
        g(repo, "init", "-q", "-b", "master")
        open(os.path.join(repo, "f.py"), "w").write("a = 1\n"); g(repo, "add", "."); g(repo, "commit", "-q", "-m", "one")
        first = g(repo, "rev-parse", "HEAD")
        open(os.path.join(repo, "f.py"), "w").write("a = 2\n"); g(repo, "commit", "-qam", "two")
        second = g(repo, "rev-parse", "HEAD")
        ver = os.path.join(d, "work-verify"); g(repo, "worktree", "add", "-q", "--detach", ver, first)
        open(os.path.join(ver, "f.py"), "w").write("a = 'a stray hand edit'\n")        # someone edited the verifier's tree
        ctl = os.path.join(d, "ctl"); os.makedirs(ctl)
        with mock.patch.object(V, "VERIFY", ver), mock.patch.object(C, "ctl_dir", lambda: ctl):
            V.checkout(second)
        assert g(ver, "rev-parse", "HEAD") == second, "the checkout must succeed"
        assert open(os.path.join(ver, "f.py")).read() == "a = 2\n", "the tree is clean at the new sha"
        patches = [f for f in os.listdir(ctl) if f.startswith("verify-dirty-")]
        assert len(patches) == 1 and "a stray hand edit" in open(os.path.join(ctl, patches[0])).read(), "the edit is saved, not lost"
        # (2) order
        names = ["bug-fresh-old", "fix-proof-x", "bug-fresh-new", "fix-merge-y", "fix-orch-z"]
        items = [{"name": n, "added": i} for i, n in enumerate(names)]
        got = [i["name"] for i in sorted(items, key=C.refill_key)]
        assert got == ["fix-proof-x", "fix-merge-y", "fix-orch-z", "bug-fresh-old", "bug-fresh-new"], got
    print("test_finishing_first: ok")


if __name__ == "__main__":
    main()
