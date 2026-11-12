#!/usr/bin/env python3
"""Regression test for the missing-module compile-time diagnostic.

Modular rejects an import that names no resolvable module at compile time
(`error: unable to locate module 'X'`).  Our compiler used to accept it
silently, because `_compile_imported_module` returned `(None, [])` for every
unresolved name and the caller just skipped it.  A module that is a real
Python module is still fine (the runtime provides it via importlib); a module
that is neither on the search path nor importable as Python is a genuine
missing module and must fail compilation.

Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md (category A,
imports).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=True, filename=filename)


def test_missing_module_import_fails():
    try:
        _compile('import does_not_exist\n\nfn main():\n    pass\n')
    except RuntimeError as e:
        assert 'unable to locate module' in str(e), e
        assert 'does_not_exist' in str(e), e
        return
    raise AssertionError('missing module import compiled without error')


def test_missing_module_from_import_fails():
    try:
        _compile('from no_such_pkg import thing\n\nfn main():\n    pass\n')
    except RuntimeError as e:
        assert 'unable to locate module' in str(e), e
        assert 'no_such_pkg' in str(e), e
        return
    raise AssertionError('missing from-import module compiled without error')


def test_missing_dotted_component_names_leaf():
    """`import a.b.c` reports the FIRST missing component, like modular:
    with `a` present, the missing leaf `c` is named."""
    _d = os.path.join(HERE, 'test_fixtures', 'imports')
    try:
        _compile('import imported_module.does_not_exist\n\nfn main():\n    pass\n',
                 filename=os.path.join(_d, 'main.mojo'))
    except RuntimeError as e:
        assert "unable to locate module 'does_not_exist'" in str(e), e
        return
    raise AssertionError('missing dotted module compiled without error')


def test_missing_root_component_names_root():
    """A wrong-case/unresolved ROOT is named, not the leaf
    (modular's mojo_import_case_sensitive_error.mojo:
    `from TEST_BINARY_PACKAGE.inner1.myfile import x` -> 'TEST_BINARY_PACKAGE')."""
    try:
        _compile('from TEST_BINARY_PACKAGE.inner1.myfile import print10\n\nfn main():\n    pass\n')
    except RuntimeError as e:
        assert "unable to locate module 'TEST_BINARY_PACKAGE'" in str(e), e
        return
    raise AssertionError('wrong-case root module compiled without error')


def test_python_module_import_passes():
    # A real Python module is provided by the runtime; not an error.
    _compile('import os\n\nfn main():\n    pass\n')


def test_user_sibling_module_import_passes():
    # A sibling .mojo module resolves on the search path.
    _compile('import mymod\n\nfn main():\n    pass\n',
             filename=os.path.join(HERE, 'test_fixtures', 'imports', 'main.mojo'))


def test_from_import_symbol_is_not_a_missing_module():
    """`from X import Y` where Y is a symbol in X (not a submodule) must not
    be reported as a missing module."""
    _compile('from test_helper import double, add\n\nfn main():\n    pass\n')


def test_future_import_passes():
    _compile('from __future__ import annotations\n\nfn main():\n    pass\n')


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
