#!/usr/bin/env python3
from fire_compiler import py_tokenize, Parser


def test_double_slash_line_comments():
    src = """// comment at start
x = 1 // inline comment
// another
y = x + 2  // end
"""
    tokens = py_tokenize(src)
    # Should parse successfully
    names = [t.value for t in tokens if t.kind == 'NAME']
    assert 'x' in names
    assert 'y' in names
    assert 'comment' not in ' '.join([t.value for t in tokens])
    stmts = Parser(tokens).parse_module()
    assert len(stmts) == 2  # two assignments


def test_triple_slash_comment():
    src = """/// doc comment
z = 42 /// another
"""
    tokens = py_tokenize(src)
    names = [t.value for t in tokens if t.kind == 'NAME']
    assert 'z' in names
    stmts = Parser(tokens).parse_module()
    assert len(stmts) == 1


if __name__ == '__main__':
    test_double_slash_line_comments()
    test_triple_slash_comment()
    print('ok')
