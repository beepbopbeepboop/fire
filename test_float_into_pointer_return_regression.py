"""Regression test: a float returned from a function whose return type is an
ANNOTATED POINTER is a compile-time error, not a silent truncation.

The annotation fixes the C return type at a pointer (`char *`), and a float
arm cannot be returned as one. The old spelling coerced it through an
int64_t temp (`(char *)(int64_t)2.5`), compiled, and handed the caller the
truncated bits as the "string" -- `print(pick(0))` printed `1` where CPython
prints `1.5`. The annotation is authoritative, as in a static type system, so
the emitter now refuses the arm and names the function.

An INFERRED float-beside-pointer return is a different shape: it has no
annotation, widens to the tagged word, and is compared against CPython in
`test_float_return_beside_tuple_return.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def _compile(src: str) -> str:
    return compile_to_gimple(src, do_imports=False)


def test_float_return_into_an_annotated_pointer_is_refused():
    src = """\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 2.5
"""
    try:
        _compile(src)
    except TypeError as e:
        msg = str(e)
    else:
        raise AssertionError(
            "a float return arm in a `-> String` function compiled; it must "
            "be refused (it used to truncate to a pointer)")
    assert "'pick'" in msg, msg
    assert "'char *'" in msg, msg
    assert "'double'" in msg, msg


def _assert_refused(src: str, arm_ctype: str) -> None:
    try:
        _compile(src)
    except TypeError as e:
        msg = str(e)
    else:
        raise AssertionError(
            f"a {arm_ctype} return arm in a `-> String` function compiled; it "
            "must be refused (it used to hand the caller the raw bits as a "
            "pointer)")
    assert "'pick'" in msg, msg
    assert "'char *'" in msg, msg
    assert f"'{arm_ctype}'" in msg, msg


def test_int_return_into_an_annotated_pointer_is_refused():
    # gcc used to accept `return 7` here with a pointer-from-integer warning,
    # and print(pick(0)) dereferenced address 7 (CPython prints 7).
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 7
""", "int")


def test_bool_return_into_an_annotated_pointer_is_refused():
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return x == 2
""", "_Bool")


if __name__ == "__main__":
    test_float_return_into_an_annotated_pointer_is_refused()
    test_int_return_into_an_annotated_pointer_is_refused()
    test_bool_return_into_an_annotated_pointer_is_refused()
    print("PASS")
