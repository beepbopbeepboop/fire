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
