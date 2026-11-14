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
import elaborate

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


def test_dot_relative_dtype_satisfies_a_dtype_where_clause():
    """`.float32`, `DType.float32` and `Float32` are ONE dtype, so a where
    clause over it must answer the same for every spelling.

    Monomorphization substitutes the call site's bracket argument TEXTUALLY, so
    the where-clause checker (which only has `{param: rendered_text}`) sees
    whatever spelling the callee was written with. It used to recognize only
    `Float32`/`DType.float32`, so `.float32` fell to the conservative
    "not a float" answer and the call was rejected:
    "type '.float32' does not satisfy constraint 'T.is_floating_point()'".
    That is the red `stdlib-syntax` carried on the held nested-bracket-call
    branch: test/builtin/test_simd.mojo, test/math/test_exp.mojo and
    test/math/test_math.mojo all instantiate a `dtype: DType` generic with a
    dot-relative dtype. The dot spelling is the same text
    `_type_expr_to_ann` renders for a DottedLiteral bracket argument."""
    elaborate.check_where_clauses('', _SRC, {'T': '.float32'})
    elaborate.check_where_clauses('', _SRC, {'T': 'DType.float32'})
    elaborate.check_where_clauses('', _SRC, {'T': 'Float32'})
    # The predicate must still say NO for a dtype that is not floating: a
    # recognizer that accepted every dot spelling would pass the cases above
    # and also this one, silently.
    try:
        elaborate.check_where_clauses('', _SRC, {'T': '.int8'})
    except elaborate.ConformanceError:
        pass
    else:
        raise AssertionError(
            "'.int8' satisfied a 'T.is_floating_point()' where clause")


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
