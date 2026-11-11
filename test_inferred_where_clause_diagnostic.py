#!/usr/bin/env python3
"""Regression test: a `where`-clause diagnostic inferred from an ERASED
argument type must not fire, while an explicit one still does.

`elaborate_generic_call_inferred` reads the type arguments off the call
arguments' C types. This codegen erases a lot of real Mojo types: every SIMD
value and every `Array`/`Span` element it did not track lowers to `int64_t`,
and an untracked byte element lowers to `char`; `c_to_mojo` reads those as
`Int`/`Int64`. Enforcing a `where dtype.is_floating_point()` clause on that
guess rejects valid calls — six stdlib files (`std/random/philox.mojo` and
`test/math/test_{erf,exp,ldexp,math,tanh}.mojo`) went from compiling to
`error: invalid call to 'tanh': violated constraint` that way.

The rule this pins: an INFERRED conformance failure is only surfaced when
every argument's C type really names its Mojo type. A caller that writes the
type arguments explicitly (`f[Int32](...)`) still gets the diagnostic.

Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import elaborate

_MOD = ('fn f[T: DType](x: T) -> Bool where T.is_floating_point():\n'
        '    return True\n')


def _inferred(ctype):
    return elaborate.Elaborator().elaborate_generic_call_inferred(
        _MOD, 'f', [ctype])


def test_erased_argument_types_decline():
    # No exception, and no instantiation: the caller falls through to its
    # nominal stub, exactly as when inference binds nothing at all.
    for ctype in ('int64_t', 'int', 'char', 'SomeStruct *'):
        assert _inferred(ctype) is None, ctype


def test_trusted_argument_type_still_diagnosed():
    try:
        _inferred('int32_t')
    except elaborate.ConformanceError:
        return
    raise AssertionError(
        "an inferred call whose argument type IS its Mojo type must keep the "
        "conformance diagnostic")


def test_explicit_type_argument_still_diagnosed():
    try:
        elaborate.Elaborator().elaborate_generic_call(_MOD, 'f', ['Int32'])
    except elaborate.ConformanceError:
        return
    raise AssertionError("an explicit violating type argument must be refused")


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
