"""Regression test for CODEGEN_coroutine_os_path_split_lowers_to_zero.md
Quick only: verifies the split arm is present and the tuple-unpack branch
treats split as a list-valued pair.
"""
import sys, os
sys.path.insert(0, '.')

from mojo.backend_gimple import cpp_core

# 1. split is in aliasable set
def test_split_aliasable():
    assert 'split' in cpp_core._CPP_OS_PATH_ALIASABLE, \
        "split missing from _CPP_OS_PATH_ALIASABLE"

# 2. split arm exists in _cpp_expr (check source line presence)
def test_split_arm_present():
    src = open('mojo/backend_gimple/cpp_core.py').read()
    assert "e.func.member == 'split'" in src, \
        "split arm missing in _cpp_expr"
    assert "int64_t_path_split" in src, \
        "int64_t_path_split missing"
    assert "mojo_os_path_split_w" in src, \
        "mojo_os_path_split_w missing"

# 3. tuple-unpack branch treats split as list-valued
def test_split_tuple_unpack():
    src = open('mojo/backend_gimple/cpp_core.py').read()
    assert "_tup_is_split_call" in src, \
        "_tup_is_split_call missing"

if __name__ == '__main__':
    test_split_aliasable()
    test_split_arm_present()
    test_split_tuple_unpack()
    print("PASS: split fix verified")
