#!/usr/bin/env python3
"""Regression for the Mathlib integration in `formal/lean.py`.

The tree fetches Mathlib through the Lake project in `lakefile.toml`
(`make mathlib`) and the proof checker finds it through
`mathlib_lean_path`/`lean_path`.  Two things have to stay true:

  1. the path helper lists the Lake build dirs when they exist, and lists
     nothing (the pre-Mathlib search path) when `.lake/` is absent; and
  2. `ProofLib` and Mathlib can live in ONE file — a generated proof imports
     both, and a duplicate root declaration aborts the import before any
     theorem is read.  That is not hypothetical: `ProofLib.sub_add` collided
     with Mathlib's root `sub_add` and this is the check that catches the
     next one.

The second check is skipped when `.lake/` has not been fetched (a fresh clone
that has not run `make mathlib`), because there is nothing to import; it is
not a pass, it is an unrun check and is printed as such.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from formal import lean as L

HERE = os.path.dirname(os.path.abspath(__file__))
PROOF_DIR = os.path.join(tempfile.gettempdir(), "proof-dir")
LIB = os.path.join(HERE, "lib")


def test_path_helper():
    dirs = L.mathlib_lean_path(LIB)
    if not os.path.isdir(os.path.join(HERE, ".lake")):
        assert dirs == [], f"no .lake/ but mathlib_lean_path returned {dirs!r}"
        print("PASS: no .lake/ -> empty Mathlib path")
        return False
    assert dirs, "mathlib_lean_path found no build dirs under .lake/"
    assert any(os.path.basename(os.path.dirname(os.path.dirname(d))) == "mathlib"
               or os.sep + "mathlib" + os.sep in d for d in dirs), \
        f"no Mathlib build dir in {dirs!r}"
    joined = L.lean_path(LIB, PROOF_DIR)
    for d in dirs:
        assert d in joined, f"lean_path dropped {d}"
    assert joined.startswith(PROOF_DIR + os.pathsep), \
        "the proof directory must come FIRST"
    print(f"PASS: {len(dirs)} Mathlib build dirs, composed by lean_path")
    return True


def test_prooflib_and_mathlib_coexist():
    lean = L.find_lean()
    assert lean, "lean not found"
    L.ensure_library(lean, LIB)
    src = """import ProofLib
import ProofLibSteps
import work
import Refine
import Mathlib.Tactic
import Aesop

example : 1 + 1 = 2 := by norm_num
example (n : Nat) (h : n < 3) : n = 0 \u2228 n = 1 \u2228 n = 2 := by
  interval_cases n <;> simp
"""
    with tempfile.TemporaryDirectory(prefix="mathlib_test_") as td:
        p = os.path.join(td, "coexist.lean")
        with open(p, "w") as f:
            f.write(src)
        env = dict(os.environ)
        env["LEAN_PATH"] = L.lean_path(LIB)
        # Through the launcher, like every Lean run in the tree: its bounds and
        # process-group kill apply, and `exceeded` says which one a run hit.
        r = L.run_lean(lean, [p], cwd=td, env=env)
    assert r.exceeded is None, f"Lean hit a bound: {r.exceeded}"
    assert r.returncode == 0, (
        "ProofLib + Mathlib failed to coexist:\n"
        + (r.stdout or "") + (r.stderr or ""))
    print("PASS: ProofLib + Mathlib + Aesop coexist; norm_num/interval_cases work")


if __name__ == "__main__":
    fetched = test_path_helper()
    if fetched:
        test_prooflib_and_mathlib_coexist()
    else:
        print("SKIP: .lake/ not fetched (run `make mathlib`); coexistence unrun")
