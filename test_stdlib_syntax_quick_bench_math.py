#!/usr/bin/env python3
"""Pin for the last `stdlib-syntax` red filed on master: the two files it named
must keep compiling.

The last `stdlib-syntax` red filed on master (2026-11-16, branch
`work/bug-land-codegen-stdlib-dylib-lazy-undef-8`) named exactly these two
files. Measured on master, both already compile cleanly — codegen plus the
gcc `-fsyntax-only` check, with no generic-struct elaboration refusal — so that
report was retired and this pin is its `## Done when`: a regression on either
file fails here with the file's name and the compiler's message.

Kept separate from `test_stdlib_syntax_owned_pointer_asyncrt.py` /
`test_stdlib_syntax_variant.py`: those pin OTHER stdlib-syntax reds, each with
its own report and fixing commit. One pin per red is what makes a failure name
the report it reopens.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, compile_file

PINNED_FILES = [
    'test/benchmark/test_quick_bench.mojo',
    'test/math/test_math.mojo',
]


class TestStdlibSyntaxQuickBenchMath(unittest.TestCase):
    def test_named_files_compile(self):
        stdlib = get_stdlib_path()
        for rel in PINNED_FILES:
            with self.subTest(module=rel):
                # `compile_file` grew a fifth return value (the per-module
                # elaboration refusals) on master after this pin's branch was
                # cut. Its verdict was and is the leading pair, so read that
                # rather than the tuple's width.
                ok, msg = compile_file(str(stdlib / rel))[:2]
                self.assertTrue(
                    ok, f"{rel} (the last stdlib-syntax red filed on master) "
                        f"failed to compile: {msg}")


if __name__ == "__main__":
    unittest.main()
