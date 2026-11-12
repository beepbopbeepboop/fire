#!/usr/bin/env python3
"""Regression test: an inferred parameter cannot depend on a non-inferred one.

An inferred parameter is one whose type has a `_` placeholder. Its implicit
type, with the callee's parameters replaced by the arguments, may not mention a
non-inferred parameter of the same signature. Modular's
test/mojo-parser/autoparam_dependency_errors.mojo requires:

    struct RepeatedDep[c: Int, X: NeedsPair[c, c, _]]
    # error: inferred parameter of type 'Pair[c, c]' cannot depend on
    #        non-inferred parameter 'c'

Checked by fire_compiler._check_inferred_param_dependencies, run from
Parser.parse_module, and surfaced through compile_to_gimple.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

_PRELUDE = (
    'struct Pair[a: Int, b: Int](Movable where False):\n'
    '    pass\n'
    '\n'
    'struct NeedsPair[a: Int, b: Int, p: Pair[a, b]](Movable where False):\n'
    '    pass\n'
    '\n'
)


def _compile(src):
    # The check runs on the parse, and the source is read from a real file.
    d = tempfile.mkdtemp(prefix='inferred_dep_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    return compile_to_gimple(src, do_imports=True, filename=p)


def test_repeated_dependency_is_refused():
    src = _PRELUDE + 'struct RepeatedDep[c: Int, X: NeedsPair[c, c, _]]:\n    pass\n'
    try:
        _compile(src)
    except RuntimeError as e:
        text = str(e)
        assert ("inferred parameter of type 'Pair[c, c]' cannot depend on "
                "non-inferred parameter 'c'") in text, text
        return
    raise AssertionError('a dependency on a non-inferred parameter compiled')


def test_each_distinct_dependency_is_reported_once():
    src = _PRELUDE + 'struct TwoDeps[a: Int, b: Int, X: NeedsPair[a, b, _]]:\n    pass\n'
    try:
        _compile(src)
    except RuntimeError as e:
        text = str(e)
        assert ("'Pair[a, b]' cannot depend on non-inferred parameter 'a'" in text), text
        assert ("'Pair[a, b]' cannot depend on non-inferred parameter 'b'" in text), text
        return
    raise AssertionError('a dependency on two non-inferred parameters compiled')


def test_satisfied_dependency_compiles():
    # The implicit parameter reads only a constant, so no non-inferred
    # parameter of this signature is depended on.
    _compile(_PRELUDE + 'struct NoDep[X: NeedsPair[1, 2, _]]:\n    pass\n')


def test_variadic_element_with_placeholder_is_refused():
    # A `_` in a variadic's element type makes it an inferred parameter, which
    # a variadic may not be. Printed with the callee's name for the slot.
    src = _PRELUDE + 'def variadic_deps[a: Int, b: Int, *Xs: NeedsPair[a, b, _]]():\n    pass\n'
    try:
        _compile(src)
    except RuntimeError as e:
        assert "element type parameter 'NeedsPair[a, b, p]' must be an 'inferred' parameter" in str(e), str(e)
        return
    raise AssertionError('a variadic with a placeholder element type compiled')


def test_variadic_element_naming_a_signature_parameter_is_refused():
    src = _PRELUDE + 'def v[T: AnyType, *Xs: T]():\n    pass\n'
    try:
        _compile(src)
    except RuntimeError as e:
        assert "element type parameter 'T' must be an 'inferred' parameter" in str(e), str(e)
        return
    raise AssertionError('a variadic whose element names a signature parameter compiled')


def test_variadic_element_without_dependency_compiles():
    _compile(_PRELUDE + 'def v[a: Int, *Xs: Int]():\n    pass\n'
                        'def w[*Xs: Pair[1, 2]]():\n    pass\n')


if __name__ == '__main__':
    test_repeated_dependency_is_refused()
    test_each_distinct_dependency_is_reported_once()
    test_satisfied_dependency_compiles()
    test_variadic_element_with_placeholder_is_refused()
    test_variadic_element_naming_a_signature_parameter_is_refused()
    test_variadic_element_without_dependency_compiles()
    print('ok')
