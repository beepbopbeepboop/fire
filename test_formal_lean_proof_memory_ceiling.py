#!/usr/bin/env python3
"""Regression: per-proof `-M` ceiling via PROOF_MEMORY_MB.

Bug: FORMAL_x86_endtoend_memory_ceiling-part1

Every generated proof was checked under the single corpus ceiling
`formal.lean.LEAN_MEMORY_MB = 6144`; there was no way to give one memory-ceiling
proof (`wide_expr`, `wide_recv`, `list_literal_index`) its own `-M` without
raising the default for everyone.

The fix: one table `PROOF_MEMORY_MB` (example stem -> MB) plus the ONE resolver
`proof_memory_mb(proof_path)`, which every `mem_mb is None` path consults.

The test monkeypatches `formal.lean.run_lean` so NO Lean process is started; it
records the argv `run_lean` is called with (reconstructed from `lean_flags`).  It
fails on the pre-fix code (`proof_memory_mb` and `PROOF_MEMORY_MB` absent) and
passes after.
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from formal import lean as L


class TestPerProofMemoryCeiling(unittest.TestCase):
    """The per-proof `-M` ceiling mechanism."""

    def setUp(self):
        self.lib_dir = tempfile.mkdtemp(prefix="ppm-lib-")
        self.proof_dir = tempfile.mkdtemp(prefix="ppm-p-")
        # proof_memory_mb keys on the basename's stem, so name the file wide_expr.
        self.proof_path = os.path.join(self.proof_dir, "wide_expr.lean")
        with open(self.proof_path, "w") as f:
            f.write("theorem t : 1 = 1 := by trivial\n")
        # Start every test from an empty table, restored afterwards.
        self.addCleanup(self._restore_table, dict(L.PROOF_MEMORY_MB))
        L.PROOF_MEMORY_MB.clear()
        # Intercept run_lean so Lean is never started; record what it receives.
        self.calls = []
        self.addCleanup(setattr, L, "run_lean", L.run_lean)
        L.run_lean = self._fake_run_lean

    def tearDown(self):
        shutil.rmtree(self.proof_dir, ignore_errors=True)
        shutil.rmtree(self.lib_dir, ignore_errors=True)

    def _restore_table(self, saved):
        L.PROOF_MEMORY_MB.clear()
        L.PROOF_MEMORY_MB.update(saved)

    def _fake_run_lean(self, lean, args, cwd=None, env=None, wall_s=None,
                       cpu_s=None, mem_mb=None, heartbeats=None, threads=None):
        argv = ([lean]
                + L.lean_flags(mem_mb, heartbeats, threads)
                + [str(a) for a in args])
        self.calls.append({"args": [str(a) for a in args], "mem_mb": mem_mb,
                           "argv": argv})
        return L.LeanRun(0, "", "", None, 0.0, 0.0, 0, 0)

    def _proof_call(self):
        """The single run_lean call for the proof file (not any --version probe)."""
        proof_calls = [c for c in self.calls if c["args"] != ["--version"]]
        self.assertEqual(len(proof_calls), 1,
                         "expected exactly one proof run_lean call, got %r"
                         % (self.calls,))
        return proof_calls[0]

    # ------------------------------------------------------------------
    # (a)/(b) a stem present in the table is passed as -M to lean
    # ------------------------------------------------------------------

    def test_present_stem_records_raised_mem_in_argv(self):
        L.PROOF_MEMORY_MB["wide_expr"] = 8192
        L._run_lean(self.proof_path, self.lib_dir, "lean", 10.0, 10.0)
        call = self._proof_call()
        self.assertEqual(call["mem_mb"], 8192)
        self.assertIn("-M", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("-M") + 1], "8192",
                         "argv must carry `-M 8192`: %r" % (call["argv"],))

    # ------------------------------------------------------------------
    # (c) an absent stem falls back to LEAN_MEMORY_MB (6144)
    # ------------------------------------------------------------------

    def test_absent_stem_records_corpus_default(self):
        L.PROOF_MEMORY_MB.pop("wide_expr", None)
        L._run_lean(self.proof_path, self.lib_dir, "lean", 10.0, 10.0)
        call = self._proof_call()
        self.assertEqual(call["mem_mb"], L.LEAN_MEMORY_MB)
        self.assertEqual(call["argv"][call["argv"].index("-M") + 1], "6144",
                         "argv must carry `-M 6144`: %r" % (call["argv"],))

    # ------------------------------------------------------------------
    # (d) an explicit mem_mb still wins over the table
    # ------------------------------------------------------------------

    def test_explicit_mem_mb_overrides_table(self):
        L.PROOF_MEMORY_MB["wide_expr"] = 8192
        L._run_lean(self.proof_path, self.lib_dir, "lean", 10.0, 10.0,
                    mem_mb=4096)
        call = self._proof_call()
        self.assertEqual(call["mem_mb"], 4096)
        self.assertEqual(call["argv"][call["argv"].index("-M") + 1], "4096",
                         "an explicit mem_mb must override the table: %r"
                         % (call["argv"],))

    # ------------------------------------------------------------------
    # (e) the verdict key changes with the ceiling for the same proof bytes
    # ------------------------------------------------------------------

    def test_proof_verdict_key_changes_with_ceiling(self):
        # Explicit 6144 vs 8192 on identical proof bytes.
        k_6144 = L.proof_verdict_key(self.proof_path, self.lib_dir, "lean",
                                     mem_mb=6144)
        k_8192 = L.proof_verdict_key(self.proof_path, self.lib_dir, "lean",
                                     mem_mb=8192)
        self.assertNotEqual(k_6144, k_8192,
                            "proof_verdict_key must differ between 6144 and 8192")
        # And the table drives the default: 8192 under the entry, 6144 unpatched.
        L.PROOF_MEMORY_MB["wide_expr"] = 8192
        k_table = L.proof_verdict_key(self.proof_path, self.lib_dir, "lean")
        self.assertEqual(k_table, k_8192,
                         "the table entry must key exactly like an explicit 8192")
        L.PROOF_MEMORY_MB.clear()
        k_default = L.proof_verdict_key(self.proof_path, self.lib_dir, "lean")
        self.assertEqual(k_default, k_6144,
                         "an absent stem must key exactly like an explicit 6144")


if __name__ == "__main__":
    unittest.main()