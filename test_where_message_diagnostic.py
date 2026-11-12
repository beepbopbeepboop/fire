#!/usr/bin/env python3
"""Regression test: a `where` clause with a message is enforced.

Modular's test/mojo-parser/decls/where_message_errors.mojo requires a provably
false `where (cond, "message")` to be rejected at the call (function) or the
instantiation (struct), with the user's message in the note. Before this, the
parser skipped struct `where` clauses and the elaborator's check was a regex
that only knew the DType predicates, so both programs compiled silently.

Each case is one row of the table in
bugs/mid/DIAGNOSTICS_missing_validation_modular-part1.md, compiled with
do_imports=True from a real temp file (the elaborator reads the template back
from there).
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src):
    d = tempfile.mkdtemp(prefix='where_message_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    return compile_to_gimple(src, do_imports=True, filename=p)


_GATED = ('def gated_fn[sc: Int]() where (sc > 1, "scaling factor must be greater than 1"):\n'
          '    pass\n')
_STRUCT = ('struct ViolatedStruct[N: Int] where (N > 0, "N must be positive"):\n'
           '    var x: Int\n'
           '    def __init__(out self):\n'
           '        self.x = N\n')
_RANGE = ('def bounded[N: Int]() where (N > 0 and N < 10, "N must be in (0, 10)"):\n'
          '    pass\n')
_SINGLE = ('def f[x: Int]() where (x > 0 and x < 10):\n'
           '    pass\n')
_NATURAL = ('def requires_natural[x: Int](y: Int) where x >= 0:\n'
            '    pass\n'
            'def caller[x: Int](y: Int):\n'
            '    comptime assert x >= 0, "x must be non-negative"\n'
            '    requires_natural[x](y)\n')


def _expect_violation(src, *needles):
    try:
        _compile(src)
    except RuntimeError as e:
        text = str(e)
        for n in needles:
            assert n in text, (n, text)
        return
    raise AssertionError('provably-false where clause compiled without error')


def test_function_where_message_violated_fails():
    _expect_violation(_GATED + 'fn main():\n    gated_fn[0]()\n',
                      "invalid call to 'gated_fn': violated constraint",
                      'scaling factor must be greater than 1')


def test_function_where_message_satisfied_compiles():
    _compile(_GATED + 'fn main():\n    gated_fn[2]()\n')


def test_struct_where_message_violated_fails():
    _expect_violation(_STRUCT + 'fn main():\n    var v = ViolatedStruct[-1]()\n',
                      'violated constraint',
                      'N must be positive')


def test_struct_where_message_satisfied_compiles():
    _compile(_STRUCT + 'fn main():\n    var v = ViolatedStruct[5]()\n')


def test_range_where_message_false_fails():
    _expect_violation(_RANGE + 'fn main():\n    bounded[-1]()\n',
                      'violated constraint',
                      'N must be in (0, 10)')


def test_range_where_message_true_compiles():
    _compile(_RANGE + 'fn main():\n    bounded[5]()\n')


def test_parenthesised_single_condition_is_enforced():
    # `(x > 0 and x < 10)` is one condition with no message.
    _expect_violation(_SINGLE + 'fn main():\n    f[20]()\n',
                      'violated constraint')


def test_caller_with_comptime_assert_still_compiles():
    # The caller's `comptime assert x >= 0` precedes the constrained call. Here
    # x is bound to 3, so the clause folds true and this compiles. The
    # undecided path (an unbound name) is accepted by the same rule in
    # check_where_clauses; this case pins that the assert-carrying shape is not
    # rejected.
    _compile(_NATURAL + 'fn main():\n    caller[3](1)\n')


if __name__ == '__main__':
    test_function_where_message_violated_fails()
    test_function_where_message_satisfied_compiles()
    test_struct_where_message_violated_fails()
    test_struct_where_message_satisfied_compiles()
    test_range_where_message_false_fails()
    test_range_where_message_true_compiles()
    test_parenthesised_single_condition_is_enforced()
    test_caller_with_comptime_assert_still_compiles()
    print('ok')
