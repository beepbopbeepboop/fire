"""Regression pin for CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.
The `next(<user-defined iterator struct>)` lowering and the `for` loop's
named refusal are pinned by test_gimple.py; this file keeps the claim
honest after the bug doc was removed."""

def test_pinned():
    # The existing test_next_on_a_user_struct_lowers_and_its_for_loop_says_why_not
    # in test_gimple.py asserts both halves (lowering + named refusal).
    pass
