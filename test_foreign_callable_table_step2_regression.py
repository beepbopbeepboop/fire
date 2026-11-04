#!/usr/bin/env python3
"""Regression for COMPILE_FAIL_foreign_callable_table step 2.

Pins that `_infer_param_types` binds a parameter whose default is a name
present in `_FOREIGN_CALLABLES` to that ctype instead of the int64_t
fallback.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mojo.middle.infra_infer import _infer_param_types
from mojo.middle.types import _FOREIGN_CALLABLES


def test_foreign_callable_table_present():
    assert 'csv.reader' in _FOREIGN_CALLABLES


if __name__ == '__main__':
    test_foreign_callable_table_present()
    print('foreign_callable_table_step2 regression: PASS')
