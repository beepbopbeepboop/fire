"""Regression for bug-formal-formal-arm64-the-universal-th-9570.
The root cause was the missing return-address map for same-image calls.
This test checks the mechanism directly (no Lean gate needed)."""
import unittest
import tempfile, os, shutil
import formal.arm64_proof_gen as G
import formal.build as fb

class TestSameImagePlanRegression(unittest.TestCase):
    def _plan(self, src):
        tmp = tempfile.mkdtemp(prefix="r9570-")
        try:
            p = os.path.join(tmp, "p.mojo")
            with open(p, "w") as f:
                f.write(src)
            r = fb.compile_formal(p, arch="arm64", output=os.path.join(tmp,"p.aout"),
                                  prove=False, check=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        code, info = r["code"], r["info"]
        entry = info["labels"].get(info["func_name"], info["base_addr"])
        return G._same_image_call_plan(code, info["base_addr"], entry)

    def test_one_leaf_call_is_followable(self):
        got, why = self._plan("def helper(n):\n    return n * 2\n"
                            "def main(x):\n    return helper(x)\n")
        self.assertIsNotNone(got, why)
        self.assertEqual(len(got), 1)

    def test_shared_callee_refused(self):
        got, why = self._plan("def helper(n):\n    return n * 2\n"
                            "def main(x):\n    return helper(x) + helper(x)\n")
        self.assertIsNone(got)
        self.assertIn("same callee", why)

    def test_recursion_refused(self):
        got, why = self._plan("def helper(n):\n    if n>0: return helper(n-1)\n    return n\n"
                            "def main(x):\n    return helper(x)\n")
        self.assertIsNone(got)
        self.assertIn("RECURSION", why)

if __name__ == "__main__":
    unittest.main()
