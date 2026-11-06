#!/usr/bin/env python3
"""`model.once_bound_string_literals`: the only names whose literal text a fold may use.

A `var s = "lit"` is a MUTABLE local. The first draft of the printf/subscript
folds recorded every such binding in the codegen's `_comptime_vals` (the table of
`comptime` constants), which made any later `s = ...` a build error — it broke 42
of the 92 hostmods through `out = ...` in `os/_syscalls.mojo` — and would have
folded a stale text for a name reassigned on another path. This pins the rule that
replaced it: bound exactly once, to a plain string literal, and never stored to
again.

    python3 test_formal_once_bound_strings.py
"""
import sys
import unittest

import formal.build  # noqa: F401  (import order: formal.model needs formal.types first)
import fire_compiler as F
from formal import model as M


def _fn(src, name="f"):
    mod = F.Parser(F.py_tokenize(src)).parse_module()
    return next(n for n in mod if getattr(n, "name", None) == name)


class OnceBound(unittest.TestCase):
    def test_a_name_bound_once_to_a_literal_is_known(self):
        fn = _fn('def f(n: Int) -> Int:\n    var a = "日本"\n    return 0\n')
        self.assertEqual({"a": "日本"}, M.once_bound_string_literals(fn))

    def test_escapes_are_decoded(self):
        fn = _fn('def f(n: Int) -> Int:\n    var a = "a\\x41"\n    return 0\n')
        self.assertEqual({"a": "aA"}, M.once_bound_string_literals(fn))

    def test_a_reassigned_name_is_not_known(self):
        fn = _fn('def f(n: Int) -> Int:\n    var b = "xy"\n    b = "z"\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_an_augmented_assignment_is_a_store(self):
        fn = _fn('def f(n: Int) -> Int:\n    var b = "xy"\n    b += "z"\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_a_for_target_is_a_store(self):
        fn = _fn('def f(n: Int) -> Int:\n    var c = "k"\n    for c in range(3):\n        pass\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_a_parameter_is_not_a_literal_binding(self):
        fn = _fn('def f(a: Int) -> Int:\n    var a = "q"\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_a_second_declaration_disqualifies_the_name(self):
        fn = _fn('def f(n: Int) -> Int:\n    var a = "p"\n    if n:\n        var a = "q"\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_a_non_literal_value_is_not_known(self):
        fn = _fn('def f(n: Int) -> Int:\n    var a = g()\n    var b = 3\n    return 0\n')
        self.assertEqual({}, M.once_bound_string_literals(fn))

    def test_independent_names_do_not_disturb_each_other(self):
        fn = _fn('def f(n: Int) -> Int:\n    var a = "ok"\n    var b = "no"\n    b = "x"\n    return 0\n')
        self.assertEqual({"a": "ok"}, M.once_bound_string_literals(fn))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
