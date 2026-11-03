#!/usr/bin/env python3
"""Regression: tuple with float + pointer must not infer Span*."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mojo.middle.types as gimple_ctypes
from mojo.middle.resolve_shared import _infer_return_elem_type
import inspect

def test_guard_present():
    src = inspect.getsource(_infer_return_elem_type)
    assert "_has_float = any" in src
    assert "_has_ptr = any" in src
    assert "if _has_float and _has_ptr:\n            return None" in src

def test_join_picks_pointer():
    assert gimple_ctypes.TypeLattice.join_all(['double', 'Span *']) == 'Span *'

if __name__ == '__main__':
    test_guard_present(); test_join_picks_pointer()
    print("PASS regression_tuple_float_ptr")
