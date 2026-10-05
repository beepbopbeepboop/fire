#!/usr/bin/env python3
"""The proof-regression RATCHET is an instrument, so the instrument is pinned.

    python3 test_formal_proof_census.py [-v]

`tools/formal_proof_census.py` is the thing that makes the Lean side of the
formal path regress LOUDLY: it runs every `formal/examples/*.mojo` through
`formal.build.compile_formal(prove=True, check=True)` — through
`formal/lean.py::run_lean`'s bounds, with no launcher and no bound of its own —
and compares the result against a committed JSON baseline, failing when an
example's status gets worse, when a hole or an admitted contract appears, or
when a proof costs more than twice what it cost.

Its verdicts are quoted in `bugs/FORMAL_proof_coverage_census_2026-10-03.md` and
will be re-quoted, and the baseline is a COMMITTED FILE, so six things have to
hold or the numbers mean nothing:

  * **the corpus is the whole directory, and it is sorted.** The unit that
    regresses is an example; a sample of examples makes the ratchet blind to the
    one that moved, and an unsorted baseline is a diff nobody can read.
  * **the rank order is the argument.** `proved` → `sorry` is a regression and
    `sorry` → `proved` is a result to bank, while `too-large` → `bound-exceeded`
    is NEITHER: both are the absence of a measurement, so a program moving
    between them has not regressed, while a program moving into either from
    `proved` has.
  * **an unmeasured time is never compared and never zero.** `formal/lean.py`'s
    verdict cache replays a verdict in about a tenth of a second, so an
    unchanged corpus measures no time at all; a row written from a replay
    carries `null`, and `null` must not read as "0 seconds" anywhere.
  * **a changed example is not compared against its old row.** `source_sha256`
    is in the record for that, and a ratchet that compared two different
    programs' times would be reporting a fact about neither.
  * **the committed baseline is honest.** Every example has a row, every row's
    status is one the tool has, every recorded time is a real measurement or
    `null` rather than zero, and at least one row carries a time — because a
    baseline with no timings in it has a time ratchet that cannot fire, and it
    would sit there looking perfectly valid.
  * **the classifier says what it means.** A captured `LeanRun` with `exceeded`
    set is a bound breach and not a verdict, Lean's own memory sentence is a
    third thing, and anything else is a verdict on the proof. All three are
    checked without Lean, so this file costs a codegen run and no proof.

None of this runs Lean. The census's own Lean numbers are its job and its
baseline's business; this file is what keeps that job honest.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_proof_census as C          # noqa: E402


def row(stem="s", status="proved", **kw):
    """A `Record` for a comparison test, with everything else at its best."""
    got = dict(
        stem=stem, arch="arm64", status=status, reason="", phase="check",
        n_sorries=0, n_admitted=0, decide_sites={"native_decide": 3,
                                                 "bv_decide": 0},
        decide_total=3, proof_lines=120, source_sha256="deadbeef",
        lean_wall_s=10.0, lean_cpu_s=12.0, lean_peak_gb=1.5,
        timed_on="2026-10-05", cached=False,
        wall_s=11.0, peak_gb=1.6)
    got.update(kw)
    return C.Record(**got)


class TestCorpus(unittest.TestCase):
    """The whole directory, in one order, every time."""

    def test_it_is_every_example_in_sorted_order(self):
        stems = C.corpus()
        self.assertEqual(stems, sorted(stems), "corpus order must be sorted")
        on_disk = sorted(f[:-5] for f in os.listdir(C.EXAMPLES)
                         if f.endswith(".mojo"))
        self.assertEqual(stems, on_disk,
                         "the census must cover every formal/examples/*.mojo; "
                         "a sampled corpus is blind to the example that moved")
        self.assertGreater(len(stems), 20,
                           "the corpus shrank — is this the right directory?")

    def test_two_calls_agree(self):
        self.assertEqual(C.corpus(), C.corpus())

    def test_only_narrows_it_and_names_what_it_could_not_find(self):
        two = C.corpus(["ret42", "neg"])
        self.assertEqual(two, sorted(two))
        self.assertLessEqual(len(two), 2)
        with self.assertRaises(SystemExit):
            C.corpus(["no-such-example"])

    def test_the_baseline_path_is_per_architecture(self):
        arm = C.baseline_path("arm64")
        x86 = C.baseline_path("x86_64")
        self.assertNotEqual(arm, x86,
                            "the two backends' proof generators are separate "
                            "implementations; one baseline would compare an "
                            "x86-64 row against an arm64 one")


class TestRank(unittest.TestCase):
    """The order the whole comparison rests on."""

    def test_proved_is_the_best_and_a_crash_is_the_worst_verdict(self):
        order = ["proved", "admitted", "sorry", "lean-rejected", "refused",
                 "crash", "too-large", "bound-exceeded"]
        ranks = [C.STATUS_RANK[s] for s in order]
        self.assertEqual(ranks, sorted(ranks),
                         f"the rank order is not the documented one: "
                         f"{list(zip(order, ranks))}")

    def test_the_two_no_verdict_classes_share_a_rank(self):
        """The rule that stops a false red in both directions.

        `too-large` and `bound-exceeded` are both the ABSENCE of a measurement
        (`formal/lean.py`: a breach "is NOT a verdict on the proof"), so moving
        between them is not a regression — while moving into either from
        `proved` is, because a proof that used to check no longer does. Same
        rank is what expresses both halves of that in one comparison.
        """
        self.assertEqual(C.STATUS_RANK["too-large"],
                         C.STATUS_RANK["bound-exceeded"])
        self.assertEqual(C.NOT_A_VERDICT, {"too-large", "bound-exceeded"})

    def test_a_worse_status_is_a_regression(self):
        for was, now in (("proved", "sorry"), ("proved", "admitted"),
                         ("sorry", "lean-rejected"), ("admitted", "refused"),
                         ("proved", "too-large"), ("refused", "crash")):
            findings = C.compare({"s": row(status=was)}, [row(status=now)])
            self.assertIn(
                "REGRESSION",
                [f.severity for f in findings],
                f"{was} -> {now} must be reported as a regression")

    def test_a_better_status_is_an_improvement_to_bank(self):
        findings = C.compare({"s": row(status="sorry", n_sorries=3)},
                             [row(status="proved", n_sorries=0)])
        self.assertEqual([f.severity for f in findings].count("IMPROVEMENT"), 2,
                         "the status and the hole count are two ratchets, and "
                         "both moved the right way")
        self.assertIn("--write-baseline", " ".join(f.text for f in findings),
                      "an improvement must say how to bank it")


class TestCompare(unittest.TestCase):
    """The four things the comparison does, and the four it refuses to do."""

    def setUp(self):
        self.before = {"s": row()}

    def test_the_same_row_is_silent(self):
        self.assertEqual(
            [f for f in C.compare(self.before, [row()])
             if f.severity != "INFO"], [],
            "an unchanged example must produce no finding a reader has to act on")

    def test_holes_may_only_go_down(self):
        up = C.compare({"s": row(status="sorry", n_sorries=2)},
                       [row(status="sorry", n_sorries=4)])
        self.assertIn("REGRESSION", [f.severity for f in up])
        down = C.compare({"s": row(status="sorry", n_sorries=4)},
                         [row(status="sorry", n_sorries=2)])
        self.assertIn("IMPROVEMENT", [f.severity for f in down])
        self.assertNotIn("REGRESSION", [f.severity for f in down])

    def test_a_proof_over_twice_as_expensive_is_a_regression(self):
        slow = C.compare(self.before, [row(lean_cpu_s=24.1, lean_wall_s=20.1)])
        self.assertIn("REGRESSION", [f.severity for f in slow])
        self.assertIn("2.0x", " ".join(f.text for f in slow),
                      "a regression must say how far over the line it is")
        just_under = C.compare(self.before, [row(lean_cpu_s=23.9,
                                                 lean_wall_s=19.9)])
        self.assertNotIn("REGRESSION", [f.severity for f in just_under])

    def test_an_unmeasured_time_is_neither_zero_nor_a_regression(self):
        """The rule that makes the tool usable on a warm verdict cache.

        `formal/lean.py` replays a cached verdict in about a tenth of a second,
        so a repeat run measures NO time for an unchanged corpus. Comparing that
        against a baseline that has one would fail every example on every run,
        and reading it as 0 would fail them the other way.
        """
        cases = {
            "this run measured, the baseline did not": (12.0, None),
            "the baseline measured, this run did not": (None, 12.0),
        }
        for what, (now_cpu, baseline_cpu) in cases.items():
            findings = C.compare(
                {"s": row(lean_cpu_s=baseline_cpu)}, [row(lean_cpu_s=now_cpu)])
            self.assertNotIn("REGRESSION", [f.severity for f in findings], what)
            self.assertIn("INFO", [f.severity for f in findings],
                          f"{what} must be SAYED, not silently skipped")
        # …and neither measured is SILENT, because that is the steady state of
        # a warm run and 52 rows of "still no timing here" would bury the one
        # row that has something to say.
        self.assertEqual(C.compare({"s": row(lean_cpu_s=None)},
                                   [row(lean_cpu_s=None)]), [])

    def test_the_untimed_rows_are_one_finding_and_not_one_each(self):
        """16 identical sentences are not 16 facts a reader can act on.

        The action is one thing — re-measure, or bank a timing for the rows that
        have none — so `compare` names the stems once under `RUN_SCOPE`.
        """
        baseline = {s: row(s, lean_cpu_s=20.0) for s in "abcdef"}
        rows = [row(s, lean_cpu_s=None) for s in "abcdef"]
        findings = C.compare(baseline, rows)
        self.assertEqual(len(findings), 1, [f.text for f in findings])
        self.assertEqual(findings[0].severity, "INFO")
        self.assertEqual(findings[0].stem, C.RUN_SCOPE)
        self.assertIn("6 row(s)", findings[0].text)
        self.assertIn("a, b, c, d, e, f", findings[0].text)
        self.assertNotIn("REGRESSION", [f.severity for f in findings])

    def test_a_row_that_is_timed_on_both_sides_and_within_tolerance_is_silent(self):
        findings = C.compare({"s": row(lean_cpu_s=10.0)},
                             [row(lean_cpu_s=15.0)])
        self.assertEqual(findings, [], [f.text for f in findings])

    def test_a_changed_example_is_not_compared(self):
        findings = C.compare({"s": row(source_sha256="old")},
                             [row(source_sha256="new")])
        self.assertNotIn("REGRESSION", [f.severity for f in findings])
        self.assertEqual([f.severity for f in findings], ["INFO"])
        self.assertIn("changed", findings[0].text)

    def test_a_new_or_deleted_example_is_information_not_failure(self):
        new = C.compare({}, [row(stem="fresh")])
        self.assertEqual([f.severity for f in new], ["INFO"])
        gone = C.compare({"gone": row(stem="gone")}, [row(stem="other")])
        self.assertNotIn("REGRESSION", [f.severity for f in gone])
        said = " ".join(f.text for f in gone)
        self.assertIn("not in the baseline", said, "the new one")
        self.assertIn("deleted", said, "the deleted one")

    def test_a_refusal_moving_inside_one_rank_is_information(self):
        findings = C.compare(
            {"s": row(status="refused", reason="no value for x.y",
                      phase="generate")},
            [row(status="refused", reason="an f-string has no buffer",
                 phase="build")])
        self.assertNotIn("REGRESSION", [f.severity for f in findings],
                         "a value-model project moves refusals along the "
                         "pipeline on purpose; a gate that fired on that "
                         "would be fired at every step of it")
        self.assertIn("different reason",
                      " ".join(f.text for f in findings))

    def test_one_of_the_two_no_verdict_classes_moving_to_the_other_is_not_a_regression(self):
        findings = C.compare({"s": row(status="too-large")},
                             [row(status="bound-exceeded")])
        self.assertNotIn("REGRESSION", [f.severity for f in findings])


class TestClassify(unittest.TestCase):
    """Which of the three check outcomes this is, without running Lean."""

    class FakeRun:
        """A `LeanRun` shaped like the one `formal/lean.py` returns."""

        def __init__(self, rc=0, out="", err="", exceeded=None):
            self.returncode, self.stdout, self.stderr = rc, out, err
            self.exceeded = exceeded
            self.wall_s, self.cpu_s, self.peak_rss = 1.0, 2.0, 1 << 30

    def test_a_breach_is_its_own_verdict(self):
        run = self.FakeRun(rc=-9, exceeded="lean exceeded 1500s wall")
        status, reason = C._classify_failure([run], "proof check failed: …")
        self.assertEqual(status, "bound-exceeded")
        self.assertIn("1500s", reason)

    def test_leans_own_memory_ceiling_is_a_third_thing(self):
        run = self.FakeRun(
            rc=1,
            err="either_proof.lean:2600:8: error: (kernel) excessive memory "
                "consumption detected")
        status, reason = C._classify_failure([run], "proof check failed")
        self.assertEqual(status, "too-large")
        self.assertIn("excessive memory", reason)

    def test_anything_else_is_a_verdict_on_the_proof(self):
        run = self.FakeRun(rc=1, err="sum_proof.lean:2880:16: error: unsolved "
                                       "goals")
        status, _reason = C._classify_failure([run], "proof check failed")
        self.assertEqual(status, "lean-rejected")

    def test_a_replayed_verdict_classifies_from_the_stored_detail(self):
        """The warm-cache case, which is what most rows actually are.

        `formal/lean.py` publishes FAILED verdicts too, so on a repeat run it
        raises without ever launching Lean and the detail carries the words
        Lean said on the run that first produced them. Classifying only from a
        captured run put 13 of this tool's first 52 rows in `refused` — every
        one of them a Lean verdict.
        """
        self.assertEqual(
            C._classify_failure([], "proof check failed: IEEE754\nProofLib\n"
                                    "either_proof.lean:2600:8: error: "
                                    "(kernel) excessive memory consumption "
                                    "detected")[0],
            "too-large")
        self.assertEqual(
            C._classify_failure([], "proof check failed: sum_proof.lean:1:1: "
                                    "error: unsolved goals")[0],
            "lean-rejected")

    def test_a_measured_run_and_a_replayed_one_agree_on_the_reason(self):
        """The reason is ONE LINE, and the same line either way.

        A replayed verdict's stored detail carries Lean's header first
        (`IEEE754 / ProofLib / Refine / X86 / work`) before the diagnostics and
        a measured one does not, so comparing whole blobs reported "same
        status, different reason" on three corpus rows on every single run.
        """
        diagnostic = ("sum_proof.lean:2880:16: error: Tactic `rfl` failed: the "
                     "left and right sides differ\n  mem_read_u64 (mem_write_u64 …")
        replayed = ("proof check failed: IEEE754\nProofLib\nRefine\nX86\n"
                    "work\n" + diagnostic)
        measured = "proof check failed: " + diagnostic
        self.assertEqual(C._classify_failure([], replayed)[1],
                         C._classify_failure([self.FakeRun(err=measured)],
                                             measured)[1])
        self.assertEqual(C.first_diagnostic(measured),
                         "sum_proof.lean:2880:16: error: Tactic `rfl` failed: "
                         "the left and right sides differ",
                         "one line: Lean's continuation lines are the repeated "
                         "goal state, and folding them in is what made the "
                         "committed baseline 40 KB of duplicated `mem_read_u64`")

    def test_a_proof_run_is_told_apart_from_every_other_launcher_call(self):
        for args, want in (
                (["sum_proof.lean"], True),
                (["/abs/path/sum_proof.lean"], True),
                (["-o", "/tmp/ProofLib.olean", "/repo/lib/ProofLib.lean"],
                 False),
                (["--version"], False),
                ([], False)):
            self.assertEqual(C._is_proof_run(args), want, f"{args}")
        import formal.lean as L
        self.assertEqual(L.lean_flags(), ["-j", str(L.LEAN_THREADS),
                                          "-M", str(L.LEAN_MEMORY_MB),
                                          "-T", str(L.LEAN_HEARTBEATS)])


class TestDecideSites(unittest.TestCase):
    """The trust-boundary column, and what it must not count."""

    def test_it_counts_both_tactics_and_ignores_prose(self):
        text = "\n".join([
            "theorem t1 : True := by native_decide",
            "-- a comment mentioning bv_decide and native_decide",
            "theorem t2 : True := by bv_decide",
            'theorem t3 : True := by exact "native_decide"',   # a string
            "theorem t4 : True := by decide",                 # kernel-checked
        ])
        self.assertEqual(C.decide_sites(text),
                         {"native_decide": 1, "bv_decide": 1})

    def test_the_tactic_list_is_read_from_the_model_not_restated(self):
        from formal import admitted
        self.assertEqual(sorted(C.decide_sites("")),
                         sorted(admitted.AXIOM_TACTICS),
                         "a second hand-kept copy of the tactic list goes "
                         "stale silently; this one is read from the model's")

    def test_an_ordinary_mention_in_a_name_is_not_a_site(self):
        self.assertEqual(C.decide_sites("theorem my_native_decide_step : "
                                        "True := by trivial"),
                         {"native_decide": 0, "bv_decide": 0})


class TestBaselineFile(unittest.TestCase):
    """A committed file is a thing this tool has to survive."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="proof-census-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, name="b.json"):
        return os.path.join(self.dir, name)

    def test_it_round_trips(self):
        path = self.path()
        rows = [row("a"), row("b", status="sorry", n_sorries=2)]
        C.write_baseline(path, rows, "arm64", "Lean (version 4.32.2)")
        back = C.load_baseline(path)
        self.assertEqual(sorted(back), ["a", "b"])
        self.assertEqual(back["b"].n_sorries, 2)
        self.assertEqual(back["b"].decide_sites, rows[1].decide_sites)

    def test_a_write_merges_over_what_it_was_given(self):
        """`--only x --write-baseline` must not throw the other rows away.

        Re-seeding one row's timing is the documented way to put a measured
        time into a baseline written on a warm tree, and a replacing write
        would answer that by leaving the committed file a census of one
        example. The corpus argument is the WHOLE corpus, which is what the
        first version got wrong: it filtered by the measured stems, so the
        `--only <17 stems> --remeasure --write-baseline` that banked this
        baseline's timings deleted the other 35 rows out of it.
        """
        path = self.path()
        corpus_stems = ["a", "b", "c"]
        C.write_baseline(path, [row(s) for s in corpus_stems], "arm64", "v",
                         corpus_stems)
        C.write_baseline(path, [row("b", lean_cpu_s=99.0)], "arm64", "v",
                         corpus_stems, keep=C.load_baseline(path))
        back = C.load_baseline(path)
        self.assertEqual(sorted(back), ["a", "b", "c"])
        self.assertEqual(back["b"].lean_cpu_s, 99.0)

    def test_a_deleted_examples_row_is_dropped_and_only_its_own(self):
        """The one row a merge may lose, and it is decided in one place.

        `corpus_stems` is what says which examples still exist, so a row for a
        stem that is gone cannot survive a write — and a row for a stem that
        exists but was not measured this run must.
        """
        path = self.path()
        C.write_baseline(path, [row("a"), row("gone")], "arm64", "v",
                         ["a", "gone"])
        C.write_baseline(path, [], "arm64", "v", ["a"],
                         keep=C.load_baseline(path))
        self.assertEqual(sorted(C.load_baseline(path)), ["a"])

    def test_a_replayed_write_keeps_the_timing_the_row_already_had(self):
        """A ratchet must not decay through ordinary use of its own writer.

        `formal/lean.py` replays a cached verdict in about a tenth of a second,
        so the common `--write-baseline` — banking an improvement the census
        just reported — measures no time at all. Overwriting the row with that
        would reset every row the operator touched to "no timing known", and a
        few honest improvements later the whole time ratchet is inert while the
        baseline still looks complete. **An unmeasured value is not a change.**
        """
        path = self.path()
        timed = row("a", lean_cpu_s=30.0, lean_wall_s=25.0, lean_peak_gb=2.0,
                    timed_on="2026-10-05")
        C.write_baseline(path, [timed], "arm64", "v", ["a"])
        replayed = row("a", lean_cpu_s=None, lean_wall_s=None,
                       lean_peak_gb=None, timed_on=None, cached=True)
        C.write_baseline(path, [replayed], "arm64", "v", ["a"],
                         keep=C.load_baseline(path))
        got = C.load_baseline(path)["a"]
        self.assertEqual(got.lean_cpu_s, 30.0)
        self.assertEqual(got.lean_wall_s, 25.0)
        self.assertEqual(got.lean_peak_gb, 2.0)
        self.assertEqual(got.timed_on, "2026-10-05",
                         "a preserved timing must keep the DATE it was taken, "
                         "or it reads as this write's measurement")
        self.assertTrue(got.cached,
                        "the verdict really was replayed, and the row says so")

    def test_a_measured_write_replaces_the_timing_and_its_date(self):
        path = self.path()
        C.write_baseline(path, [row("a", lean_cpu_s=30.0,
                                    timed_on="2026-10-05")], "arm64", "v", ["a"])
        C.write_baseline(path, [row("a", lean_cpu_s=12.0,
                                    timed_on="2026-10-06")], "arm64", "v", ["a"],
                         keep=C.load_baseline(path))
        got = C.load_baseline(path)["a"]
        self.assertEqual((got.lean_cpu_s, got.timed_on), (12.0, "2026-10-06"))

    def test_a_foreign_body_is_refused_rather_than_read_as_good(self):
        path = self.path()
        with open(path, "w") as f:
            f.write('{"tag": "something-else", "records": {}}')
        with self.assertRaises(SystemExit):
            C.load_baseline(path)
        with open(path, "w") as f:
            f.write("not json at all")
        with self.assertRaises(SystemExit):
            C.load_baseline(path)

    def test_a_row_missing_a_field_is_refused(self):
        with self.assertRaises(ValueError):
            C.record_from_dict({"stem": "s", "status": "proved"})

    def test_a_status_this_tool_does_not_have_reads_as_the_worst_verdict(self):
        """Never as the best one. A baseline nobody can read must not be a
        green light, so an unrecognised status becomes `crash` — the loudest
        class there is — and says so in its reason."""
        got = C.record_from_dict({f: getattr(row(), f)
                                  for f in C.Record._fields} |
                                 {"status": "proved, obviously"})
        self.assertEqual(got.status, "crash")
        self.assertIn("proved, obviously", got.reason)

    def test_a_replay_is_never_written_as_zero_seconds(self):
        path = self.path()
        C.write_baseline(path, [row("a", lean_wall_s=None, lean_cpu_s=None,
                                    lean_peak_gb=None, cached=True)],
                         "arm64", "v")
        with open(path) as f:
            body = json.load(f)
        self.assertIsNone(body["records"]["a"]["lean_cpu_s"])
        self.assertTrue(body["records"]["a"]["cached"])


