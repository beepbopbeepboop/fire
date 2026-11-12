#!/usr/bin/env python3
"""gate_ledger: what needs a gate, the bisection, the expect= splice, and the ledger's state machine.

Run: python3 tools/test_gate_ledger.py
"""
import ast, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_ledger as G

def _doc(name):
    return "bugs/" + name + ".md"      # built, not spelled: a test fixture is not a citation of a doc


SRC = '''# header
test('alpha', [PY, 'a.py'], mem='tiny')
test('beta', [PY, 'b.py'],
     mem='tiny',
     desc='the beta job')
test('gamma', [PY, 'c.py'], expect='a person wrote this')
test('delta', [PY, 'd.py'], expect='', mem='tiny')
fanout('eps', [PY, 'e.py'], ['x'], mem='tiny')
'''


class NeedsGate(unittest.TestCase):
    def test_docs_and_orchestration_cannot_change_a_verdict(self):
        self.assertFalse(G.needs_gate([_doc("x"), "doc/y.html", "README.md", "tools/swarm.py", "tools/test_swarm_why.py",
                                       "tools/gate_ledger.py", "tools/gates.json"]))

    def test_the_compiled_path_and_the_suite_do(self):
        for f in ("gimple_codegen.py", "fire_compiler.py", "mojo/backend_gimple/emit_stmts.py", "runtime/fire_runtime.c",
                  "tools/suite.py", "test_gimple.py", "formal/model.py"):
            self.assertTrue(G.needs_gate([_doc("x"), f]), f)


class Bisect(unittest.TestCase):
    def test_finds_the_first_bad_commit_in_log_n_probes(self):
        commits = ["c%d" % i for i in range(1, 17)]
        for first in range(16):
            bad = set(commits[first:])
            got, probes = G.first_bad(commits, lambda c: c in bad)
            self.assertEqual(got, commits[first])
            self.assertLessEqual(probes, 4)

    def test_a_single_candidate_needs_no_probe(self):
        self.assertEqual(G.first_bad(["only"], lambda c: 1 / 0), ("only", 0))


class Splice(unittest.TestCase):
    def reason(self, job):
        return G.get_expect(G.set_expect(SRC, job, G.MARK + " red"), job)

    def test_added_on_one_line_and_multi_line_registrations_and_fanout(self):
        for job in ("alpha", "beta", "eps"):
            out = G.set_expect(SRC, job, G.MARK + " red")
            ast.parse(out)
            self.assertEqual(G.get_expect(out, job), G.MARK + " red", job)
            for other in ("gamma",):
                self.assertEqual(G.get_expect(out, other), "a person wrote this")

    def test_only_the_named_job_changes(self):
        out = G.set_expect(SRC, "alpha", G.MARK + " red")
        self.assertEqual(out.replace(", expect=%r" % (G.MARK + " red"), ""), SRC)

    def test_an_empty_marker_is_filled_and_a_real_one_is_never_overwritten(self):
        self.assertEqual(G.get_expect(G.set_expect(SRC, "delta", "r"), "delta"), "r")
        self.assertEqual(G.set_expect(SRC, "gamma", "r"), SRC)

    def test_drop_removes_only_our_marker(self):
        ours = G.set_expect(SRC, "beta", G.MARK + " red")
        self.assertEqual(G.drop_expect(ours, "beta"), SRC)
        self.assertEqual(G.drop_expect(SRC, "gamma"), SRC)                 # a person's marker stays
        ast.parse(G.drop_expect(G.set_expect(SRC, "alpha", G.MARK + " x"), "alpha"))

    def test_disabled_names_the_gate_doc_and_round_trips(self):
        out = G.set_disabled(SRC, "beta")
        ast.parse(out)
        self.assertEqual(G.get_disabled(out, "beta"), _doc("gate-beta"))
        self.assertEqual(G.drop_disabled(out, "beta"), SRC)
        self.assertEqual(G.set_disabled(out, "beta"), out)                 # already disabled: no second marker
        self.assertEqual(G.set_disabled(SRC, "gamma"), SRC)                # a person's expect marker is left alone

    def test_a_disabled_marker_that_is_not_ours_stays(self):
        src = SRC.replace("mem='tiny')\ntest('beta'", "mem='tiny', disabled='bugs/notes.txt')\ntest('beta'")
        self.assertEqual(G.drop_disabled(src, "alpha"), src)

    def test_an_unknown_job_is_a_no_op(self):
        self.assertEqual(G.set_expect(SRC, "nope", "r"), SRC)


class Ledger(unittest.TestCase):
    def test_a_new_red_takes_the_previous_run_as_last_good(self):
        st = {}
        new, rec = G.reconcile(st, "S2", ["j"], [], {"sha": "S1", "failed": []})
        self.assertEqual(new, ["j"])
        self.assertEqual(st["jobs"]["j"]["last_good"], "S1")

    def test_a_job_red_in_the_previous_run_has_no_known_good(self):
        st = {}
        G.reconcile(st, "S2", ["j"], [], {"sha": "S1", "failed": ["j"]})
        self.assertIsNone(st["jobs"]["j"]["last_good"])

    def test_still_red_is_not_new_and_keeps_its_history(self):
        st = {"jobs": {"j": {"red": True, "last_good": "S0", "first_bad": "S1"}}}
        new, _ = G.reconcile(st, "S3", ["j"], [], {"sha": "S2", "failed": ["j"]})
        self.assertEqual(new, [])
        self.assertEqual(st["jobs"]["j"]["first_bad"], "S1")
        self.assertEqual(st["jobs"]["j"]["last_good"], "S0")

    def test_a_pass_recovers_a_red_job(self):
        st = {"jobs": {"j": {"red": True, "last_good": "S0"}}}
        _, rec = G.reconcile(st, "S3", [], ["j"], {})
        self.assertEqual(rec, ["j"])
        self.assertFalse(st["jobs"]["j"]["red"])


class GitHistory(unittest.TestCase):
    def setUp(self):
        import subprocess, tempfile
        self.d = tempfile.mkdtemp(prefix="gl_")
        self.g = lambda *a: subprocess.run(["git", *a], cwd=self.d, capture_output=True, text=True, check=True).stdout.strip()
        self.g("init", "-q", "-b", "master")
        self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")

    def commit(self, name, text="x"):
        os.makedirs(os.path.dirname(os.path.join(self.d, name)) or self.d, exist_ok=True)
        open(os.path.join(self.d, name), "w").write(text + name)
        self.g("add", "-A"); self.g("commit", "-q", "-m", "add " + name)
        return self.g("rev-parse", "HEAD")

    def test_pending_lists_only_commits_a_gate_can_see(self):
        base = self.commit("gimple_codegen.py")
        self.commit(_doc("a")); code = self.commit("runtime/r.c"); self.commit("tools/swarm.py")
        self.assertEqual([s for s, _ in G.pending(base, "master", cwd=self.d)], [code])

    def test_docs_only_since_the_last_run_means_not_due(self):
        base = self.commit("gimple_codegen.py")
        self.commit(_doc("a")); self.commit("doc/b.html")
        self.assertEqual(G.pending(base, "master", cwd=self.d), [])

    def test_no_earlier_run_is_one_pending_entry(self):
        self.commit("a.py")
        self.assertEqual(len(G.pending(None, "master", cwd=self.d)), 1)

    def test_commits_between_excludes_good_and_includes_bad(self):
        good = self.commit("a.py"); c2 = self.commit("b.py"); c3 = self.commit("c.py")
        self.assertEqual(G.commits_between(good, c3, cwd=self.d), [c2, c3])


if __name__ == "__main__":
    unittest.main()
