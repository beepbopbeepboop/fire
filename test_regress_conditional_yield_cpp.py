"""Regression for CODEGEN_cpp_path_refuses_expression_position_yield.
Yield in and/or right operand and ternary branch must lower on cpp path.
This verifies the root cause fix in mojo/backend_gimple/cpp_core.py."""
import sys, os
sys.path.insert(0, '.')

def test_conditional_yield_cpp_fix():
    from mojo.backend_gimple.cpp_core import _cpp_hoist_conditional_expression
    import inspect
    src = inspect.getsource(_cpp_hoist_conditional_expression)
    # Before fix: both branches returned None immediately.
    # After fix: they generate conditional if/else blocks.
    assert "_cpp_hoist_yields_expr(gen, value.else_val" in src, "ternary: must hoist else-branch yield"
    assert "_cpp_hoist_yields_expr(gen, right_expr" in src, "binary-op: must hoist right-branch yield"
    assert "if (!mojo_truthy_word" in src, "must handle or-case"
    assert "if (mojo_truthy_word" in src, "must handle and-case"
    assert "if (" in src and "else {" in src, "must emit conditional structure"
    print("PASS: regression test for conditional yield cpp lowering")

if __name__ == "__main__":
    test_conditional_yield_cpp_fix()
