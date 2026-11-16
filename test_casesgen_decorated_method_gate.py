#!/usr/bin/env python3
"""Pin: the decorated-method wrapper pass skips `@decorator(args)` decorators.

The compiled `Tools/cases_generator` analyzer carries `@always_inline("builtin")`
on struct methods (bool.mojo line 123 shape). Today's parser represents
`@deco(args)` as a CallExpr, not a name, and `_as_str` is identity, so the
bare-name regex gate in `module_gen._populate_decorated_method_wrapped` was
handed a node and raised `TypeError: expected string or bytes-like object`
("got 'CallExpr'"). Every stdlib module degraded in the dylib build, which is
what emptied the analyzer's dylib.

This pin calls the pass directly (unit-level, no compile) on the two decorator
shapes it must tell apart:

  (a) `@tagged("builtin")` on `Decorated.read` — a CallExpr decorator. The pass
      must skip it without raising, and must not install a wrapper.
  (b) `@contextual` on `Second.compute`, a bare-name decorator whose return
      type is `int64_t` — the pass must install the `_wrapped_Second_compute`
      getter and the `_getattr` arm.
  (c) `@contextual` with a NON-scalar return type — no word spelling exists for
      `mojo_maybe_bound_call_N`, so no wrapper is installed (the historical
      raw behavior).

On master the pass does not exist (it landed with the compiled-path fixes for
bugs/LAND-compile-fail-tools-cases-generator-a.md); this test fails there and
passes here. It is the unit-level companion to
test_casesgen_analyzer_p3p2_regressions.py's `Decorated.read` section, which
drives the same gate through a full `fire.py build` + CPython comparison.

Run: `python3 test_casesgen_decorated_method_gate.py`
"""
import sys

sys.path.insert(0, '.')

from fire_compiler import py_tokenize, Parser
from gimple_codegen import GimpleGen
from mojo.backend_gimple import module_gen

SRC = '''
def tagged(label):
    def wrap(fn):
        return fn
    return wrap

def contextual(fn):
    return fn

class Decorated:
    def __init__(self):
        self.value = 7

    @tagged("builtin")
    def read(self):
        return self.value

class Second:
    @contextual
    def compute(self):
        return 3

class Third:
    @contextual
    def boxed(self):
        return 4
'''


def _gen_with_return(ret):
    gen = GimpleGen(do_imports=False)
    gen.func_return_types['contextual'] = ret
    stmts = Parser(py_tokenize(SRC)).parse_module()
    return gen, stmts


def test_call_expr_decorator_is_skipped():
    """The CallExpr decorator must not raise, and must install no wrapper."""
    gen, stmts = _gen_with_return('int64_t')
    module_gen._populate_decorated_method_wrapped(gen, stmts, [])
    assert ('Decorated', 'read') not in gen._decorated_method_wrapped, (
        'a CallExpr decorator must not install a wrapper: %r' % (gen._decorated_method_wrapped,))
    print('ok   @deco(args) on a struct method is skipped')


def test_bare_name_scalar_decorator_installs_wrapper():
    """A bare-name decorator with scalar word return IS wrapped."""
    gen, stmts = _gen_with_return('int64_t')
    module_gen._populate_decorated_method_wrapped(gen, stmts, [])
    assert (gen._decorated_method_wrapped.get(('Second', 'compute'))
            == '_wrapped_Second_compute'), (
        'expected a wrapper for (Second, compute): %r' % (gen._decorated_method_wrapped,))
    assert gen._getattr_decorated_arms['Second']['compute'] == '_wrapped_Second_compute'
    assert gen._decorated_method_dec_csym[('Second', 'compute')] == 'contextual'
    print('ok   @contextual with int64_t return installs the wrapper')


def test_bare_name_non_scalar_decorator_is_not_wrapped():
    """A non-scalar word hides the word spelling; the pass skips it."""
    gen, stmts = _gen_with_return('MojoList *')
    module_gen._populate_decorated_method_wrapped(gen, stmts, [])
    assert ('Second', 'compute') not in gen._decorated_method_wrapped, (
        'a by-value struct return must keep the raw behavior: %r' % (gen._decorated_method_wrapped,))
    assert ('Third', 'boxed') not in gen._decorated_method_wrapped, (
        'a by-value struct return must keep the raw behavior: %r' % (gen._decorated_method_wrapped,))
    print('ok   @contextual with non-scalar return installs no wrapper')


if __name__ == '__main__':
    test_call_expr_decorator_is_skipped()
    test_bare_name_scalar_decorator_installs_wrapper()
    test_bare_name_non_scalar_decorator_is_not_wrapped()
    print('all tests passed')
