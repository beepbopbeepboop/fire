"""Regression pin for COMPILE_FAIL_Tools_gdb_libpython str-key subscript fix.
Before _cpp_refuse_str_key_subscript: a generator with d['k'] emitted
mojo_char_at_str((char *)(d), "k") — const char* where int64_t index
belongs, causing 10× g++ 'invalid conversion' errors in libpython.cpp.
After: honest refusal, no invalid C emitted.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_gimple import _force_cpp_coro, test_raises

def test_str_key_subscript_refused_not_emitted():
    with _force_cpp_coro():
        test_raises("str_key_subscript_refused_not_emitted", """\
def gen(d):
    yield d['k']

def main():
    for x in gen({}):
        print(x)
""", "Unsupported shape(s): gen: a str-keyed subscript")

if __name__ == "__main__":
    test_str_key_subscript_refused_not_emitted()
    print("PASS str_key_subscript_refused_not_emitted")
