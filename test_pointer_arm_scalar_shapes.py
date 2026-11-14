"""Regression test: an int/bool return arm is refused in a pointer-annotated
function only when its SOURCE SHAPE is unambiguously scalar.

`5ccd8aa18` widened `_check_float_arm_into_annotated_pointer` to every
non-pointer scalar C type. The C type cannot tell a mistyped scalar from a
legitimate pointer value, so that made 83 stdlib files fail:

  * `return result^` returning a String is an erased `int64_t` box;
  * `return None` in a `-> Optional[String]` function is `int 0`;
  * a `-> Bool` method's comparison arm is a `_Bool` that matches its own
    scalar annotation.

The refusals below are the real bug the widening was for (`return 7` used to
hand the caller address 7). The accepted shapes are the ones its C-type test
misread.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def _compile(src: str) -> str:
    return compile_to_gimple(src, do_imports=False)


def _assert_refused(src: str, arm_ctype: str | None = None) -> None:
    try:
        _compile(src)
    except TypeError as e:
        msg = str(e)
    else:
        raise AssertionError(
            "a scalar return arm in a `-> String` function compiled; it must "
            "be refused (it used to hand the caller the raw bits as a pointer)")
    assert "'pick'" in msg, msg
    assert "'char *'" in msg, msg
    if arm_ctype is not None:
        assert f"'{arm_ctype}'" in msg, msg


def test_int_literal_return_into_an_annotated_pointer_is_refused():
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 7
""", "int")


def test_negative_int_literal_arm_is_refused():
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return -7
""", "int")


def test_bool_literal_arm_is_refused():
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return True
""")


def test_comparison_arm_is_refused():
    _assert_refused("""\
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return x == 2
""", "_Bool")


# ── the legitimate shapes the C-type reading misclassified ─────────────────

def test_a_string_value_arm_is_allowed():
    # `result^` is a String; its C type is the erased int64_t box.
    _compile("""\
def pick(x: Int) -> String:
    var result = String(x)
    return result^
""")


def test_a_none_arm_in_an_optional_return_is_allowed():
    # `-> Optional[String]` is a pointer; None is the null arm.
    _compile("""\
def pick(x: Int) -> Optional[String]:
    if x == 1:
        return "one"
    return None
""")


def test_a_bool_annotation_accepts_its_own_comparison_arm():
    # The annotation is itself a scalar (`Bool`), so `_Bool` is the value.
    _compile("""\
def pick(x: Int) -> Bool:
    return x == 1
""")


def test_a_scalar_annotation_accepts_its_own_int_literal():
    # `Codepoint` is a scalar alias; 65 is the value, not a mistyped pointer.
    _compile("""\
def pick(x: Int) -> Codepoint:
    return 65
""")


if __name__ == "__main__":
    test_int_literal_return_into_an_annotated_pointer_is_refused()
    test_negative_int_literal_arm_is_refused()
    test_bool_literal_arm_is_refused()
    test_comparison_arm_is_refused()
    test_a_string_value_arm_is_allowed()
    test_a_none_arm_in_an_optional_return_is_allowed()
    test_a_bool_annotation_accepts_its_own_comparison_arm()
    test_a_scalar_annotation_accepts_its_own_int_literal()
    print("PASS")
