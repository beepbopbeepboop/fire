#!/usr/bin/env python3
"""Regression: a BARE STATEMENT call to a generic function with inferred
parameters (`invalid(Foo())`, no brackets) is instantiated like the same call
in value position. The statement fast path in emit_stmts never reached
`_lower_call`'s generic arm, so the call became a plain extern against a weak
"unavailable in compiled mode" stub: the program built, and a call whose
instantiation the elaborator rejects built clean.

Also covers the inference the call needs: `x: T` bound from a `Foo()`
argument, whose C type `Foo *` alone cannot name its Mojo type.
Pure codegen (no gcc)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimple_codegen  # noqa: E402

FOO = '''@fieldwise_init
struct Foo(ImplicitlyCopyable):
    pass


'''


def compile_src(src, name='m.mojo'):
    return gimple_codegen.compile_to_gimple(src, do_imports=False, filename=name)


def test_statement_call_is_instantiated():
    c = compile_src(FOO + '''def keep[T: ImplicitlyCopyable & Deinitable](x: T):
    print("kept")


def main():
    keep(Foo())
''')
    assert 'keep_1_T_3_Foo (' in c, 'the call is not the Foo instantiation'
    assert 'keep (' not in c.replace('keep_1_T_3_Foo', ''), 'bare extern `keep` left'


def test_value_and_statement_forms_agree():
    c = compile_src(FOO + '''def ident[T: ImplicitlyCopyable & Deinitable](x: T) -> T:
    return x


def side[T: ImplicitlyCopyable & Deinitable](x: T):
    print("s")


def main():
    _ = ident(Foo())
    side(Foo())
''')
    assert 'ident_1_T_3_Foo' in c and 'side_1_T_3_Foo' in c


def test_rejected_instantiation_is_reported_for_a_statement_call():
    src = FOO + '''def print_it[T: Writable & Deinitable](var x: T):
    print(x)


def invalid[T: ImplicitlyCopyable & Deinitable](x: T):
    print_it(rebind[downcast[T, Writable]](x))


def main():
    invalid(Foo())
'''
    try:
        compile_src(src, 'invalid_downcast_error.mojo')
    except RuntimeError as e:
        msg = str(e)
        assert 'error: function instantiation failed' in msg, msg
        assert ("struct 'invalid_downcast_error::Foo' does not have witness "
                "table for trait 'std::format::__init__::Writable'") in msg, msg
    else:
        raise AssertionError('the invalid downcast built clean')


def test_local_shadow_is_an_ordinary_call():
    c = compile_src('''def keep[T: ImplicitlyCopyable & Deinitable](x: T):
    print("kept")


def main():
    var keep = 1
    print(keep)
''')
    assert 'keep_1_T' not in c


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
