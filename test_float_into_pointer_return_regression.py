"""Regression test: a float returned from a function whose inferred return
type is a POINTER must compile.

`comptime.py`'s `eval_const` returns bool/int/float/str/tuple from one
function, so its return-type join lands on `char *`. When `13b16397d` added
`if isinstance(node, FloatLiteral): return node.value`, that branch emitted a
bare `(char *)<double>`:

    mojo/middle/comptime.py:470:3: error: cannot convert to a pointer type

which took down `make mojoc`, `make stage2/mojo` and `test_selfhost.py`'s build.
The int/bool branches of the same function were already returning into the same
pointer slot and gcc accepts those with a warning, so only the float spelling
ever surfaced.

`_sce_simple_emit` now routes a float->pointer coercion through int64_t, like
every other scalar->pointer coercion in that file.
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
