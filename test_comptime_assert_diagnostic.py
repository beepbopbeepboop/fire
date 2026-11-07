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


def test_comptime_assert_short_circuit_and_false():
    # Short-circuit: `False and <unknown>` is provably false even when the
    # right operand cannot be folded (generic/comptime-param dependent).
    # bugs/DIAGNOSTICS_missing_validation_modular.md: missing diagnostic when
    # comptime bool folding required both operands to be known.
    try:
        _compile('fn f[x: Int]():\n    comptime assert False and x > 0, "nope"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'nope' in s, s
        return
    raise AssertionError('provably-false short-circuit and compiled without error')


def test_comptime_assert_short_circuit_or_unknown_not_false():
    # `True or <unknown>` is provably true: must NOT fail compilation.
    _compile('fn f[x: Int]():\n    comptime assert True or x < 0, "ok"\n')


def test_comptime_assert_short_circuit_and_true_needs_rhs():
    # `True and <unknown>` depends on rhs; must not produce a false diagnostic.
    _compile('fn f[x: Int]():\n    comptime assert True and x > 0, "ok"\n')


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


def test_comptime_assert_in_comptime_for_range():
    # comptime for unrolls at compile time; the induction variable must be
    # visible to comptime assertion evaluation so a provably-false condition in
    # any iteration is diagnosed (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime for i in range(3):\n        comptime assert i < 2, "bad"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'bad' in s, s
        return
    raise AssertionError('comptime assert in comptime for (false iteration) compiled')


def test_comptime_assert_in_comptime_for_range_true():
    _compile('fn f():\n    comptime for i in range(3):\n        comptime assert i < 3, "ok"\n')


def test_comptime_assert_in_comptime_for_product():
    # product() unrolling must also bind loop targets for comptime evaluation.
    src = (
        'from itertools import product\n'
        'fn f():\n'
        '    comptime for i, j in product(range(2), range(2)):\n'
        '        comptime assert i + j < 2, "sum"\n'
    )
    try:
        _compile(src)
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'sum' in s, s
        return
    raise AssertionError('comptime assert in comptime for product compiled')


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


def test_comptime_assert_in_comptime_for_list_literal():
    # comptime for over a constant list literal must unroll and bind the loop
    # variable so comptime assertions see the per-iteration value
    # (bugs/DIAGNOSTICS_missing_validation_modular.md: "comptime-for shapes
    # beyond the gimple unroller's bound forms").
    try:
        _compile('fn f():\n    comptime for i in [0, 1, 2]:\n        comptime assert i < 2, "bad"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'bad' in s, s
        return
    raise AssertionError('comptime assert in comptime for over list literal compiled')


def test_comptime_assert_in_comptime_for_tuple_literal():
    try:
        _compile('fn f():\n    comptime for i in (0, 1, 2):\n        comptime assert i != 2, "hit"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'hit' in s, s
        return
    raise AssertionError('comptime assert in comptime for over tuple literal compiled')


def test_comptime_assert_in_comptime_for_list_literal_true():
    _compile('fn f():\n    comptime for i in [0, 1, 2]:\n        comptime assert i < 3, "ok"\n')


def test_comptime_assert_in_comptime_for_tuple_unpack():
    # tuple-unpacking targets over constant collections must bind each target
    # so comptime diagnostics see per-iteration values
    # (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime for i, j in [(0, 1), (2, 0)]:\n        comptime assert i + j < 2, "sum"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'sum' in s, s
        return
    raise AssertionError('comptime assert in comptime for tuple unpack compiled')


def test_comptime_assert_in_comptime_for_tuple_unpack_true():
    _compile('fn f():\n    comptime for i, j in [(0, 1), (1, 2)]:\n        comptime assert i < j, "ok"\n')


def test_comptime_assert_in_comptime_for_comptime_alias():
    # Iterating over a comptime (non-literal) iterable alias must unroll with
    # the loop variable bound so comptime diagnostics fire
    # (bugs/DIAGNOSTICS_missing_validation_modular.md: "iteration over
    # non-literal comptime values").
    src = 'fn f():\n    comptime vals = [0, 1, 2]\n    comptime for i in vals:\n        comptime assert i < 2, "bad"\n'
    try:
        _compile(src)
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'bad' in s, s
        return
    raise AssertionError('comptime assert in comptime for over comptime alias compiled')


def test_comptime_assert_in_comptime_for_comptime_alias_true():
    _compile('fn f():\n    comptime vals = [0, 1, 2]\n    comptime for i in vals:\n        comptime assert i < 3, "ok"\n')


def test_comptime_assert_in_comptime_for_comptime_alias_tuple_unpack():
    src = (
        'fn f():\n'
        '    comptime pairs = [(0, 1), (2, 0)]\n'
        '    comptime for i, j in pairs:\n'
        '        comptime assert i + j < 2, "sum"\n'
    )
    try:
        _compile(src)
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'sum' in s, s
        return
    raise AssertionError('comptime assert in comptime for over comptime alias unpack compiled')


def test_comptime_assert_in_comptime_for_range_comptime_bound():
    # Range bounds from comptime-bound identifiers must unroll so comptime
    # validation sees the loop variable (DIAGNOSTICS_missing_validation_modular).
    try:
        _compile(
            'fn f():\n'
            '    comptime n = 3\n'
            '    comptime for i in range(n):\n'
            '        comptime assert i < 2, "nope"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'nope' in s, s
        return
    raise AssertionError('comptime assert in comptime for range(comptime var) compiled')


def test_comptime_assert_in_comptime_for_range_comptime_bound_true():
    _compile(
        'fn f():\n'
        '    comptime n = 3\n'
        '    comptime for i in range(n):\n'
        '        comptime assert i < 3, "ok"\n')


def test_comptime_assert_len_comptime_list_fails():
    # `len()` folds on comptime-known collections (DIAGNOSTICS_missing_validation_modular).
    try:
        _compile(
            'fn f():\n'
            '    comptime a = [1, 2, 3]\n'
            '    comptime assert len(a) == 2, "bad len"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'bad len' in s, s
        return
    raise AssertionError('comptime assert len(comptime list) == wrong compiled')


def test_comptime_assert_len_comptime_list_true():
    _compile(
        'fn f():\n'
        '    comptime a = [1, 2, 3]\n'
        '    comptime assert len(a) == 3, "ok"\n')


def test_comptime_assert_in_comptime_for_range_len_fails():
    # `range(len(a))` bounds must fold when `a` is comptime-known so the
    # comptime-for unroller can validate the body.
    try:
        _compile(
            'fn f():\n'
            '    comptime a = [1, 2, 3]\n'
            '    comptime for i in range(len(a)):\n'
            '        comptime assert i < 2, "nope"\n')
    except RuntimeError as e:
        s = str(e)
        assert 'comptime assertion failed' in s, s
        assert 'nope' in s, s
        return
    raise AssertionError('comptime assert in comptime for range(len(a)) compiled')


def test_comptime_assert_in_comptime_for_range_len_true():
    _compile(
        'fn f():\n'
        '    comptime a = [1, 2, 3]\n'
        '    comptime for i in range(len(a)):\n'
        '        comptime assert i < 3, "ok"\n')


if __name__ == '__main__':
    test_comptime_assert_false_fails()
    test_comptime_assert_false_no_msg()
    test_comptime_assert_true_passes()
    test_comptime_assert_comparison_fails()
    test_comptime_assert_message_string_concat_and_string_int()
    test_comptime_assert_message_tstring()
    test_comptime_assert_message_tstring_expr()
    test_comptime_assert_message_fstring()
    test_comptime_assert_short_circuit_and_false()
    test_comptime_assert_short_circuit_or_unknown_not_false()
    test_comptime_assert_short_circuit_and_true_needs_rhs()
    test_comptime_assert_in_comptime_for_range()
    test_comptime_assert_in_comptime_for_range_true()
    test_comptime_assert_in_comptime_for_product()
    test_comptime_assert_message_tstring_generic_param()
    test_comptime_assert_in_comptime_for_list_literal()
    test_comptime_assert_in_comptime_for_tuple_literal()
    test_comptime_assert_in_comptime_for_list_literal_true()
    test_comptime_assert_in_comptime_for_tuple_unpack()
    test_comptime_assert_in_comptime_for_tuple_unpack_true()
    test_comptime_assert_in_comptime_for_comptime_alias()
    test_comptime_assert_in_comptime_for_comptime_alias_true()
    test_comptime_assert_in_comptime_for_comptime_alias_tuple_unpack()
    test_comptime_assert_in_comptime_for_range_comptime_bound()
    test_comptime_assert_in_comptime_for_range_comptime_bound_true()
    test_comptime_assert_len_comptime_list_fails()
    test_comptime_assert_len_comptime_list_true()
    test_comptime_assert_in_comptime_for_range_len_fails()
    test_comptime_assert_in_comptime_for_range_len_true()
    print('ok')
