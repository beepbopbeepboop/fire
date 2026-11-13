#!/usr/bin/env python3
"""A `where` clause may resolve a top-level module `alias` constant.

Regression for DIAGNOSTICS_missing_validation_modular-part5: a provably-false
`where` clause that names a module `alias` must be rejected, while an
undecided clause and an ordinary module-level assignment must remain accepted.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from diagnostic_build import build_refusal
from gimple_codegen import compile_to_gimple


def _compile(src):
    d = tempfile.mkdtemp(prefix='where_alias_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    return compile_to_gimple(src, do_imports=True, filename=p)


def _expect_refusal(src, *needles):
    rc, text = build_refusal(src)
    assert rc != 0, ('expected refusal, compiled ok', src)
    for n in needles:
        assert n in text, (n, text)
    return text


# --- function where, module alias ---

def test_function_where_alias_violated_fails():
    _expect_refusal(
        'alias LIMIT = 2\n'
        'def f[x: Int]() where x < LIMIT:\n'
        '    pass\n'
        'fn main():\n'
        '    f[5]()\n',
        "requirement 'x < LIMIT' is not satisfied")


def test_function_where_alias_satisfied_compiles():
    _compile(
        'alias LIMIT = 2\n'
        'def f[x: Int]() where x < LIMIT:\n'
        '    pass\n'
        'fn main():\n'
        '    f[1]()\n')


def test_function_where_alias_message_violated_fails():
    _expect_refusal(
        'alias LIMIT = 2\n'
        'def f[x: Int]() where (x < LIMIT, "too big"):\n'
        '    pass\n'
        'fn main():\n'
        '    f[5]()\n',
        'too big')


# --- struct where, module alias ---

def test_struct_where_alias_violated_fails():
    _expect_refusal(
        'alias LIMIT = 2\n'
        'struct S[x: Int] where x < LIMIT:\n'
        '    var v: Int\n'
        '    def __init__(out self):\n'
        '        self.v = x\n'
        'fn main():\n'
        '    var s = S[5]()\n',
        "requirement 'x < LIMIT' is not satisfied")


def test_struct_where_alias_satisfied_compiles():
    _compile(
        'alias LIMIT = 2\n'
        'struct S[x: Int] where x < LIMIT:\n'
        '    var v: Int\n'
        '    def __init__(out self):\n'
        '        self.v = x\n'
        'fn main():\n'
        '    var s = S[1]()\n')


# --- undecided: unfolderable alias stays accepted ---

def test_unfolderable_alias_clause_stays_accepted():
    # The alias value is not a foldable literal, so the clause is undecided and
    # must not become a false positive.
    _compile(
        'alias LIMIT = some_unknown_name\n'
        'def f[x: Int]() where x < LIMIT:\n'
        '    pass\n'
        'fn main():\n'
        '    f[5]()\n')


# --- control: ordinary module-level assignment is not a constant ---

def test_module_assignment_not_treated_as_constant():
    # `LIMIT = 2` is a module-level assignment, not an `alias`. If it were
    # folded as a constant, f[5]() would be wrongly rejected.
    _compile(
        'LIMIT = 2\n'
        'def f[x: Int]() where x < LIMIT:\n'
        '    pass\n'
        'fn main():\n'
        '    f[5]()\n')


# --- existing integer/Bool literal and predicate behaviour preserved ---

def test_integer_literal_where_still_enforced():
    _expect_refusal(
        'def f[x: Int]() where x < 2:\n'
        '    pass\n'
        'fn main():\n'
        '    f[5]()\n',
        "requirement 'x < 2' is not satisfied")


def test_integer_literal_where_still_compiles():
    _compile(
        'def f[x: Int]() where x < 2:\n'
        '    pass\n'
        'fn main():\n'
        '    f[1]()\n')


if __name__ == '__main__':
    test_function_where_alias_violated_fails()
    test_function_where_alias_satisfied_compiles()
    test_function_where_alias_message_violated_fails()
    test_struct_where_alias_violated_fails()
    test_struct_where_alias_satisfied_compiles()
    test_unfolderable_alias_clause_stays_accepted()
    test_module_assignment_not_treated_as_constant()
    test_integer_literal_where_still_enforced()
    test_integer_literal_where_still_compiles()
    print('ok')