class TestCommittedBaseline(unittest.TestCase):
    """The file in the tree, checked for the properties it exists to have."""

    @classmethod
    def setUpClass(cls):
        cls.path = C.baseline_path("arm64")
        with open(cls.path) as f:
            cls.body = json.load(f)
        cls.records = C.load_baseline(cls.path)

    def test_it_is_this_tools_own_baseline(self):
        self.assertEqual(self.body["tag"], C.BASELINE_TAG)
        self.assertEqual(self.body["arch"], "arm64")
        self.assertEqual(self.body["time_factor"], C.TIME_FACTOR)

    def test_every_example_has_a_row_and_every_row_a_status(self):
        self.assertEqual(sorted(self.records), C.corpus(),
                         "an example with no baseline row is one the ratchet "
                         "cannot see; re-seed with --write-baseline")
        for stem, r in self.records.items():
            self.assertIn(r.status, C.STATUS_RANK, f"{stem}: {r.status}")
            self.assertEqual(r.arch, "arm64", stem)

    def test_each_row_is_tied_to_the_example_it_measured(self):
        for stem, r in self.records.items():
            on_disk = C.sha256_file(os.path.join(C.EXAMPLES, stem + ".mojo"))
            self.assertEqual(r.source_sha256, on_disk,
                             f"{stem}.mojo has changed since the baseline was "
                             f"written; re-seed with --write-baseline so the "
                             f"comparison is against this program")

    def test_no_row_claims_a_zero_second_proof(self):
        """`0.0` is the one value that cannot mean "not measured"."""
        for stem, r in self.records.items():
            for field in ("lean_wall_s", "lean_cpu_s"):
                value = getattr(r, field)
                self.assertTrue(value is None or value > 0,
                                f"{stem}: {field}={value} — a replayed "
                                f"verdict measures no time and must be null, "
                                f"never zero")

    def test_at_least_one_row_carries_a_measured_time(self):
        """Otherwise the time ratchet cannot fire and the baseline looks valid.

        A baseline written on a tree whose verdict cache is warm records a
        status for every example and a time for none, because
        `formal/lean.py` replays rather than re-elaborates. That is a real state
        and the tool handles it honestly (null, never zero, reported as
        unmeasured) — but a committed baseline that stays that way has a dead
        half, so this pins that it is not that.
        """
        timed = [s for s, r in self.records.items() if r.lean_cpu_s]
        self.assertTrue(timed,
                        "no row in the committed baseline carries a measured "
                        "Lean CPU time, so the 2x time ratchet can never fire. "
                        "Re-seed some rows with: python3 "
                        "tools/formal_proof_census.py --remeasure --write-"
                        "baseline --only <stem,…>")
        for stem in timed:
            r = self.records[stem]
            self.assertTrue(r.timed_on,
                            f"{stem}: a timing with no date on it reads as "
                            f"this write's measurement, and it is not")
            self.assertIsNotNone(r.lean_peak_gb, stem)

    def test_a_timing_carries_the_date_it_was_taken(self):
        """The property that makes a preserved timing usable at all.

        A replayed write carries a row's `lean_cpu_s` forward (see
        `write_baseline`), and it is `timed_on` — not the write's own
        `written` — that says how old the number is. Without it, a timing taken
        before someone else's `--write-baseline` on another machine reads as
        this tree's measurement, which is the "wrong artifact served from cache"
        failure with a date instead of a filename.

        Checked as "a real date, not in the future" rather than "one date": a
        seeding pass that runs over midnight legitimately dates its rows
        differently, and a test that forbade that would be a test of the
        calendar.
        """
        import datetime
        today = datetime.date.today()
        for stem, r in self.records.items():
            if not r.lean_cpu_s:
                continue
            self.assertRegex(r.timed_on or "", r"^\d{4}-\d{2}-\d{2}$", stem)
            self.assertLessEqual(
                datetime.date.fromisoformat(r.timed_on), today,
                f"{stem}: timed_on is in the future, so the timing was not "
                f"measured on any real machine")

    def test_a_proved_row_admits_nothing(self):
        for stem, r in self.records.items():
            if r.status == "proved":
                self.assertEqual(r.n_sorries, 0, stem)
                self.assertEqual(r.n_admitted, 0, stem)

    def test_every_row_that_emitted_a_proof_counts_its_decide_sites(self):
        for stem, r in self.records.items():
            if r.proof_lines:
                self.assertEqual(r.decide_total,
                                 sum(r.decide_sites.values()), stem)
                self.assertGreater(r.decide_total, 0,
                                   f"{stem}: {r.proof_lines} lines of proof "
                                   f"and not one native_decide/bv_decide "
                                   f"site — the counter is not reading the "
                                   f"file it was given")


