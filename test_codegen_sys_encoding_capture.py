"""Regression for CODEGEN_function_values_assigned_in_branches_then_returned_
assignment_to_int_from_char_ptr.

`encoding = sys.getfilesystemencoding()` was typed `int` by the closure
discovery pre-pass (`_quick_type`'s generic `sys.*` row), so a nested `def`
capturing it got an `int encoding` env field: the pointer was truncated, and
beside a branch assigning the real `char *` gcc rejected the program."""
from test_gimple_runner import test_gimple_matches_cpython


def test_sys_encoding_captured_by_nested_def():
    test_gimple_matches_cpython("sys_encoding_capture_simple", """\
import sys

def make():
    encoding = sys.getfilesystemencoding()
    def encode(value):
        return value + '/' + encoding
    return encode

print(make()("a"))

""")


def test_function_values_assigned_in_branches_then_returned():
    test_gimple_matches_cpython("sys_encoding_capture_branches", """\
import sys

def make(is_win):
    if is_win:
        def check_str(value):
            if not isinstance(value, str):
                raise TypeError("str expected")
            return value
        encode = check_str
        decode = str
        def encodekey(key):
            return encode(key).upper()
    else:
        encoding = sys.getfilesystemencoding()
        def encode(value):
            if not isinstance(value, str):
                raise TypeError("str expected")
            return value + '/' + encoding
        def decode(value):
            return value.upper() + encoding
        encodekey = encode
    return encode, decode, encodekey

e, d, k = make(False)
print(e("a"), d("b"), k("c"))
""")


if __name__ == '__main__':
    test_sys_encoding_captured_by_nested_def()
    test_function_values_assigned_in_branches_then_returned()
    print('ok')
