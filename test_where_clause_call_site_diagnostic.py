#!/usr/bin/env python3
"""Regression test: a generic call whose `where` clause is provably false for
the supplied type arguments must fail to compile.

`check_bounds` already knew how to evaluate `where T.is_floating_point()` /
`is_integral()`; the gap was that the in-TU pre-pass materialized the
instantiation without checking, so `_elaborate_generic_call` declined (its
name was in `_intu_func_args`) and the `.o` route's own check was bypassed.

Plan: docs/diagnostics-missing-validation-plan.md §1.
Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md (category A,
constraints).
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

_SRC = ('fn f[T: DType](x: T) -> Bool where T.is_floating_point():\n'
        '    return True\n')


def _compile(src):
    # The elaborator reads the file at `filename`, so the source must live in
    # a real file for the generic template to be found.
    d = tempfile.mkdtemp(prefix='where_clause_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    return compile_to_gimple(src, do_imports=True, filename=p)


def test_violated_where_clause_fails():
    try:
        _compile(_SRC + '\nfn main():\n    print(f[DType.int32](1))\n')
    except RuntimeError as e:
        assert "error: invalid call to 'f': violated constraint" in str(e), e
        return
    raise AssertionError('violated where clause compiled without error')


def test_satisfied_where_clause_passes():
    _compile(_SRC + '\nfn main():\n    print(f[DType.float32](1.0))\n')


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