class TestClassifyShape(unittest.TestCase):
    """`measure_example`'s own shape, with `compile_formal` faked.

    Three decisions are made by whether a PROOF FILE EXISTS beside the build's
    output, not by the wording of `compile_formal`'s exception — and all three
    were wrong or absent in the first version. It is the discriminator that
    matters most, because a failed verdict is CACHED: `formal/lean.py` publishes
    failures as well as passes, so on a warm tree `compile_formal` raises
    without ever launching Lean, and a tool that classified from "did I see a
    `LeanRun`" reported all thirteen rejected examples as `refused`.

    Faking `compile_formal` is what keeps this Lean-free: the file's whole
    subject is the classification, and the classification is decided before
    Lean is ever asked.
    """

    def setUp(self):
        import formal.build as FB
        self.real = FB.compile_formal
        self.proof_body = ("theorem t : True := by native_decide\n"
                           "theorem u : True := by bv_decide\n")

    def tearDown(self):
        import formal.build as FB
        FB.compile_formal = self.real

    def _fake(self, side_effect=None, result=None, write_proof=False):
        import formal.build as FB
        from formal import lean as L

        def fake(source_path, output=None, **kw):
            if write_proof:
                with open(output[:-len(".aout")] + "_proof.lean", "w") as f:
                    f.write(self.proof_body)
            if side_effect is not None:
                raise side_effect
            return result
        FB.compile_formal = fake
        # `measure_example` reads the proof back through `_read_proof`, which
        # globs the scratch directory; nothing else in it needs Lean.
        self.assertTrue(L.find_lean())

    def test_an_unreadable_proof_is_a_crash_and_never_a_pass(self):
        """The bug this file's own first version had.

        `measure_example` starts with `status = "crash"` and reclassifies a
        completed build into `proved`; testing "is the status still `crash`?"
        as the marker of a completed build also reclassifies an UNREADABLE
        PROOF into `proved`, which is a census reporting its own crash as a
        pass — the one failure mode this whole instrument exists to prevent.
        """
        import formal.build as FB
        self._fake(result={"proof_path": "/nonexistent/ret42_proof.lean",
                           "proof_sorries": 0, "admitted": [],
                           "proof_cached": True})
        got = C.measure_example("ret42")
        self.assertEqual(got.status, "crash")
        self.assertIn("proof unreadable", got.reason)

    def test_a_refusal_writes_no_proof_and_is_a_refusal(self):
        import formal.build as FB
        self._fake(side_effect=FB.FormalBuildError(
            "universal theorem: 2 calls this walk cannot follow"))
        got = C.measure_example("udivmod")
        self.assertEqual(got.status, "refused")
        self.assertEqual(got.phase, "build")
        self.assertIsNone(got.n_sorries)

    def test_a_failed_check_with_a_proof_on_disk_is_a_lean_verdict(self):
        """The warm-cache case: no `LeanRun`, a proof on disk, still a verdict."""
        import formal.build as FB
        self._fake(side_effect=FB.FormalBuildError(
            "proof check failed: sum_proof.lean:1:1: error: unsolved goals"),
            write_proof=True)
        got = C.measure_example("sum")
        self.assertEqual(got.status, "lean-rejected")
        self.assertEqual(got.phase, "check")
        self.assertTrue(got.cached, "no run was captured, so the verdict was "
                                   "replayed and the row must say so")
        self.assertIsNone(got.lean_cpu_s, "a replayed verdict measures no time")
        self.assertEqual(got.decide_sites, {"native_decide": 1, "bv_decide": 1})
        self.assertEqual(got.proof_lines, 2)

    def test_a_generator_refusal_is_named_and_attributed_to_the_generator(self):
        self._fake(side_effect=NotImplementedError(
            "model: a ListExpr has no value in the semantic model"))
        got = C.measure_example("subscript_var")
        self.assertEqual((got.status, got.phase), ("refused", "generate"))


class TestEntryPoint(unittest.TestCase):
    """`--list` builds nothing, which is what makes the tool inspectable."""

    def test_list_is_free_and_prints_the_corpus(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = C.main(["--list"])
        self.assertEqual(rc, 0)
        self.assertIn(str(len(C.corpus())), buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)