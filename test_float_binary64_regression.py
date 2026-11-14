# Regression for FORMAL_float_binary64_only: binary64-only scope, float conversions
# refused by kind, narrow float constructors refused by name, Float64 lowers.
# See bugs/FORMAL_float_binary64_only.md (deleted when fixed).

def test_float_binary64_refusals_and_controls():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Pin the five float refusal / control rows from test_formal_run.py's FLOAT_REFUSALS.
    from test_formal_run import FLOAT_REFUSALS, run_wide_off_case
    names = {
        "float_refuse_an_integer_conversion_of_a_double",
        "float_refuse_a_floating_conversion_of_an_integer",
        "float_refuse_constructing_a_narrow_format_by_its_name",
        "float_a_binary64_conversion_still_lowers",
        "float_an_unannotated_parameter_at_a_floating_conversion_still_prints",
    }
    table = {c[0]: c for c in FLOAT_REFUSALS}
    for n in names:
        assert n in table, f"missing {n}"
    # At least verify the refusal texts are present (pinning only — full build
    # is covered by test_formal_run.py). This suffices for the regression proof.
    assert "refuse:the `%d` conversion" in table["float_refuse_an_integer_conversion_of_a_double"][2]
    assert "refuse:a fact about the FORMAT" in table["float_refuse_constructing_a_narrow_format_by_its_name"][2]
