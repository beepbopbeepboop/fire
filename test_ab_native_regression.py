#!/usr/bin/env python3
"""Regression for CODEGEN_ab_native_fails — match_stmt divergence.

This pins the remaining divergence down to the builtin "match_stmt"
case: when both paths (python fire.py --dump and compiled mojoc --dump)
produce byte-identical .ci files, the bug is fixed.

Usage: python3 test_ab_native_regression.py
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def test_regression_pins_match_stmt():
    """Only match_stmt diverged before fix; after fix it must be IDENTICAL.

    Runs test_ab_native.test_inline_source("match_stmt", ...) which
    compiles the same source through the python path and native (mojoc)
    path and compares .ci files byte-for-byte.  If mojoc is not available
    the test reports SKIP (no failure).
    """
    try:
        import test_ab_native
    except ModuleNotFoundError:
        # Can't import test_ab_native without it being on path; skip.
        print("SKIP: test_ab_native not on path; cannot verify match_stmt parity.")
        return

    # Only test the match_stmt case from the builtin corpus.
    source = test_ab_native.BUILTIN_TESTS["match_stmt"]
    try:
        result = test_ab_native.test_inline_source("match_stmt", source)
    except FileNotFoundError as e:
        # mojoc not found — the test cannot run, which is fine; skip.
        print(f"SKIP: {e}")
        return

    if result:
        print("PASS: match_stmt .ci files are IDENTICAL (byte-parity).")
    else:
        # Before fix this was FAIL; after fix it must pass.
        assert False, ("FAIL: match_stmt diverged between python and native "
                        "backends (see the deleted bug doc for ab-native).")


if __name__ == '__main__':
    test_regression_pins_match_stmt()