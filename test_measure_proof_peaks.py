#!/usr/bin/env python3
"""Schema and dry-run tests for tools/measure_proof_peaks.py.

Runs no Lean. The dry run is the only thing here that starts a process, and it
starts only the harness itself; the in-process checks patch `Popen` so that a
`lean` spawn would fail the test.

    python3 test_measure_proof_peaks.py TestMeasureProofPeaksSchema
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import measure_proof_peaks as M  # noqa: E402

HARNESS = os.path.join(ROOT, "tools", "measure_proof_peaks.py")


def _fixture_record(stem="wide_expr"):
    return {
        "stem": stem,
        "returncode": 0,
        "peak_rss_mb": 4321,
        "wall_s": 12.5,
        "lean_version": "Lean (version 4.32.2)",
        "mem_limit_mb": 8192,
        "ran_at": "2026-11-23T00:00:00+00:00",
    }


class TestMeasureProofPeaksSchema(unittest.TestCase):

    def test_stems_are_the_three_memory_ceiling_proofs(self):
        self.assertEqual(M.STEMS, ("wide_expr", "wide_recv", "list_literal_index"))

    def test_dry_run_subprocess_exits_zero_with_m8192_per_stem(self):
        p = subprocess.run([sys.executable, HARNESS, "--dry-run"],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)
        for stem in M.STEMS:
            lines = [l for l in p.stdout.splitlines() if l.startswith(stem + ":")]
            self.assertEqual(len(lines), 1, "one argv line per stem, got %r" % p.stdout)
            line = lines[0]
            self.assertIn("-M 8192", line)
            self.assertIn("memslot.py", line)
            self.assertIn("--gb 8", line)

    def test_dry_run_builds_argv_and_spawns_nothing(self):
        def refuse(*_a, **_k):
            raise AssertionError("dry run must not start a process")
        buf = io.StringIO()
        with mock.patch.object(subprocess, "Popen", side_effect=refuse), \
                mock.patch.object(subprocess, "run", side_effect=refuse), \
                contextlib.redirect_stdout(buf):
            rc = M.main(["--dry-run"])
        self.assertEqual(rc, 0)
        for stem in M.STEMS:
            argv = M.job_argv(stem, "lean", "p.lean")
            self.assertIn("-M", argv)
            self.assertEqual(argv[argv.index("-M") + 1], "8192")
            self.assertEqual(argv[-1], "p.lean")
            self.assertIn("--", argv)
            self.assertEqual(argv.index("--") + 1, argv.index("lean"))
        self.assertIn("-M 8192", buf.getvalue())

    def test_fixture_record_validates(self):
        tmp_base = os.environ.get("TMPDIR") or os.path.join(ROOT, ".tmp")
        os.makedirs(tmp_base, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_base) as d:
            path = os.path.join(d, "peaks.json")
            with open(path, "w") as f:
                json.dump({"wide_expr": _fixture_record()}, f)
            with open(path) as f:
                data = json.load(f)
        self.assertEqual(set(data), {"wide_expr"})
        rec = data["wide_expr"]
        self.assertEqual(set(rec), set(M.RECORD_FIELDS))
        self.assertIsInstance(rec["peak_rss_mb"], int)
        self.assertGreaterEqual(rec["peak_rss_mb"], 0)
        self.assertEqual(rec["mem_limit_mb"], 8192)
        M.validate_record("wide_expr", rec)

    def test_schema_rejects_bad_records(self):
        bad = {
            "missing field": {k: v for k, v in _fixture_record().items() if k != "ran_at"},
            "negative peak": dict(_fixture_record(), peak_rss_mb=-1),
            "float peak": dict(_fixture_record(), peak_rss_mb=1.5),
            "wrong ceiling": dict(_fixture_record(), mem_limit_mb=6144),
            "wrong stem": dict(_fixture_record(), stem="wide_recv"),
        }
        for label, rec in bad.items():
            with self.subTest(label), self.assertRaises(ValueError):
                M.validate_record("wide_expr", rec)

    def test_killed_or_refused_stem_keeps_its_returncode(self):
        # A ceiling kill or a Lean refusal is a real record, not a dropped one:
        # validate_record must accept a null/negative returncode and a peak as reached.
        for rc in (None, -6, 1, -9):
            with self.subTest(rc=rc):
                M.validate_record("wide_expr", dict(_fixture_record(), returncode=rc))


if __name__ == "__main__":
    unittest.main()
