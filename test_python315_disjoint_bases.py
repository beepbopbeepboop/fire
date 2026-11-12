#!/usr/bin/env python3
"""Regression: Python 3.15 disjoint bases (`typing.disjoint_base`).

Python 3.15 adds `typing.disjoint_base`, a decorator that marks a class as a
disjoint base for type checkers and sets `cls.__disjoint_base__ = True` at
runtime (no runtime MRO/layout enforcement).

The interpreter must:
  - resolve `typing.disjoint_base` (available in 3.15's `typing`)
  - apply class/struct decorators (root cause: execute_StructDef ignored
    node.decorators, so `@disjoint_base` was dropped)
  - expose the `__disjoint_base__` marker on the decorated class
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class TestDisjointBaseInterpreter(unittest.TestCase):
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

    def test_disjoint_base_decorator_sets_marker(self):
        src = (
            "from typing import disjoint_base\n"
            "\n"
            "@disjoint_base\n"
            "class C:\n"
            "    pass\n"
            "\n"
            "print(C.__disjoint_base__)\n"
            "print('ok')\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "True\nok\n")

    def test_disjoint_base_manual_decoration(self):
        src = (
            "from typing import disjoint_base\n"
            "\n"
            "class D:\n"
            "    pass\n"
            "D2 = disjoint_base(D)\n"
            "print(D2 is D)\n"
            "print(D.__disjoint_base__)\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "True\nTrue\n")

    def test_class_decorators_applied_interpreted(self):
        # Root-cause guard: class decorators must be applied in execute_StructDef.
        src = (
            "def mark(cls):\n"
            "    cls.marked = 7\n"
            "    return cls\n"
            "\n"
            "@mark\n"
            "class E:\n"
            "    x = 1\n"
            "\n"
            "print(E.marked)\n"
            "print(E.x)\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "7\n1\n")


if __name__ == "__main__":
    unittest.main()
