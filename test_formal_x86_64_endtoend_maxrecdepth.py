#!/usr/bin/env python3
"""`_header`'s `maxRecDepth` must price the image as well as the step count.

`all_bytes` is a flat `And` chain over every byte of the image (each conjunct a
`List.get` into it), so the kernel's depth to check it scales with the image,
not with the function's step count. A small function with a large image -- the
`call_both_arms`/`elif_call` shape, few steps so the step budget sits at the
1000 floor but a long compiler-trap image -- busts that floor and the file is
rejected with "maximum recursion depth has been reached" on `all_bytes` (the
theorem body then loses `hb` and cascades). Pins the fix that prices
`maxRecDepth` from the image size as well as the step count.

    python3 test_formal_x86_64_endtoend_maxrecdepth.py [-v]
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "formal"))

import formal.x86_64_endtoend_test as ET  # noqa: E402


def _depth(code, steps):
    text = "\n".join(ET._header(code, [], 0, steps))
    m = re.search(r"^set_option maxRecDepth (\d+)$", text, re.M)
    assert m, "no maxRecDepth in header:\n" + text[:400]
    return int(m.group(1))


class TestMaxRecDepthPricesTheImage(unittest.TestCase):
    def test_small_function_large_image_gets_more_than_the_step_floor(self):
        # call_both_arms shape: a handful of steps (step budget -> 1000 floor)
        # but a 532-byte image whose all_bytes term needs well over 1000.
        steps = 20
        code = b"\x00" * 532
        depth = _depth(code, steps)
        self.assertGreaterEqual(
            depth, 2 * (len(code) + 1),
            "maxRecDepth %d is sized only for %d steps and ignores the %d-byte "
            "image, so all_bytes (a conjunct per byte, each a List.get into the "
            "image) exhausts the default 1000 floor on a small-function/"
            "large-image case" % (depth, steps, len(code)))

    def test_long_function_still_gets_its_step_budget(self):
        # The step-proportional budget must not regress: a long function's
        # closing simp nests one successor equation per step (40/step, floor 1000).
        steps = 77
        code = b"\x00" * 64
        depth = _depth(code, steps)
        self.assertGreaterEqual(
            depth, 40 * steps,
            "maxRecDepth %d dropped below the step-proportional budget (40 * %d) "
            "the closing simp needs" % (depth, steps))

    def test_floor_holds_for_tiny_cases(self):
        self.assertGreaterEqual(_depth(b"\x90", 1), 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
