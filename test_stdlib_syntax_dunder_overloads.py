#!/usr/bin/env python3
"""Regression pin for the stdlib-syntax red on overloaded dunder call sites.

`_emit_struct_method_prototypes` no longer emits a suffix-less forward
declaration for an overloaded dunder (its bare symbol is defined by no
overload). That is only safe when every dunder call site names a concrete
overload. Three real stdlib shapes still named the bare symbol, so their
generated C called a function nothing declares:

  * `BinaryHeap[Int](copy=heap)` — the implicit copy constructor, with no
    declared `__init__(*, copy: Self)` candidate;
  * `StringDict[StringSpan, Int][StringSpan("fruit")]` — two same-arity
    `__getitem__` overloads whose C parameter types erase identically, so the
    ctype score cannot choose one;
  * `with TempEnvWithCleanup(...)` — the one-argument `__exit__(error)`
    overload, while the zero-argument overload was the bare-name target.

Each case transpiles to C that gcc accepts. `transpile_file` is the same
per-module stage `stdlib-syntax` uses, so this fails before the fix with the
gate's own `implicit declaration of function` errors.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, transpile_file


CASES = [
    "test/collections/test_binary_heap.mojo",
    "test/collections/test_dict.mojo",
    "test/tempfile/test_tempfile.mojo",
]


class TestStdlibSyntaxDunderOverloads(unittest.TestCase):
    def test_overloaded_dunder_call_sites_compile(self):
        root = get_stdlib_path()
        for rel in CASES:
            with self.subTest(module=rel):
                ok, msg, _cg, _gcc, _ref = transpile_file(str(root / rel))
                self.assertTrue(ok, f"{rel} failed to transpile: {msg}")


if __name__ == "__main__":
    unittest.main()
