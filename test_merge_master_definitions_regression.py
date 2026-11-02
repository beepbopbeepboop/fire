#!/usr/bin/env python3
"""Quick regression: EXPORT_RULE_* constants exist after merge fix."""
import formal.model as M

def test_export_rule_constants_defined():
    assert hasattr(M, "EXPORT_RULE_DECLARED")
    assert hasattr(M, "EXPORT_RULE_ABSENT")
    assert M.EXPORT_RULE_DECLARED == "declared"
    assert M.EXPORT_RULE_ABSENT == "absent"

def test_interpolated_census_definitions_present():
    # These were the worst missing definitions that killed test_formal_run.
    assert callable(M.interpolated_field_shape)
    assert callable(M.interpolated_literal_bound)
    assert callable(M.integer_text_width)
    assert callable(M.context_enter_returns_receiver)
    assert callable(M.context_exit_suppression_at_site)
    assert callable(M.is_list_expr)
    assert callable(M.comprehension_element_not_sized)

if __name__ == "__main__":
    test_export_rule_constants_defined()
    test_interpolated_census_definitions_present()
    print("PASS")
