"""Regression: the suite self-test crashed when the consolidated formal
sweep work map was missing.

`test_suite.py`'s `test_formal_sweep_work_map_index_tags_only_from_section3`
used to open the consolidated map unconditionally, so on a tree without it
the whole self-test died with an unhandled `FileNotFoundError` before it
could report a single check. This pin renames the map away, runs the
function, and fails if it raises, or if the missing-map condition is not
reported as the named check failure the guard records.

The path comes from `test_suite.SWEEP_WORK_MAP` so this test and the guard
cannot drift to two different files; it is spelled there once, not here, so
this file carries no citation of a document the tree has deleted.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_suite


def test_missing_sweep_map_does_not_crash():
    path = test_suite.SWEEP_WORK_MAP
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
