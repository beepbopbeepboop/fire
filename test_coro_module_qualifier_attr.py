#!/usr/bin/env python3
"""Regression: mojo.middle.coro must expose module_qualifier as module attribute."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_coro_has_module_qualifier_attr():
    # Fresh import to catch import-cycle related issues
    for k in list(sys.modules):
        if k.startswith('mojo.middle.coro'):
            del sys.modules[k]
    import mojo.middle.coro as coro
    assert hasattr(coro, 'module_qualifier'), "coro.module_qualifier missing"
    # Should be callable
    assert callable(coro.module_qualifier)
    assert coro.module_qualifier('foo.bar') == 'foo_bar'


if __name__ == '__main__':
    test_coro_has_module_qualifier_attr()
    print('PASS')
