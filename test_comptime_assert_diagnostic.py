#!/usr/bin/env python3
"""Regression test for comptime assert compile-time diagnostics.

`bugs/DIAGNOSTICS_missing_validation_modular.md`: the compiler accepted
`comptime assert` statements whose conditions are provably false at compile
time.  A `comptime assert` is a compile-time check; a provably-false
condition must fail compilation with a diagnostic, not be silently accepted
(or lowered to a runtime trap).
"""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_comptime_assert_false_fails():
    try:
        _compile('fn f():\n    comptime assert False, "nope"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_false_no_msg():
    try:
        _compile('fn f():\n    comptime assert False\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_true_passes():
    _compile('fn f():\n    comptime assert True, "ok"\n    pass\n')


def test_comptime_assert_comparison_fails():
    try:
        _compile('fn f():\n    comptime assert 1 == 2, "math"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'math' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_message_string_concat_and_string_int():
    # Comptime diagnostic messages must be evaluated: String(int) and +
    # concatenation fold so the message is human-readable, not a temp name.
    try:
        _compile('fn f():\n    comptime x = 42\n    comptime assert False, "got " + String(x)\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'got 42' in s, s
        assert '_t' not in s.split('comptime assertion failed:')[-1], s
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_message_tstring():
    # t-string (template string) messages must be evaluated in comptime
    # diagnostics (bugs/DIAGNOSTICS_missing_validation_modular.md: t"..."
    # reflection-driven messages).
    try:
        _compile('fn f():\n    comptime x = 5\n    comptime assert False, t"value is {x}"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'value is 5' in s, s
        assert '{x}' not in s, s
        return
    raise AssertionError('provably-false comptime assert with t-string compiled')


def test_comptime_assert_message_tstring_expr():
    try:
        _compile('fn f():\n    comptime assert 1 == 2, t"math {1 + 1}"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'math 2' in s, s
        return
    raise AssertionError('provably-false comptime assert with t-string expr compiled')


def test_comptime_assert_message_fstring():
    try:
        _compile('fn f():\n    comptime x = 9\n    comptime assert False, f"n={x}"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'n=9' in s, s
        return
    raise AssertionError('provably-false comptime assert with f-string compiled')


def _compile_full(src):
    import os
    import tempfile
    tmpdir = os.environ.get('TMPDIR', '.tmp')
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.mojo', dir=tmpdir,
                                     delete=False, mode='w') as f:
        f.write(src)
        fn = f.name
    try:
        return compile_to_gimple(src, do_imports=True, filename=fn)
    finally:
        try:
            os.unlink(fn)
        except OSError:
            pass


def test_comptime_assert_message_tstring_generic_param():
    # Modular shape: t-string message referencing an instantiated generic param.
    src = '''
def use_positive_int[x: Int]():
    comptime assert x > 0, t"expected positive number, got {x}"

def main():
    use_positive_int[-3]()
'''
    try:
        _compile_full(src)
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'expected positive number, got -3' in s, s
        return
    raise AssertionError('instantiated generic comptime assert t-string compiled')


if __name__ == '__main__':
    test_comptime_assert_false_fails()
    test_comptime_assert_false_no_msg()
    test_comptime_assert_true_passes()
    test_comptime_assert_comparison_fails()
    test_comptime_assert_message_string_concat_and_string_int()
    test_comptime_assert_message_tstring()
    test_comptime_assert_message_tstring_expr()
    test_comptime_assert_message_fstring()
    test_comptime_assert_message_tstring_generic_param()
    print('ok')
