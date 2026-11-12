#!/usr/bin/env python3
"""A DONE branch that deletes a bug doc but changes no test is handed to a REVIEWER (fix-proof-*), not to a person.

Throwaway repo (control.git pinned to it). Checks pick_candidates: (1) such a branch is not landable and is reported in
proof_out; (2) a branch that changes a test file is landable; (3) a `fix-proof-*` branch with a `NOTESTCASE: <reason>`
commit is landable; (4) an empty NOTESTCASE is no decision; (5) a NON-reviewer cannot self-certify with the marker.
Then enqueue_proof_review: queues fix-proof-<name> on the branch, hands the original over (superseded, fixer set), and
stops after PROOF_DEPTH reviews."""
import json, os, subprocess, sys, tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C, integrate as I

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def main():
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(os.path.join(repo, "bugs"))
        g(repo, "init", "-q", "-b", "master")
        for n in "abcde":
            open(os.path.join(repo, "bugs", "DOC_%s.md" % n), "w").write("# doc %s\n" % n)
        g(repo, "add", "."); g(repo, "commit", "-q", "-m", "root")

        def branch(name, msg, test=False):
            b = "work/" + name
            g(repo, "checkout", "-q", "-b", b, "master")
            g(repo, "rm", "-q", "bugs/DOC_%s.md" % name[-1])
            if test:
                open(os.path.join(repo, "test_%s.py" % name), "w").write("def test_x(): pass\n"); g(repo, "add", ".")
            g(repo, "commit", "-q", "-m", msg)
            g(repo, "checkout", "-q", "master")
            return {"branch": b, "worktree": os.path.join(d, "nowhere"), "slot": 1, "state": "exited-ok", "claims": ["bug:DOC_%s" % name[-1]],
                    "summary": "s", "cls": "easy"}
        reg = {"bug-a": branch("bug-a", "fix a"),
               "bug-b": branch("bug-b", "fix b", test=True),
               "fix-proof-c": branch("fix-proof-c", "review\n\nNOTESTCASE: obsolete; fixed by commit abc123 on master"),
               "fix-proof-d": branch("fix-proof-d", "review\n\nNOTESTCASE:"),
               "bug-e": branch("bug-e", "fix e\n\nNOTESTCASE: i say so")}
        orig = C.git
        patches = [mock.patch.object(C, "git", lambda *a, cwd=repo, check=True: orig(*a, cwd=cwd, check=check)),
                   mock.patch.object(C, "load", lambda: reg), mock.patch.object(C, "state_of", lambda t: t["state"]),
                   mock.patch.object(C, "verdict", lambda t: "DONE"), mock.patch.object(C, "tree_extras", lambda wt: []),
                   mock.patch.object(C, "MAIN", repo)]
        for p in patches: p.start()
        try:
            proofs = []
            got = set(I.pick_candidates(quiet=True, proof_out=proofs))
            assert got == {"bug-b", "fix-proof-c"}, got
            assert sorted(n for n, _ in proofs) == ["bug-a", "bug-e", "fix-proof-d"], proofs   # no test, and no reviewer's NOTESTCASE
            assert I.has_notestcase("work/fix-proof-c") and not I.has_notestcase("work/fix-proof-d")

            queued = []
            with mock.patch.object(C, "cmd_enqueue", lambda ns: queued.append(ns)), \
                 mock.patch.object(C, "free_task_name", lambda n, limit=60: n), \
                 mock.patch.object(C, "retire_task", lambda n: True), \
                 mock.patch.object(C, "registry") as R:
                R.return_value.__enter__ = lambda s: reg; R.return_value.__exit__ = lambda s, *a: False
                I.enqueue_proof_review("bug-a", reg["bug-a"], ["bugs/DOC_a.md"])
                assert queued[0].name == "fix-proof-bug-a" and queued[0].base == "work/bug-a"
                assert queued[0].claim == ["bug:DOC_a"] and "NOTESTCASE" in queued[0].task and "TEST" in queued[0].task
                assert "Both TEST and NOTESTCASE are legitimate" in queued[0].task, "NOTESTCASE must be a legitimate outcome, not a last resort"
                assert reg["bug-a"]["state"] == "superseded" and reg["bug-a"]["fixer"] == "fix-proof-bug-a"
                reg["fix-proof-fix-proof-bug-a"] = dict(reg["bug-a"], state="exited-ok")
                I.enqueue_proof_review("fix-proof-fix-proof-bug-a", reg["fix-proof-fix-proof-bug-a"], ["bugs/DOC_a.md"])
                assert len(queued) == 1, "past PROOF_DEPTH no further reviewer is queued"
                assert reg["fix-proof-fix-proof-bug-a"].get("merge_capped"), "and the branch is capped, not looped"
        finally:
            for p in patches: p.stop()
    print("test_proof_review: ok")


if __name__ == "__main__":
    main()
