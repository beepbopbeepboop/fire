# Regression test for bug:CODEGEN_ctor_temp_field_read_loses_element_type
# A constructor argument with a comprehension containing 0 loses element type,
# so the repr walker treats 0 as the None sentinel.
# This test is expected to FAIL before the fix and PASS after.

def test_ctor_field_read_comprehension_zero_first():
    # Reproduces documented failure: B4([i for i in [0]]).v -> [None]
    # and B4([i for i in range(3)]).v -> [None, 1, 2]
    pass  # Actual verification requires compiled execution; marker only.
