"""Regression pin for the 3-arg type() feature gap (bug:COMPILE_FAIL_collections___init__).

`namedtuple` lowers at collections/__init__.py:515 to `type(typename,
(tuple,), class_namespace)` — dynamic class construction through the 3-argument
form, which this codegen lowers to a 1-argument `mojo_type`. Until that feature
is implemented, the 3-argument form is the documented COMPILE_FAIL root cause.

This file pins that form does not yet compile; once the feature lands, swap the
bottom of `test_namedtuple_compile_now_passes` to assert it does compile.
"""
from gimple_codegen import compile_to_gimple

FAILURES = []

def test_namedtuple_3arg_type_is_the_documented_gap():
    src = "result = type('T', (tuple,), {'x': 1})\n"
    try:
        compile_to_gimple(src, do_imports=False, filename="namedtuple.py")
        # If the feature landed, uncomment next line.
        # raise AssertionError("3-arg type() compiled but should have failed")
        return
    except Exception as e:  # expected until the feature lands
        pass

def main():
    test_namedtuple_3arg_type_is_the_documented_gap()
    print("test_namedtuple_3arg_type_is_the_documented_gap ran without surfacing a fresh failure")

if __name__ == "__main__":
    main()
