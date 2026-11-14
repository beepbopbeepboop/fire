"""Regression test: `x[slice(a, b, c)]` must lower as a SLICE.

The parser folds `x[a:b]` into a SliceExpr, but `x[slice(a, b, c)]` has runtime
bounds and arrives as a call to the `slice` builtin. With no arm for it,
`_lower_subscript` fell through to the scalar-index path, which cast the slice
object to an integer and read ONE element.

Measured on the self-host closure: `mojo/middle/comptime.py`'s
`_eval_subscript` ends with `base[slice(start, stop, step)]` over a
comptime-known str/list, and the self-hosted compiler emitted

    _t125 = slice (start, stop, step);
    _t126 = (int64_t) _t125;
    _t127 = mojo_char_at_str_cp (base, _t126);

— a CHARACTER read where a slice was meant. `slice` was also an undefined
symbol at link time (declared in `module_gen`'s `_util_pairs`, never defined),
so `make bootstrap` could not link `stage2/mojo` at all.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple


def _compile(src: str) -> str:
    return compile_to_gimple(src, do_imports=False)


def test_str_slice_builtin_lowers_as_a_slice():
    src = """\
def f(s: String) -> String:
    return s[slice(1, 3)]
"""
    c = _compile(src)
    assert 'mojo_cstr_slice' in c, (
        "s[slice(1, 3)] was not lowered as a string slice")
    assert 'mojo_char_at_str_cp' not in c, (
        "s[slice(1, 3)] was lowered as a single-character read")


def test_list_slice_builtin_lowers_as_a_slice():
    src = """\
def g(xs: List[Int]) -> List[Int]:
    return xs[slice(None, -1)]
"""
    c = _compile(src)
    assert 'mojo_list_slice' in c, (
        "xs[slice(None, -1)] was not lowered as a list slice")


def test_slice_builtin_with_a_step():
    src = """\
def h(xs: List[Int]) -> List[Int]:
    return xs[slice(None, None, 2)]
"""
    c = _compile(src)
    # A step takes the extended runtime helper, not the step-less one.
    assert 'mojo_list_slice_step' in c, (
        "xs[slice(None, None, 2)] was not lowered as a stepped list slice")


def test_no_bare_slice_symbol_is_emitted():
    # The old path called the never-defined `slice(...)`; the subscript arm
    # builds a SliceExpr instead, so no such call can survive.
    src = """\
def f(s: String) -> String:
    return s[slice(0, 2)]
"""
    c = _compile(src)
    assert not re.search(r'= slice \(', c), (
        "a bare call to the undefined `slice` builtin was emitted")


if __name__ == "__main__":
    test_str_slice_builtin_lowers_as_a_slice()
    test_list_slice_builtin_lowers_as_a_slice()
    test_slice_builtin_with_a_step()
    test_no_bare_slice_symbol_is_emitted()
    print("PASS")
