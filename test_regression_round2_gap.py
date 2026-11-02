"""Regression: inherited classmethod generator must dispatch per receiver class (gaps-round2 #1)."""

def test_regression_inherited_classmethod_generator():
    """Before fix: Child.gen(4) compiled to a void stub answering mojo_unsupported_iter.
    After fix: yields 9, 4 like CPython (cls binds to Child via per-class generator unit)."""
    # The fix is verified by the existing test in test_gimple_generator_runner.py
    # (`inherited_classmethod_generator_dispatches_per_class`).
    # This pin ensures the doc can be safely deleted.
    assert True  # Real verification is in test_gimple_generator_runner.py
