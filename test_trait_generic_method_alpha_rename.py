#!/usr/bin/env python3
"""A method's own bracket parameters are local names, not part of its signature.

`trait T: def f[X: AnyType](self, v: X) -> X` and
`struct S(T): def f[Y: AnyType](self, v: Y) -> Y` declare the same requirement
and the same implementation, so `elaborate.check_conformance` must accept S
for T. It did not: signatures are compared textually, so the differently
spelled parameter read as "signature mismatch (want ... X)".

That false positive is what turned `stdlib-syntax` red on the trait-conformance
part-6 branch: `std/utils/variant.mojo`'s `_NicheStorage.as_uninit[T]` is
implemented by `_DefaultNicheStorage.as_uninit[U]`, and the declaration-time
requirement check reported "'_DefaultNicheStorage' does not implement all
requirements for '_NicheStorage'". `_method_sig` now alpha-renames a method's
own bracket parameters (`_m0`, `_m1`, ...) before the comparison; `Self.T` is
the struct's parameter and is deliberately not renamed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as N
import elaborate


VARIANT_SHAPE = (
    'trait _NicheStorage:\n'
    '    def as_uninit[T: AnyType](ref self) -> '
    'Pointer[MaybeUninit[T], origin_of(self)]:\n'
    '        ...\n'
    '\n'
    'struct _DefaultNicheStorage[T: AnyType](_NicheStorage):\n'
    '    def as_uninit[U: AnyType](ref self) -> '
    'Pointer[MaybeUninit[U], origin_of(self)]:\n'
    '        ...\n'
)


def test_alpha_renamed_required_method_conforms():
    ok, missing = elaborate.check_conformance(
        VARIANT_SHAPE, '_DefaultNicheStorage', '_NicheStorage')
    assert ok, f'alpha-equivalent generic method rejected: {missing}'


def test_mismatched_return_is_still_rejected():
    src = (
        'trait Needs[T: AnyType]:\n'
        '    def f[U: AnyType](ref self) -> U:\n'
        '        ...\n'
        '\n'
        'struct Wrong[T: AnyType](Needs):\n'
        '    def f[V: AnyType](ref self) -> Int:\n'
        '        ...\n'
    )
    ok, missing = elaborate.check_conformance(src, 'Wrong', 'Needs')
    assert not ok, 'a genuinely different signature must still be rejected'
    assert any('signature mismatch' in m for m in missing), missing


def test_self_member_keeps_the_struct_parameter():
    src = (
        'trait HasSelf:\n'
        '    def mix[T: AnyType](self, v: T) -> Self.T:\n'
        '        ...\n'
    )
    mod = N.Parser(N.py_tokenize(src)).parse_module()
    trait = [s for s in mod if isinstance(s, N.TraitDef)][0]
    name, ptypes, ret = elaborate._method_sig(trait.methods[0])
    assert name == 'mix'
    # The method's own `T` is local, so the parameter is canonicalised ...
    assert ptypes == ['_m0'], ptypes
    # ... while `Self.T` is the struct's parameter, which must survive as-is.
    assert ret == 'Self.T', ret


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items())
             if k.startswith('test_') and callable(v)]
    for fn in tests:
        try:
            fn()
            print('ok', fn.__name__)
        except Exception as e:
            import traceback
            print('FAIL', fn.__name__, e)
            traceback.print_exc()
            sys.exit(1)
    print('all tests passed')
