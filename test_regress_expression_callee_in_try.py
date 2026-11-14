#!/usr/bin/env python3
"""Regression for bug-formal-formal-a-callee-that-is-an-ex-6547:
a callee that is an EXPRESSION inside a try must be refused (unknown),
not answered False (cannot raise)."""
import formal.model as M


def test_expression_callee_is_refused_not_false():
    # _callee_raises for ("other", "", "") must be True (refuse/unknown),
    # not False (safe-but-wrong "cannot raise").
    class Dummy:
        externs = frozenset()
        defined = frozenset()
        raising = frozenset()
        raising_methods = frozenset()
        bound_modules = {}
        _cross = None

    d = Dummy()
    # The "other" kind (expression callee) must now return True
    assert M.RaiseGraph._callee_raises(d, "other", "", "") is True, \
        "expression callee should be refused (True), not False"
    print("PASS: expression callee refused")


if __name__ == "__main__":
    test_expression_callee_is_refused_not_false()
