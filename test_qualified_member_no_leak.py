#!/usr/bin/env python3
"""Regression test: a qualified access `mod.name` must resolve `name` only
against `mod`.

A sibling module (or an `__init__` re-export of the accessing file's own
package) is NOT a member of `mod`; resolving `other.shared_fn` /
`other.helpers` through the enclosing package is the deprecated intra-package
fallback modular rejects (import_qualified_member_no_leak.mojo).

Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md (category A,
imports).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

_PKG = os.path.join(HERE, 'test_fixtures', 'imports', 'qualified_member_leak')


def _compile(entry):
    src = open(entry).read()
    return compile_to_gimple(src, do_imports=True, filename=entry)


def test_reexport_member_is_not_a_member_of_other():
    entry = os.path.join(_PKG, 'consumer_reexport.mojo')
    try:
        _compile(entry)
    except RuntimeError as e:
        assert "module 'other' has no declaration 'shared_fn'" in str(e), e
        return
    raise AssertionError('other.shared_fn compiled without error')


def test_sibling_module_is_not_a_member_of_other():
    entry = os.path.join(_PKG, 'consumer_sibling.mojo')
    try:
        _compile(entry)
    except RuntimeError as e:
        assert "module 'other' has no declaration 'helpers'" in str(e), e
        return
    raise AssertionError('other.helpers compiled without error')


def test_real_member_of_other_still_works():
    # `other.other_fn` IS a member; a direct compile of a consumer that calls
    # it must not raise the missing-declaration error.
    entry = os.path.join(_PKG, 'other.mojo')
    _compile(entry)


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
