"""`bootstrap-validate.mojo` must check every source the bootstrap stages dump.

The gate job `bootstrap-validate` exists to be the COMPLETENESS half of the
three-stage fixed-point check: `tools/bootstrap_verify.py` compares the union of
the artefacts that all three stages happen to have produced, and reports a file
missing from a stage as a WARNING (it only fails on that with `--strict`, which
the suite does not pass), so a stage that silently drops an artefact stays green
there.  `bootstrap-validate.mojo` is the job that says every input produced
`.ci`/`.tok`/`.ast`/`.pyi` in all three stages.  Its input list was a second,
hand-maintained copy of the drivers' list, and it went stale at the
`mojo.py` -> `fire.py` rename (2026-09-26): it still named `mojo.py`,
`mojo_compiler.py` and `mojo_main.py` (none of which exists, so `os.path.isfile`
silently skipped them) and had never heard of `fire.py`, `fire_compiler.py` or
`fire_main.py` — half of `tools/suite.py::PY_FILES`, including `fire.py` (the
driver) and `fire_compiler.py` (the parser/AST source of truth).  A stage2 that
dropped any of the three would have been reported as `PASSED`.

These tests drive the real script against synthetic stage trees, so they pin
the behaviour a future edit could break, not the shape of its source:

- every source in `suite.PY_FILES` is checked (delete its stage2 `.ci` and the
  run must FAIL and name the file) — this is the regression: the old list made
  the three renamed-to-`fire_*` sources invisible;
- a `.py` file that is not a bootstrap input is not checked (a decoy must not
  make a clean tree fail);
- the `*.mojo` half still comes from the glob, so a missing `.mojo` artefact
  fails too, and a fully matching tree passes.

`suite` is the source of truth for the input list, and importing it here is
deliberate: the script itself cannot import it at run time without adding
constructs to a file the self-hosted binary compiles as part of the bootstrap
corpus (`bootstrap-stage2-dumps:bootstrap-validate.mojo`), so the duplicate is
kept honest by this check instead of being consolidated inside the script.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import tools.suite as S

REPO = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(REPO, "bootstrap-validate.mojo")
EXTS = ("ci", "tok", "ast", "pyi")


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


class SyntheticStages(unittest.TestCase):
    """A three-stage tree with a matching artefact for every bootstrap input."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bootstrap-validate-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        for stage in ("stage1", "stage2", "stage3"):
            os.mkdir(os.path.join(self.dir, stage))

        self.py_stems = [stem(name) for name in S.PY_FILES]
        stems = self.py_stems + [stem(p) for p in S.MOJO_FILES]
        # The sources themselves: `.mojo` ones are found by the script's glob,
        # the `.py` ones by `os.path.isfile`, both relative to the cwd the
        # suite runs it from (the repo root; here, the synthetic tree).
        for name in list(S.MOJO_FILES) + list(S.PY_FILES):
            path = os.path.join(self.dir, name)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("# synthetic bootstrap input\n")
        for name in stems:
            for ext in EXTS:
                # Distinct content per file so a mismatched stage is detectable,
                # identical across stages so the healthy run is a PASS.
                body = ("%s.%s\n" % (name, ext)).encode()
                for stage in ("stage1", "stage2", "stage3"):
                    with open(os.path.join(self.dir, stage,
                                           "%s.%s" % (name, ext)), "wb") as f:
                        f.write(body)
        self.total = len(stems) * len(EXTS)

    def run_validate(self):
        proc = subprocess.run([sys.executable, SCRIPT], cwd=self.dir,
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def artefact(self, stage, name, ext):
        return os.path.join(self.dir, stage, "%s.%s" % (name, ext))

    def test_a_matching_tree_passes(self):
        code, out = self.run_validate()
        self.assertEqual(0, code, out)
        self.assertIn("PASSED: all %d output files match" % self.total, out)

    def test_every_dumped_python_source_is_checked(self):
        # The bug: `fire.py`, `fire_compiler.py` and `fire_main.py` were in the
        # drivers' list and not in the validator's, so their artefacts were
        # never compared-or-required by this job.
        for name in self.py_stems:
            path = self.artefact("stage2", name, "ci")
            os.rename(path, path + ".aside")
            try:
                code, out = self.run_validate()
                self.assertEqual(
                    1, code,
                    "a missing stage2/%s.ci was not reported:\n%s" % (name, out))
                self.assertIn("MISSING stage2/%s.ci" % name, out)
            finally:
                os.rename(path + ".aside", path)

    def test_every_dumped_mojo_source_is_checked(self):
        for name in [stem(p) for p in S.MOJO_FILES]:
            path = self.artefact("stage3", name, "pyi")
            os.rename(path, path + ".aside")
            try:
                code, out = self.run_validate()
                self.assertEqual(
                    1, code,
                    "a missing stage3/%s.pyi was not reported:\n%s" % (name, out))
                self.assertIn("MISSING stage3/%s.pyi" % name, out)
            finally:
                os.rename(path + ".aside", path)

    def test_a_python_file_that_is_not_a_bootstrap_input_is_ignored(self):
        # Exactness in the other direction: the list must be the drivers' list,
        # not a superset.  `mojo.py`/`mojo_compiler.py`/`mojo_main.py` are the
        # names the staleness left behind; they must stay out even if such a
        # file appears in the tree.
        for decoy in ("mojo.py", "mojo_compiler.py", "mojo_main.py"):
            with open(os.path.join(self.dir, decoy), "w", encoding="utf-8"):
                pass
        code, out = self.run_validate()
        self.assertEqual(0, code, out)
        self.assertIn("PASSED: all %d output files match" % self.total, out)

    def test_a_stage1_only_source_failure_is_named(self):
        # stage1 is the ground truth: an artefact missing there is a FAIL even
        # though two stages agree with each other.
        path = self.artefact("stage1", self.py_stems[0], "tok")
        os.rename(path, path + ".aside")
        try:
            code, out = self.run_validate()
            self.assertEqual(1, code, out)
            self.assertIn("MISSING stage1/%s.tok" % self.py_stems[0], out)
        finally:
            os.rename(path + ".aside", path)


if __name__ == "__main__":
    unittest.main()
