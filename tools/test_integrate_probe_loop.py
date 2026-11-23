#!/usr/bin/env python3
"""Regression pins for the integrator loop that ran all night (2026-11-20).

    python3 tools/test_integrate_probe_loop.py

Each test pins one fault that let a stuck probe repeat forever:
  - a probe that dies with an exception printed no verdict, so it was classified EMPTY and retried unchanged;
  - a branch's LAND doc that failed to commit ended the WHOLE pass, so the same branches came back every pass;
  - a branch retired from the registry raised KeyError in the cap path;
  - a doc whose content was already on master made `git commit` fail instead of being a no-op;
  - two EMPTY probes of the same batch were followed by a third (now: a model triage, then park).
Temporary state only: swarm.state_path is pointed at a temp file, so the live swarm.json is never written."""
import contextlib
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autointegrate as A
import control as C
import integrate as I
import probe_triage as PT
import swarm as S
import verify_landed as V


class ProbeVerdicts(unittest.TestCase):
    def test_no_output_is_empty(self):
        self.assertEqual(S.classify_probe("some git status\n")[0], "EMPTY")

    def test_exception_line_is_error_not_empty(self):
        # integrate.py's __main__ prints this when main() raises: it must not look like "nothing to merge"
        self.assertEqual(S.classify_probe("PROBE ERROR: KeyError: 'x'\n")[0], "ERROR")

    def test_green_and_red_carry_their_branches(self):
        self.assertEqual(S.classify_probe("PROBE GREEN: a b\n")[:2], ("GREEN", ["a", "b"]))
        v, merged, failing = S.classify_probe("PROBE RED: a\nFAILED_JOBS: stdlib-syntax\n")
        self.assertEqual((v, merged, failing), ("RED", ["a"], ["stdlib-syntax"]))

    def test_lock_busy(self):
        self.assertEqual(S.classify_probe("another integrator is already running\n")[0], "BUSY")


class TriageDecision(unittest.TestCase):
    BATCH = ["bug-a", "bug-b"]

    def test_valid_land_doc(self):
        d = PT.parse_decision('{"action": "land_doc", "branch": "bug-a", "reason": "conflicts"}', self.BATCH)
        self.assertEqual((d["action"], d["branch"]), ("land_doc", "bug-a"))

    def test_park_and_retry_carry_no_branch(self):
        self.assertEqual(PT.parse_decision('{"action": "park", "branch": "bug-a"}', self.BATCH)["branch"], None)
        self.assertEqual(PT.parse_decision('{"action": "retry", "branch": null}', self.BATCH)["action"], "retry")

    def test_action_outside_the_closed_set_is_rejected(self):
        # the reviewer may not land, merge, push or edit gates: those words are not actions
        for bad in ("land", "merge", "gate_off", "expect"):
            with self.assertRaises(ValueError):
                PT.parse_decision('{"action": "%s", "branch": "bug-a"}' % bad, self.BATCH)

    def test_land_doc_must_name_a_batch_member(self):
        with self.assertRaises(ValueError):
            PT.parse_decision('{"action": "land_doc", "branch": "bug-zzz"}', self.BATCH)

    def test_no_json_is_rejected(self):
        with self.assertRaises(ValueError):
            PT.parse_decision("I think you should land bug-a.", self.BATCH)

    def test_ask_raises_on_failed_call(self):
        fake = mock.Mock(returncode=1, stdout="", stderr="rate limited")
        with self.assertRaises(RuntimeError):
            PT.ask(self.BATCH, "tail", "EMPTY", run=lambda *a, **k: fake)


