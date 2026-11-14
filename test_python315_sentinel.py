#!/usr/bin/env python3
"""Regression: Python 3.15 `sentinel` builtin (PEP 661).

The interpreter must expose `sentinel(name, /, *, repr=None)` with CPython
3.15 semantics, and the formal backends must refuse it BY NAME (a fresh unique
runtime identity this one-word model cannot produce) rather than reaching a
generic missing-name diagnostic.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class TestSentinelBuiltinInterpreter(unittest.TestCase):
    def _run_fire(self, source):
        with tempfile.TemporaryDirectory(dir=os.path.join(HERE, ".tmp")) as td:
            path = os.path.join(td, "t.mojo")
            with open(path, "w") as f:
                f.write(source)
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "fire.py"), "run", path],
                capture_output=True, text=True, timeout=30,
            )
        return r

    def test_sentinel_basic_semantics(self):
        src = (
            "def main():\n"
            "    a = sentinel('MISSING')\n"
            "    b = sentinel('MISSING')\n"
            "    if a is b:\n"
            "        print('same')\n"
            "    else:\n"
            "        print('distinct')\n"
            "    print(repr(a))\n"
            "    c = sentinel('X', repr='<X>')\n"
            "    print(repr(c))\n"
            "    if type(a) is type(b):\n"
            "        print('sametype')\n"
            "    if a == a:\n"
            "        print('eqself')\n"
            "    if a == b:\n"
            "        print('eqother')\n"
            "    else:\n"
            "        print('neqother')\n"
            "main()\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout,
            "distinct\nMISSING\n<X>\nsametype\neqself\nneqother\n",
        )

    def test_sentinel_isinstance(self):
        src = (
            "def main():\n"
            "    s = sentinel('S')\n"
            "    if isinstance(s, type(s)):\n"
            "        print('ok')\n"
            "    else:\n"
            "        print('bad')\n"
            "main()\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "ok\n")


class TestSentinelFormalModel(unittest.TestCase):
    def test_not_lowered_builtin_registered(self):
        from formal.model.builtins import NOT_LOWERED_BUILTINS

        self.assertIn("sentinel", NOT_LOWERED_BUILTINS)
        why = NOT_LOWERED_BUILTINS["sentinel"]
        self.assertIn("unique", why.lower())
        self.assertIn("object", why.lower())

    def test_conformance_case_present(self):
        # The formal conformance table carries a sentinel refusal case next to
        # the other fresh-object builtins, so the compiled path is pinned.
        path = os.path.join(HERE, "test_formal_builtins_conformance.py")
        with open(path) as f:
            text = f.read()
        self.assertIn('"sentinel"', text)
        self.assertIn("sentinel(\\\"MISSING\\\")", text)
        self.assertIn("`sentinel(...)` is not lowered on this path", text)


if __name__ == "__main__":
    unittest.main()
