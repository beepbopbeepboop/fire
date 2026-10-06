#!/usr/bin/env python3
"""The recursion contract's forced branch, for a `B.cond` test.

`count_contract` (and every other single-recursion contract in
`formal/examples/`) is proved by `contract_sound`, which needs two CFG walks:
`hbase` for `x0 = 0` and `hstep` for `x0 = arg = k + 1`.  Each walk crosses the
recursion's own test — a `B.cond` on the flags a `CMP` set — and the contract
generator forces the direction it knows the source takes (`cbz_force="fall"` in
the base case, `"taken"` in the step case).

Deciding a forced direction is a VALUE-FLOW obligation.  The step lemma leaves

    arm64_step s C = some (if <flag test> then <taken> else <fall>)

and the walk's state is `s_n`, a `qT` chain off the entry state, so the flag
test cannot be evaluated until the chain is folded back (`hsid_n`), the flags
are bridged to the comparison that produced them (`_COND_LEMMA` for the
branch's raw condition field) and the contract's own hypothesis decides the
rest: `x0 = 0` in the base case, `x0 = arg` with `arg ≠ 0` in the step case.

The generator's script for that leaf used to unfold the flags and stop, so
`s_n` never became `st` and the `if` could not be resolved: **every**
single-recursion contract admitted a `sorry` — 5 of the 7 holes the arm64
census reported (`count`, `fact`, `pow2`, `sqsum`, `sum`), all of them these
two leaves.  A proof that reports PASS while resting on a `sorry` is worse
than one that fails, because the census has to be read to notice.

The Lean half is skipped, loudly, without Lean or the built `lib/ProofLib.olean`;
the text half runs either way.

    python3 test_formal_recursion_contract.py [-v]
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROOF_GEN = os.path.join(HERE, "formal", "arm64_proof_gen.py")

# One program per shape the five fixed examples had in common.  Self-contained
# (they do not read formal/examples/, which is a parser invariant with its own
# test), and each is the tail-recursive base test `contract_sound` splits on.
PROGRAMS = {
    # `count`: the recursion is the whole body of the else arm.
    "tailrec": ("def tailrec(n):\n"
                "    if n == 0:\n"
                "        return 0\n"
                "    else:\n"
                "        return tailrec(n - 1)\n"),
    # `sum`: the call's result is combined afterwards, so the return value has
    # to be read out of the callee's frame rather than passed through x0.
    "addrec": ("def addrec(n):\n"
               "    if n == 0:\n"
               "        return 0\n"
               "    else:\n"
               "        return n + addrec(n - 1)\n"),
    # `pow2`: the base value is 1, so the contract's `x0 = 0` case is not the
    # only way out of the test — a different literal on each side.
    "baseret": ("def baseret(n):\n"
                "    if n == 0:\n"
                "        return 1\n"
                "    else:\n"
                "        return 2 * baseret(n - 1)\n"),
}


def _read(path):
    with open(path) as f:
        return f.read()


def _lean():
    from formal.lean import find_lean
    return find_lean(HERE)


def _generate(tmp, source, name, arch="arm64"):
    """Compile `source`, return `(proof_path, error)`; error is None on success."""
    import formal.build as fb
    src = os.path.join(tmp, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmp, name + ".aout")
    try:
        r = fb.compile_formal(src, arch=arch, output=out, prove=True, check=False)
        return r["proof_path"], None
    except Exception as e:            # noqa: BLE001 -- the point is to report it
        return None, f"{type(e).__name__}: {e}"


def _contract(text, name):
    """The `<name>_contract` proof (statement + tactic), or None."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(f"theorem {name}_contract "):
            out = [ln]
            for follow in lines[i + 1:]:
                out.append(follow)
                if not follow.strip():
                    break
            return "\n".join(out)
    return None


