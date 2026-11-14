#!/usr/bin/env python3
"""Regression: Python 3.15 `frozendict` builtin type (interpreter)."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class TestFrozendictBuiltinInterpreter(unittest.TestCase):
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

    def test_frozendict_exists_and_basic(self):
        src = (
            "def main():\n"
            "    d = frozendict({'a': 1, 'b': 2})\n"
            "    print(len(d))\n"
            "    print(d['a'])\n"
            "    print('b' in d)\n"
            "    print(list(d.keys()))\n"
            "main()\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertIn('2', r.stdout)
        self.assertIn('1', r.stdout)
        self.assertIn('True', r.stdout)

    def test_frozendict_kwargs_and_immutable(self):
        src = (
            "d = frozendict(a='b')\n"
            "try:\n"
            "    d['c'] = 'x'\n"
            "    print('mutated')\n"
            "except TypeError:\n"
            "    print('immutable')\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertIn('immutable', r.stdout)

    def test_frozendict_fromkeys(self):
        src = (
            "d = frozendict.fromkeys(['a', 'b'], 0)\n"
            "print(len(d))\n"
            "print(d['a'])\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertIn('2', r.stdout)
        self.assertIn('0', r.stdout)


if __name__ == "__main__":
    unittest.main()
