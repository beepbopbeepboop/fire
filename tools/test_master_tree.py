#!/usr/bin/env python3
"""master_tree: the integrator's own master tree, and the stash-safe sync of the developer checkout.

Run: python3 tools/test_master_tree.py
"""
import os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import master_tree as M


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Trees(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp(prefix="mt_")
        self.root = os.path.join(base, "repo")
        os.makedirs(self.root)
        g(self.root, "init", "-q", "-b", "master")
        g(self.root, "config", "user.email", "t@t"); g(self.root, "config", "user.name", "t")
        for n in ("a.txt", "b.txt"):
            open(os.path.join(self.root, n), "w").write("one\ntwo\nthree\n")
        g(self.root, "add", "-A"); g(self.root, "commit", "-q", "-m", "init")
        M.ROOT = self.root
        self.mt = os.path.join(base, "work-master")

    def land(self, name, text):
        open(os.path.join(self.mt, name), "w").write(text)
        g(self.mt, "commit", "-qam", "land " + name)

    def test_setup_moves_master_out_and_keeps_edits_in_place(self):
        open(os.path.join(self.root, "a.txt"), "w").write("mine\ntwo\nthree\n")
        M.setup("dev", self.mt)
        self.assertEqual(M.branch_of(self.root), "dev")
        self.assertEqual(M.branch_of(self.mt), "master")
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read().splitlines()[0], "mine")
        self.assertEqual(os.path.realpath(M.master_tree()), os.path.realpath(self.mt))

    def test_a_landing_that_touches_a_file_you_have_dirty_no_longer_blocks_and_sync_merges_both(self):
        open(os.path.join(self.root, "a.txt"), "w").write("one\ntwo\nmine\n")           # your edit, bottom
        M.setup("dev", self.mt)
        self.land("a.txt", "landed\ntwo\nthree\n")                                      # a landing, top: same file
        self.assertEqual(M.sync(self.root), 0)
        self.assertEqual(open(os.path.join(self.root, "a.txt")).read(), "landed\ntwo\nmine\n")
        self.assertEqual(g(self.root, "stash", "list"), "")                              # dropped after a clean apply

    def test_a_conflicting_edit_is_kept_in_the_stash_not_dropped(self):
        open(os.path.join(self.root, "a.txt"), "w").write("mine\ntwo\nthree\n")
        M.setup("dev", self.mt)
        self.land("a.txt", "landed\ntwo\nthree\n")
        self.assertEqual(M.sync(self.root), 1)
        self.assertIn("master_tree sync", g(self.root, "stash", "list"))
        self.assertIn("<<<<<<<", open(os.path.join(self.root, "a.txt")).read())

    def test_sync_without_edits_just_fast_forwards(self):
        M.setup("dev", self.mt)
        self.land("b.txt", "new\n")
        self.assertEqual(M.sync(self.root), 0)
        self.assertEqual(open(os.path.join(self.root, "b.txt")).read(), "new\n")

    def test_sync_refuses_to_run_on_master_itself(self):
        with self.assertRaises(SystemExit):
            M.sync(self.root)


if __name__ == "__main__":
    unittest.main()