class TestForcedBranchScript(unittest.TestCase):
    """What the generator emits for the forced branch, which needs no Lean."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="recc-")
        cls.proofs, cls.errors = {}, {}
        for name, src in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            cls.proofs[name], cls.errors[name] = p, err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_program_generates_a_contract(self):
        for name in PROGRAMS:
            with self.subTest(program=name):
                self.assertIsNone(self.errors[name],
                                  f"{name}: proof generation raised "
                                  f"{self.errors[name]}")

    def test_the_forced_branch_folds_the_state_chain(self):
        """`hsid_n` is what turns `s_n` back into the entry state."""
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            with self.subTest(program=name):
                body = _contract(_read(p), name)
                self.assertIsNotNone(
                    body, f"{name}: no `{name}_contract` was emitted")
                steps = re.findall(
                    r"have hs_\d+ : arm64_step \(s_\d+\) \w+ = some "
                    r"\(\{ s_\d+ with pc := \d+ \}\) := by\n"
                    r"((?:\s+.*\n)+)", body)
                self.assertTrue(
                    steps,
                    f"{name}: the contract has no forced-branch step; the "
                    f"script below is what has to decide its `if`")
                for blk in steps:
                    self.assertIn(
                        "hsid_", blk,
                        f"{name}: a forced branch unfolds the flags with no "
                        f"`hsid` in the simp set, so the state it branches on "
                        f"is an opaque `s_n` and the obligation can only end "
                        f"in a `sorry`:\n{blk}")
                    self.assertIn(
                        "arm64_flag_", blk,
                        f"{name}: a forced branch has no flag-to-comparison "
                        f"bridge, so the `if` is a `decide` over an "
                        f"unevaluated flag chain:\n{blk}")

    def test_the_sorry_is_the_last_resort_not_the_plan(self):
        """The value flow comes first; the hole is only reached if it misses."""
        for name, p in sorted(self.proofs.items()):
            if not p:
                continue
            with self.subTest(program=name):
                body = _contract(_read(p), name)
                for blk in re.findall(
                        r"have hs_\d+ : arm64_step \(s_\d+\) \w+ = some "
                        r"\(\{ s_\d+ with pc := \d+ \}\) := by\n"
                        r"((?:\s+.*\n)+)", body):
                    self.assertLess(
                        blk.index("hsid_"), blk.index("sorry"),
                        f"{name}: the `sorry` comes before the value flow, so "
                        f"the leaf was never attempted:\n{blk}")

    def test_the_generator_names_the_shared_factories(self):
        """The three pieces the fix reuses, not a private copy of each."""
        gen = _read(PROOF_GEN)
        self.assertIn("_COND_LEMMA.get(_cset_cond(block, words))", gen,
                      "the forced branch must pick its flag bridge from the "
                      "shared `_COND_LEMMA` table (one entry per arm64 "
                      "condition field), not hard-code one comparison")
        self.assertIn("_VALUE_SIMP", gen,
                      "the value-flow simp set is the shared `_VALUE_SIMP`; a "
                      "second list here would drift from the one the other "
                      "obligations in the same proof close with")


class TestContractTypechecks(unittest.TestCase):
    """The contract must close, with no hole left behind."""

    @classmethod
    def setUpClass(cls):
        lean = _lean()
        if not lean or not os.path.isfile(
                os.path.join(HERE, "lib", "ProofLib.olean")):
            raise unittest.SkipTest(
                "no Lean / no lib/ProofLib.olean: skipping the typecheck. "
                "Run `make prooflib` (or `python3 tools/suite.py prooflib`) "
                "first -- every assertion below is about Lean accepting the "
                "generated contract, and none of it runs without it.")
        from formal.lean import check_proof_cached
        cls.tmp = tempfile.mkdtemp(prefix="recc-lean-")
        cls.results = {}
        for name, src in PROGRAMS.items():
            p, err = _generate(cls.tmp, src, name)
            if err:
                cls.results[name] = (False, err, 0)
            else:
                ok, detail, _cached, n = check_proof_cached(
                    p, repo_root=HERE)
                cls.results[name] = (ok, detail, n)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_contract_typechecks_with_no_sorries(self):
        for name, (ok, detail, n) in sorted(self.results.items()):
            with self.subTest(program=name):
                self.assertTrue(ok, f"{name}: {detail}")
                self.assertEqual(
                    n, 0,
                    f"{name}: the proof admits {n} `sorry`; a contract that "
                    f"rests on one PASSes while proving nothing about the "
                    f"forced branch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
