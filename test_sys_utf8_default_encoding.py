"""Regression for PYTHON3.15_utf8_default_encoding (PEP 686).

UTF-8 is the default encoding. The compiler/runtime must report UTF-8 for
sys.getdefaultencoding() and sys.getfilesystemencoding(), and the gimple
backend must handle sys.getfilesystemencodeerrors() (it previously fell
through to uncompiled module dispatch and raised NotImplementedError).
"""
from test_gimple_runner import test_gimple_matches_cpython


def test_sys_encoding_functions_return_utf8_defaults():
    test_gimple_matches_cpython("sys_utf8_default_encoding", """\
import sys

print(sys.getdefaultencoding())
print(sys.getfilesystemencoding())
print(sys.getfilesystemencodeerrors())
""")


if __name__ == "__main__":
    test_sys_encoding_functions_return_utf8_defaults()
    print("ok")
