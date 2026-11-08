"""Regression: suite-self-test crashed when FORMAL_sweep_work_map.md was missing.

The function test_formal_sweep_work_map_index_tags_only_from_section3 must
record a named check failure (not raise FileNotFoundError) when the
consolidated sweep work map is absent.
"""
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_suite


def test_missing_sweep_map_does_not_crash():
    path = os.path.join(HERE, 'bugs', 'FORMAL_sweep_work_map.md')
    backup = path + '.regression-backup'
    had = os.path.exists(path)
    # Save and clear check state so we only see this test's result.
    saved_failures = list(test_suite.FAILURES)
    saved_passes = test_suite.PASSES
    test_suite.FAILURES.clear()
    test_suite.PASSES = 0
    try:
        if had:
            os.rename(path, backup)
        try:
            # Must not raise FileNotFoundError.
            test_suite.test_formal_sweep_work_map_index_tags_only_from_section3()
        except FileNotFoundError as e:
            print(f'FAIL: raised FileNotFoundError: {e}')
            return 1
        checks = test_suite.PASSES + len(test_suite.FAILURES)
        if checks < 1:
            print(f'FAIL: no checks recorded, failures={test_suite.FAILURES}')
            return 1
        if not any('consolidated work map exists' in f for f in test_suite.FAILURES):
            print(f'FAIL: expected a missing-map check failure, got {test_suite.FAILURES}')
            return 1
        print('ok: missing sweep map recorded as check failure, no crash')
        return 0
    finally:
        if had and os.path.exists(backup):
            os.rename(backup, path)
        test_suite.FAILURES[:] = saved_failures
        test_suite.PASSES = saved_passes


if __name__ == '__main__':
    sys.exit(test_missing_sweep_map_does_not_crash())
