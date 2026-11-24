#!/usr/bin/env python3
"""Pin for the 2026-11-12 stdlib-syntax red (gate job `stdlib-syntax`).

`std/memory/owned_pointer.mojo` and `std/runtime/_asyncrt.mojo` were the two
files still failing after that round, on branch
`work/fix-merge-bug-mid-diagnostics-binding-deferrals-pa-3`. Both were restored
to green by 565b85aca (the pointer-arm check now reads the return arm's SOURCE
shape instead of the erased C type). They must keep compiling.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, compile_file


class TestStdlibSyntaxOwnedPointerAsyncrt(unittest.TestCase):
    def test_owned_pointer_and_asyncrt_compile(self):
        stdlib = get_stdlib_path()
        for rel in ("std/memory/owned_pointer.mojo",
                    "std/runtime/_asyncrt.mojo"):
            with self.subTest(module=rel):
                ok, msg, _cg, _gcc, _ref = compile_file(str(stdlib / rel))
                self.assertTrue(ok, f"{rel} failed to compile: {msg}")


if __name__ == "__main__":
    unittest.main()
