#!/usr/bin/env python3
"""Regression: a Mojo keyword used as an ordinary identifier must parse.

bugs/PARSER_keyword_identifier_collision_refuses_module.md.  The compiler
compiles its own Python sources as Mojo, so every Mojo keyword that is a legal
Python identifier (`trait`, and the same shape for the others) can appear as a
variable name.  `trait` was the one that broke: the statement dispatch committed
to `_parse_trait()` unconditionally, so mojo/middle/mojoc_conformance.py's
`trait = (records or {}).get(...)` was refused with
"Expected NAME got ASSIGN('=')", aborting every whole-program self-host compile.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import elaborate as E


def _parse(src):
    return E.Parser(E.py_tokenize(src)).parse_module()


def _declared_names(src):
    return [getattr(s, 'name', None) for s in _parse(src)
            if hasattr(s, 'name')]


def test_keyword_as_identifier_assigns():
    # The exact shape that was refused: a plain assignment to `trait`.
    _parse('def f():\n    trait = 1\n')


def test_keyword_as_identifier_in_expression():
    _parse('def f():\n    trait = (records or {}).get(_split_bound(bound))\n'
           '    return trait\n')


def test_keyword_as_identifier_after_continue():
    # The reported site's surrounding shape (inside a for/if with a continue).
    _parse('def f():\n'
           '    for i, arg in enumerate(args):\n'
           '        if not bound:\n'
           '            continue\n'
           '        trait = (records or {}).get(bound)\n')


def test_keyword_as_attribute_and_call():
    _parse('def f():\n    return trait.foo\n')
    _parse('def f():\n    return trait(1)\n')


def test_real_trait_declarations_still_parse():
    # The carve-out must not swallow a declaration: `trait` followed by a NAME.
    assert _declared_names('trait Foo:\n    pass\n') == ['Foo']
    assert _declared_names('trait Foo[U]:\n    pass\n') == ['Foo']


def test_the_module_that_was_refused_parses():
    p = os.path.join(HERE, 'mojo', 'middle', 'mojoc_conformance.py')
    if not os.path.exists(p):
        return
    _parse(open(p).read())


if __name__ == '__main__':
    for _name, _fn in sorted(globals().items()):
        if _name.startswith('test_') and callable(_fn):
            _fn()
            print(f'PASS  {_name}')
    print('ok')
