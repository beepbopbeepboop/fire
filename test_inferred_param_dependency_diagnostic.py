#!/usr/bin/env python3
"""Regression test: inferred-parameter dependency diagnostics.

An inferred parameter (`_`) whose type depends on a non-inferred parameter must be
refused; an element-type parameter that is not inferred must be reported.

Umbrella: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _inferred(ctype):
    # Fixture from the bug: struct RepeatedDep[c: Int, X: Pair[c, c]]
    return elaborate.Elaborator().elaborate_generic_call_inferred(
        'struct RepeatedDep[c: Int, X: Pair[c, c]]', 'RepeatedDep', [ctype])


def test_inferred_param_dependency_refused():
    """struct RepeatedDep[c: Int, X: Pair[c, c]] fails with the dependency diagnostic."""
    try:
        _inferred('c')
    except elaborate.ConformanceError as e:
        assert 'inferred parameter of type \'Pair[c, c]\' cannot depend on non-inferred parameter \'c\'' in str(e), e
        return
    raise AssertionError("struct RepeatedDep[c: Int, X: Pair[c, c]] compiled silently")


def test_satisfied_dependency_compiles():
    """A satisfied dependency (e.g. X: Pair[Int, Int]) compiles."""
    src = '''
struct RepeatedDep[c: Int, X: Pair[c, c]]:
    pass

fn main():
    var f = RepeatedDep[1, (1, 1)]()
'''
    from gimple_codegen import compile_to_gimple
    try:
        compile_to_gimple(src, do_imports=False, filename='/tmp/repro.mojo')
    except RuntimeError as e:
        raise AssertionError(f"satisfied dependency compiled when it should fail: {e}")
    else:
        raise AssertionError("satisfied dependency compiled silently")


if __name__ == '__main__':
    test_inferred_param_dependency_refused()
    test_satisfied_dependency_compiles()
    print('ok')
