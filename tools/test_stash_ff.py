#!/usr/bin/env python3
"""stash_ff.merge: a merge into a dirty checkout lands, or is undone cleanly; the edits are never lost.

Run: python3 tools/test_stash_ff.py
"""
import os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stash_ff as S


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Merge(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="sff_")
        g(self.d, "init", "-q", "-b", "master")
        g(self.d, "config", "user.email", "t@t"); g(self.d, "config", "user.name", "t")
        self.w("a.txt", "one\ntwo\nthree\n"); self.w("b.txt", "x\n")
        g(self.d, "add", "-A"); g(self.d, "commit", "-qm", "init")
        g(self.d, "branch", "integ")
        self.master = g(self.d, "rev-parse", "HEAD")

    def w(self, n, t):
        open(os.path.join(self.d, n), "w").write(t)

    def r(self, n):
        return open(os.path.join(self.d, n)).read()

    def land(self, name, text):
        g(self.d, "switch", "-q", "integ"); self.w(name, text)
        g(self.d, "commit", "-qam", "land " + name); g(self.d, "switch", "-q", "master")

    def test_clean_checkout_fast_forwards(self):
        self.land("b.txt", "y\n")
        self.assertEqual(S.merge(self.d, "--ff-only", "integ"), ("ok", ""))
        self.assertEqual(self.r("b.txt"), "y\n")

    def test_edit_to_a_file_the_landing_also_changes_is_carried_across(self):
        self.land("a.txt", "landed\ntwo\nthree\n")
        self.w("a.txt", "one\ntwo\nmine\n")
        self.assertEqual(S.merge(self.d, "--ff-only", "integ")[0], "ok")
        self.assertEqual(self.r("a.txt"), "landed\ntwo\nmine\n")
        self.assertEqual(g(self.d, "stash", "list"), "")

    def test_a_conflicting_edit_undoes_the_merge_and_loses_nothing(self):
        self.land("a.txt", "landed\ntwo\nthree\n")
        self.w("a.txt", "mine\ntwo\nthree\n")
        st, detail = S.merge(self.d, "--ff-only", "integ")
        self.assertEqual(st, "blocked", detail)
        self.assertEqual(g(self.d, "rev-parse", "HEAD"), self.master)        # master did not move
        self.assertEqual(self.r("a.txt"), "mine\ntwo\nthree\n")             # the edit is exactly as it was
        self.assertEqual(g(self.d, "stash", "list"), "")                    # restored, so the entry is gone

    def test_a_merge_that_is_not_a_fast_forward_fails_and_restores_the_edits(self):
        self.land("b.txt", "y\n")
        self.w("a.txt", "one\ntwo\nmine\n"); g(self.d, "commit", "-qam", "master moved")
        self.w("a.txt", "one\ntwo\nmine2\n")
        st, _ = S.merge(self.d, "--ff-only", "integ")
        self.assertEqual(st, "failed")
        self.assertEqual(self.r("a.txt"), "one\ntwo\nmine2\n")

    def test_another_worktrees_stash_entry_is_never_touched(self):
        self.w("b.txt", "old edit\n"); g(self.d, "stash", "push", "-m", "someone else")
        self.land("a.txt", "landed\ntwo\nthree\n"); self.w("a.txt", "one\ntwo\nmine\n")
        self.assertEqual(S.merge(self.d, "--ff-only", "integ")[0], "ok")
        self.assertIn("someone else", g(self.d, "stash", "list"))


if __name__ == "__main__":
    unittest.main()
