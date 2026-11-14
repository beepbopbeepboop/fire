#!/usr/bin/env python3
"""Regression for COMPILE_FAIL_foreign_callable_table step 2.

Pins that `_infer_param_types` binds a parameter whose default is a name
present in `_FOREIGN_CALLABLES` to that ctype instead of the int64_t
fallback.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fire_compiler import FunctionDef, IdentExpr, MemberExpr
from mojo.middle.infra_infer import _infer_param_types
from mojo.middle.types import _FOREIGN_CALLABLES


class DummyGen:
    def __init__(self):
        self.func_return_types = {}
        self._func_param_names = {}
        self._inferred_param_types = {}
        self._KNOWN_SIGS = {}
        self.struct_field_types = {}
        self._param_usage_scan_cache = {}


def test_foreign_callable_table_present():
    assert 'csv.reader' in _FOREIGN_CALLABLES


def test_infer_param_types_binds_foreign_callable_default():
    gen = DummyGen()
    func = FunctionDef(
        name='f',
        params=[('x', None), ('_g', None)],
        return_type=None,
        body=[],
        param_defaults={'_g': MemberExpr(obj=IdentExpr(name='csv'), member='reader')}
    )
    res = _infer_param_types(gen, func)
    assert res.get('_g') == _FOREIGN_CALLABLES['csv.reader']


if __name__ == '__main__':
    test_foreign_callable_table_present()
    test_infer_param_types_binds_foreign_callable_default()
    print('foreign_callable_table_step2 regression: PASS')