@contextlib.contextmanager
def temp_state():
    """A swarm state file in a temp directory: strike_probe/park write here, never to the live swarm.json."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "swarm.json")
    with mock.patch.object(S, "state_path", return_value=path):
        yield path


class StrikesAndEscalation(unittest.TestCase):
    BATCH = ["bug-a", "bug-b"]
    TASKS = {"bug-a": {"branch": "work/bug-a"}, "bug-b": {"branch": "work/bug-b"}}

    def test_strikes_count_per_key_and_clear_on_verdict(self):
        with temp_state():
            st = {}
            self.assertEqual(S.strike_probe(st, "k"), 1)
            self.assertEqual(S.strike_probe(st, "k"), 2)
            S.clear_probe_strikes(st, "k")
            self.assertNotIn("k", st["probe_strikes"])

    def test_second_strike_escalates_and_park_stops_reprobing(self):
        # The loop this fixes: the same batch re-probed every pass. After the second no-verdict probe the reviewer is
        # asked once; a park makes the batch parked, and land() checks probe_parked before probing again.
        with temp_state() as path, \
                mock.patch.object(PT, "ask", return_value={"action": "park", "branch": None, "reason": "unclear"}) as ask:
            st = {}
            S.strike_probe(st, "k")
            S.strike_probe(st, "k")
            S.resolve_stuck_batch(st, "k", list(self.BATCH), self.TASKS, "tail", "EMPTY")
            self.assertEqual(ask.call_count, 1)
            self.assertTrue(S.probe_parked(st, "k"))
            self.assertTrue(os.path.exists(path))            # the decision is persisted, not held in memory only

    def test_land_doc_decision_caps_and_files_only_that_branch(self):
        with temp_state(), \
                mock.patch.object(PT, "ask", return_value={"action": "land_doc", "branch": "bug-a", "reason": "conflicts"}), \
                mock.patch.object(I, "_cap_merge_fix") as cap, mock.patch.object(I, "land_doc") as filed:
            st = {"probe_strikes": {"k": {"n": 2, "parked": False, "retried": False}}}
            batch = list(self.BATCH)
            S.resolve_stuck_batch(st, "k", batch, self.TASKS, "tail", "EMPTY")
            self.assertEqual(batch, ["bug-b"])
            self.assertEqual(cap.call_count, 1)
            self.assertEqual(filed.call_args[0][0], "bug-a")

    def test_unusable_decision_parks_instead_of_acting(self):
        with temp_state(), mock.patch.object(PT, "ask", side_effect=ValueError("garbage")):
            st = {"probe_strikes": {"k": {"n": 2, "parked": False, "retried": False}}}
            S.resolve_stuck_batch(st, "k", list(self.BATCH), self.TASKS, "tail", "EMPTY")
            self.assertTrue(st["probe_strikes"]["k"]["parked"])

    def test_retry_is_allowed_once_then_parks(self):
        with temp_state(), mock.patch.object(PT, "ask", return_value={"action": "retry", "branch": None, "reason": "lock"}):
            st = {"probe_strikes": {"k": {"n": 2, "parked": False, "retried": False}}}
            S.resolve_stuck_batch(st, "k", list(self.BATCH), self.TASKS, "tail", "EMPTY")
            self.assertFalse(st["probe_strikes"]["k"]["parked"])
            self.assertTrue(st["probe_strikes"]["k"]["retried"])
            st["probe_strikes"]["k"]["n"] = 2
            S.resolve_stuck_batch(st, "k", list(self.BATCH), self.TASKS, "tail", "EMPTY")
            self.assertTrue(st["probe_strikes"]["k"]["parked"])


class IntegratorDocFaults(unittest.TestCase):
    def test_cap_of_a_retired_branch_is_a_no_op_not_a_keyerror(self):
        class Reg(dict):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch.object(I.C, "registry", return_value=Reg()):
            I._cap_merge_fix("bug-gone", "land doc: bug-gone: conflicts")     # must not raise KeyError

    def test_commit_of_already_recorded_doc_is_not_an_error(self):
        # `git commit` says "nothing to commit" when the doc's content is already on master: that is success
        nothing = mock.Mock(returncode=1, stdout="On branch master\nnothing to commit\n", stderr="")

        def git(*a, **k):
            if a[:2] == ("rev-parse", "--show-toplevel"):
                return os.path.realpath(I.C.MAIN)
            if a[:2] == ("diff", "--cached"):
                return "bugs/LAND-x.md"
            return ""
        with mock.patch.object(I.C, "git", side_effect=git), \
                mock.patch.object(I.subprocess, "run", return_value=nothing):
            I.commit_doc(os.path.join(I.C.MAIN, "bugs", "LAND-x.md"), "land: x")   # returns; does not raise


class ProbeAlwaysReports(unittest.TestCase):
    def run_probe(self, entry):
        with mock.patch.object(sys, "argv", ["integrate.py", "--probe"]), \
                mock.patch("builtins.print") as p:
            with self.assertRaises(SystemExit) as ctx:
                I.run_guarded(entry)
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        return ctx.exception.code, printed

    def test_exception_prints_one_error_verdict(self):
        code, printed = self.run_probe(lambda: (_ for _ in ()).throw(KeyError("x")))
        self.assertEqual(code, 2)
        self.assertIn("PROBE ERROR: KeyError", printed)

    def test_message_exit_prints_error_verdict(self):
        code, printed = self.run_probe(lambda: sys.exit("refusing: nothing to merge"))
        self.assertEqual(code, 2)
        self.assertIn("PROBE ERROR: refusing", printed)

    def test_int_exit_is_left_to_its_own_verdict(self):
        # PROBE RED / PROBE REFUSED print their own line and exit 1: the guard must not add a second verdict
        code, printed = self.run_probe(lambda: sys.exit(1))
        self.assertEqual(code, 1)
        self.assertNotIn("PROBE ERROR", printed)


class SuiteVerdicts(unittest.TestCase):
    """The runner's own per-job verdict line is the evidence; a process exit code is not.

    `[ i/n] ok <job>` / `skip` / `FAIL` is what suite.py records about each job (`_TAG`), and the PER-TEST row
    `ok <registration> N job(s)` is the worst item's status for a fanout. Reading `rc == 0` as "right track" scored a
    selection that SKIPped behind a disabled dep as green, and reading `rc != 0` as "red" made a fanout ITEM name
    (rejected at every commit) red at every commit: one red producer's cascade produced fifty phantom bisections.
    """

    def tree(self, text):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "build"))
        p = os.path.join(d, "build", "suite.log")
        open(p, "w").write(text)
        return d, p

    LOG = ("[  1/4] ok       gimple                                     1.0s\n"
           "[  2/4] ok       bootstrap-stage2-dumps:a.mojo              0.0s\n"
           "[  3/4] skip     bootstrap-stage2-dumps:class_jit.mojo     0.0s\n"
           "[  4/4] FAIL     runner                                     0.5s\n"
           "testing:\n"
           "  ok       gimple                           1 job(s)\n"
           "      ok       gimple                           1.0s\n"
           "  skip     bootstrap-stage2-dumps           45 job(s)\n"
           "      ok       bootstrap-stage2-dumps:a.mojo             0.0s\n"
           "      skip     bootstrap-stage2-dumps:class_jit.mojo     0.0s\n"
           "  FAIL     runner                           1 job(s)\n"
           "      FAIL     runner                           0.5s\n")

    def test_pass_skip_and_fail_are_three_different_answers(self):
        _d, p = self.tree(self.LOG)
        self.assertEqual(I.job_verdict(p, "gimple"), "green")
        self.assertEqual(I.job_verdict(p, "bootstrap-stage2-dumps:class_jit.mojo"), "no-evidence")
        self.assertEqual(I.job_verdict(p, "runner"), "red")

    def test_a_registration_is_answered_by_its_own_row_not_one_of_its_items(self):
        _d, p = self.tree(self.LOG)
        self.assertEqual(I.job_verdict(p, "bootstrap-stage2-dumps"), "no-evidence")
        self.assertEqual(I.job_verdict(p, "bootstrap-stage2-dumps:a.mojo"), "green")

    def test_a_name_the_runner_never_saw_has_no_evidence(self):
        _d, p = self.tree(self.LOG)
        self.assertEqual(I.job_verdict(p, "bootstrap-stage2-dumps:not_selected.mojo"), "no-evidence")

    def test_a_log_older_than_the_run_is_not_evidence(self):
        # A run that died before the runner started leaves the PREVIOUS run's log in place; `since` refuses it.
        _d, p = self.tree(self.LOG)
        old = time.time() - 60
        os.utime(p, (old, old))
        self.assertEqual(I.job_verdict(p, "gimple", since=time.time()), "no-evidence")

    def test_passed_jobs_reads_the_runners_ok_tag_and_only_registrations(self):
        d, _p = self.tree(self.LOG)
        self.assertEqual(V.passed_jobs(d), ["gimple"])


class ProbeNeedsEvidence(unittest.TestCase):
    """`autointegrate.probe` answers green / red / no-evidence from the run's own verdict lines, never its exit code."""

    def probe(self, body, rc=0, jobs=("gimple",)):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "build"))

        def run(*a, **k):
            if body is not None:
                open(os.path.join(d, "build", "suite.log"), "w").write(body)
            return rc, "--jobs run finished"

        with mock.patch.object(A, "run_integrate", side_effect=run), \
                mock.patch.object(A.I, "INTEG", d):
            return A.probe(["bug-a"], list(jobs))

    def test_a_pass_is_the_right_track(self):
        self.assertEqual(self.probe("[  1/1] ok       gimple                           0.0s\n"), "green")

    def test_a_skip_behind_a_disabled_dep_is_no_evidence_even_though_it_exits_0(self):
        # THE regression: the selection SKIPs and exits 0, which used to be scored "right track" for a job that never ran.
        self.assertEqual(self.probe("[  1/1] skip     gimple   0.0s\n", rc=0), "no-evidence")

    def test_one_missing_verdict_refuses_the_whole_probe(self):
        # j2 never reached the runner's verdict lines: no evidence for the selection, even though j1 passed.
        self.assertEqual(self.probe("[  1/2] ok       j1     0.0s\n", jobs=("j1", "j2")), "no-evidence")

    def test_a_failing_verdict_is_the_wrong_track(self):
        self.assertEqual(self.probe("[  1/1] FAIL     gimple   0.1s\n", rc=1), "red")

    def test_a_pass_verdict_in_a_run_that_did_not_finish_cleanly_is_not_evidence(self):
        # A non-zero run with every requested job `ok` is a run that reported something else wrong (the tally, a
        # resource cap after the jobs): it is not evidence that the jobs pass the way a landing gate needs.
        self.assertEqual(self.probe("[  1/1] ok       gimple   0.0s\n", rc=1), "no-evidence")

    def test_a_run_that_never_reached_the_suite_is_not_evidence(self):
        # integrate.py can refuse before the runner starts; the previous run's ok line must not answer for this one.
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "build"))
        p = os.path.join(d, "build", "suite.log")
        open(p, "w").write("[  1/1] ok       gimple                           0.0s\n")
        old = time.time() - 60
        os.utime(p, (old, old))
        with mock.patch.object(A, "run_integrate", return_value=(0, "PROBE REFUSED: nothing to check")), \
                mock.patch.object(A.I, "INTEG", d):
            self.assertEqual(A.probe(["bug-a"], ["gimple"]), "no-evidence")

    def test_a_bisect_with_no_evidence_names_no_branch(self):
        with mock.patch.object(A, "probe", return_value="no-evidence"):
            self.assertIsNone(A.bisect_first_bad(["a", "b", "c", "d"], ["gimple"]))

    def test_a_bisect_still_finds_the_branch_when_every_probe_answers(self):
        with mock.patch.object(A, "probe", side_effect=["green", "red"]):
            self.assertEqual(A.bisect_first_bad(["a", "b", "c", "d"], ["gimple"]), 2)


class BisectStopsWithoutEvidence(unittest.TestCase):
    """verify_landed's bisect asks the suite for each commit's verdict; a commit where the job did not run has no
    answer, so the bisect stops with a note instead of picking the first commit in the range as "first bad"."""

    def test_no_evidence_names_no_first_bad(self):
        e = {"last_good": "S1"}
        with mock.patch.object(V, "job_is_red_at", return_value="no-evidence"), \
                mock.patch.object(V.G, "commits_between", return_value=["c1", "c2"]):
            V.bisect_job("bootstrap-stage2-dumps:class_jit.mojo", e, "S2")
        self.assertIsNone(e["first_bad"])
        self.assertIn("job did not run at c1; cannot bisect", e["bisect_note"])

    def test_a_red_probe_still_bisects(self):
        e = {"last_good": "S1"}
        with mock.patch.object(V, "job_is_red_at", side_effect=lambda j, c: "red" if c >= "c2" else "green"), \
                mock.patch.object(V.G, "commits_between", return_value=["c1", "c2", "c3"]):
            V.bisect_job("j", e, "S3")
        self.assertEqual(e["first_bad"], "c2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
