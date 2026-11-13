"""Regression test: a float returned from a function whose return type is an
ANNOTATED POINTER must still compile.

This is the shape that remains on the declared-pointer path: the annotation
fixes the C return type, so the float arm has to be coerced into it. When
`13b16397d` added `if isinstance(node, FloatLiteral): return node.value`, that
branch emitted a bare `(char *)<double>`:

    mojo/middle/comptime.py:470:3: error: cannot convert to a pointer type

`_sce_simple_emit` routes a float->pointer coercion through int64_t, like every
other scalar->pointer coercion in that file, so the compiles-but-truncates
spelling below still stands for an annotated return.

An INFERRED float-beside-pointer return no longer takes this path: it returns
the tagged word (`test_float_return_beside_tuple_return.py`, whose bug doc was
DELETED with its fix). The annotation-contradicted shape is written down in the
bugs/ queue as the follow-up to that fix.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def _compile(src: str) -> str:
    return compile_to_gimple(src, do_imports=False)


def test_float_return_into_a_pointer_typed_function_compiles():
    # The join of `char *` and `double` is `char *` (a pointer beats a
    # non-pointer), so the float return needs a coercion -- and a direct
    # `(char *)<double>` is invalid C.
    src = """\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 2.5
"""
    c = _compile(src)
    # The two-step: an int64_t temp holding the float, then the pointer cast.
    # `_t5 = (int64_t)2.5;  _t4 = (char *)_t5;`
    assert re.search(r'= \(int64_t\)2\.5;', c), (
        "the float->pointer return did not go through an int64_t temp")
    assert re.search(r'= \(char \*\)_t\d+;', c), (
        "the float->pointer return did not reach the pointer cast")


def test_int_return_into_the_same_shape_still_compiles():
    # The pre-existing spelling gcc accepts with a warning; the fix must not
    # have disturbed it.
    src = """\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 7
"""
    _compile(src)


if __name__ == "__main__":
    test_float_return_into_a_pointer_typed_function_compiles()
    test_int_return_into_the_same_shape_still_compiles()
    print("PASS")
