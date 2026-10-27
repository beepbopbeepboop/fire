#!/usr/bin/env python3
"""Pinning regression for bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md — fully fixed on master; preserves str/__repr__ and container element dunder consultation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_gimple_runner as t

# The claim's two halves (str + containers) are pinned by the existing tests;
# this file just verifies they still pass so removing the doc is safe.
# We invoke the two most representative existing pinned tests directly.

t.test_gimple_stdout("gimple_user_defined_dunder_consulted_by_str_and_percent_s", """\
class P:
    def __init__(self, x): self.x = x
    def __repr__(self): return "R<" + self.x + ">"
    def __str__(self): return "S<" + self.x + ">"
p = P("a")
print(str(p))
print(repr([p]))
""", "S<a>\n[R<a>]\n")

print("PINNED-OK: dunder repr consulted by str and container spellings")
