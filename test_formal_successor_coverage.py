"""Regression: SUCCESSOR_FORMS must cover all _FORMS forms.
Bug: FORMAL_x86_64_the_successor_table_is_compared_against_the_model_on_six_forms."""
import formal.x86_64_model_coverage_test as M
import formal.x86_64_endtoend_test as E

def test_successor_forms_covers_all_forms():
    covered = {row[0] for row in M.SUCCESSOR_FORMS}
    forms = set(E._FORMS)
    missing = forms - covered
    assert not missing, "SUCCESSOR_FORMS missing %d form(s): %s" % (len(missing), sorted(missing))
    assert len(M.SUCCESSOR_FORMS) == len(E._FORMS), "SUCCESSOR_FORMS has %d rows but _FORMS has %d" % (len(M.SUCCESSOR_FORMS), len(E._FORMS))

if __name__ == "__main__":
    test_successor_forms_covers_all_forms()
    print("PASS: all forms covered")
