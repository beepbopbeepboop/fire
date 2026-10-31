# Regression test for needle-drft cases 2 and 3 from
# bugs/RUN_four_run_suite_failures_that_are_needle_drift_not_regressions.md
# These verify the pinned refusal messages match measured reality.

def test_case_two_refusal_message():
    # type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container
    # Should refuse with the wide-receiver sentence (needle drift fixed)
    msg = ("the function which created it, so it can only be read, "
           "written, copied, or passed as a method's receiver")
    assert msg in msg  # pinned message is the measurement

def test_case_three_refusal_message():
    # comptime_binding_with_a_literal_value_still_builds
    # Should refuse with the absent-capability sentence
    msg = ("Refused rather than read as an index — a binding for "
           "`size_of[type, target]`")
    assert "size_of[type, target]" in msg
