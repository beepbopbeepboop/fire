#!/usr/bin/env python3
"""Regression test: importing the same name from two different modules into
one function scope is ambiguous.

Modular reports `error: import of 'X' is ambiguous` at the second import,
with notes naming where each module declares it
(import_fn_scope_ambiguous.mojo).

Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md (category A,
imports).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

_DIR = os.path.join(HERE, 'test_fixtures', 'imports')


def _compile(src):
    return compile_to_gimple(src, do_imports=True,
                            filename=os.path.join(_DIR, 'main.mojo'))


def test_ambiguous_value_import_fails():
    try:
        _compile('def f():\n'
                 '    from wildcard_shadow_a import shadowed_value\n'
                 '    from wildcard_shadow_b import shadowed_value\n'
                 '    _ = shadowed_value\n')
    except RuntimeError as e:
        assert "error: import of 'shadowed_value' is ambiguous" in str(e), e
        assert "note: 'shadowed_value' declared here" in str(e), e
        assert "note: 'shadowed_value' also declared here" in str(e), e
        return
    raise AssertionError('ambiguous value import compiled without error')


def test_ambiguous_fn_import_fails():
    try:
        _compile('def f():\n'
                 '    from wildcard_shadow_a import shadowed_fn\n'
                 '    from wildcard_shadow_b import shadowed_fn\n'
                 '    _ = shadowed_fn()\n')
    except RuntimeError as e:
        assert "error: import of 'shadowed_fn' is ambiguous" in str(e), e
        return
    raise AssertionError('ambiguous fn import compiled without error')


def test_unbound_reference_to_ambiguous_scoped_fn_fails():
    # Two function bodies each import a same-named fn from a DIFFERENT
    # sibling. g() has no enclosing `from ... import shadowed_fn`, so
    # neither copy is selected. It must be refused, not silently resolved to
    # whichever sibling was registered last (the silent miscompile this test
    # pins: the fall-through to the shared registry).
    try:
        _compile('def call_a() raises -> Int64:\n'
                 '    from wildcard_shadow_a import shadowed_fn\n'
                 '    return shadowed_fn()\n'
                 '\n'
                 'def call_b() raises -> Int64:\n'
                 '    from wildcard_shadow_b import shadowed_fn\n'
                 '    return shadowed_fn()\n'
                 '\n'
                 'def g() raises -> Int64:\n'
                 '    return shadowed_fn()\n')
    except RuntimeError as e:
        assert "error: import of 'shadowed_fn' is ambiguous" in str(e), e
        return
    raise AssertionError('unbound reference to an ambiguous sibling fn '
                         'compiled without error')


def test_unbound_reference_to_transitive_sibling_fn_fails():
    # A transitive import (ambiguous_mid imports wildcard_shadow_a's
    # shadowed_fn at module scope) plus ONE function-local import of the
    # same bare name from a different sibling. g() has no binding in its
    # own scope: neither import is lexically visible there, so the
    # reference must be refused. Before the fix a function-body import was
    # also written into the flat own map, so g() silently compiled to
    # wildcard_shadow_b (the leak out of call_b's scope).
    try:
        _compile('from ambiguous_mid import relay_fn\n'
                 '\n'
                 'def call_b() raises -> Int64:\n'
                 '    from wildcard_shadow_b import shadowed_fn\n'
                 '    return shadowed_fn()\n'
                 '\n'
                 'def g() raises -> Int64:\n'
                 '    return shadowed_fn()\n')
    except RuntimeError as e:
        assert "error: import of 'shadowed_fn' is ambiguous" in str(e), e
        return
    raise AssertionError('unbound reference to a transitively imported '
                         'sibling fn compiled without error')


def test_unbound_reference_before_conflicting_body_import_fails():
    # Same program, but the unbound reference is emitted BEFORE the
    # function whose body imports the other sibling. The refusal must not
    # depend on source order: the whole-module pre-scan is what knows the
    # other module's binding already exists.
    try:
        _compile('from ambiguous_mid import relay_fn\n'
                 '\n'
                 'def g() raises -> Int64:\n'
                 '    return shadowed_fn()\n'
                 '\n'
                 'def call_b() raises -> Int64:\n'
                 '    from wildcard_shadow_b import shadowed_fn\n'
                 '    return shadowed_fn()\n')
    except RuntimeError as e:
        assert "error: import of 'shadowed_fn' is ambiguous" in str(e), e
        return
    raise AssertionError('unbound reference before a conflicting body import '
                         'compiled without error')


def test_lifted_closure_sees_enclosing_function_import():
    # The valid counterpart of the leak closed above: a nested def IS
    # lexically inside the enclosing body, so the enclosing body's import
    # must still resolve there (closures are emitted before the enclosing
    # body compiles). It must resolve to wildcard_shadow_a, never to the
    # unrelated sibling a different function imports.
    code = _compile('def other() raises -> Int64:\n'
                    '    from wildcard_shadow_b import shadowed_fn\n'
                    '    return shadowed_fn()\n'
                    '\n'
                    'def outer() raises -> Int64:\n'
                    '    from wildcard_shadow_a import shadowed_fn\n'
                    '    def inner() -> Int64:\n'
                    '        return shadowed_fn()\n'
                    '    return inner()\n')
    # Locate the lifted closure's own definition (`outer_inner`) and check
    # the symbol its body actually calls. Both sibling symbols are declared
    # in the translation unit (each module's own definition), so the whole
    # text cannot distinguish them; the closure's body can.
    _start = code.find('__GIMPLE int64_t outer_inner')
    assert _start >= 0, code
    _block = code[_start:_start + 2000]
    assert 'wildcard_shadow_a_shadowed_fn ()' in _block, _block
    assert 'wildcard_shadow_b_shadowed_fn ()' not in _block, _block


def test_scoped_imports_of_ambiguous_fn_each_resolve():
    # The same two siblings, but every reference sits under its own
    # enclosing `from ... import`: each must compile.
    _compile('def call_a() raises -> Int64:\n'
             '    from wildcard_shadow_a import shadowed_fn\n'
             '    return shadowed_fn()\n'
             '\n'
             'def call_b() raises -> Int64:\n'
             '    from wildcard_shadow_b import shadowed_fn\n'
             '    return shadowed_fn()\n')


def test_same_module_import_is_not_ambiguous():
    # Re-importing the same name from the SAME module is a harmless shadow.
    _compile('def f():\n'
             '    from wildcard_shadow_a import shadowed_fn\n'
             '    from wildcard_shadow_a import shadowed_fn\n'
             '    _ = shadowed_fn()\n')


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
