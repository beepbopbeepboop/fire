#!/usr/bin/env python3
"""The disagreement classes of an early return decision (bugs/GIR_type_solver_precision.md, 4.5).

`emit_funcs._return_disagreement(frozen, measured)` must return exactly the table in its docstring:
same | refined | weak | conflict. A `weak` or `conflict` is an acceptance failure, a `refined` is
allowed and listed, so this table is what the acceptance count stands on.

Run directly: python3 test_return_disagreement.py
"""
import sys
import unittest

import mojo.backend_gimple.emit_funcs as gfn


class Table(unittest.TestCase):
    def check(self, frozen, measured, want):
        self.assertEqual(gfn._return_disagreement(frozen, measured), want,
                         '%r early, %r measured' % (frozen, measured))

    def test_identical_is_same(self):
        self.check('int64_t', 'int64_t', 'same')
        self.check('char *', 'char *', 'same')
        self.check('MojoList *', 'MojoList *', 'same')

    def test_solver_lost_a_pointer_the_backend_knew_is_weak(self):
        self.check('int64_t', 'char *', 'weak')
        self.check('int64_t', 'MojoDict *', 'weak')
        self.check('int64_t', '_Bool', 'weak')
        self.check('int64_t', 'StructDef *', 'weak')

    def test_solver_knew_more_than_the_backend_is_refined(self):
        self.check('char *', 'int64_t', 'refined')
        self.check('MojoList *', 'int64_t', 'refined')
        self.check('_Bool', 'int64_t', 'refined')

    def test_two_different_pointers_are_a_conflict(self):
        self.check('char *', 'MojoList *', 'conflict')
        self.check('MojoDict *', 'MojoSet *', 'conflict')

    def test_a_word_or_pointer_against_a_double_is_a_conflict(self):
        self.check('double', 'int64_t', 'conflict')
        self.check('int64_t', 'double', 'conflict')
        self.check('char *', 'double', 'conflict')

    def test_void_against_a_value_is_a_conflict(self):
        self.check('void', 'char *', 'conflict')
        self.check('char *', 'void', 'conflict')


if __name__ == '__main__':
    sys.exit(0 if unittest.TextTestRunner(verbosity=1).run(
        unittest.TestLoader().loadTestsFromTestCase(Table)).wasSuccessful() else 1)
