#!/usr/bin/env python3
"""`mixed_field_names`: a struct field that is stored a `None` literal AND a
scalar literal is the box-holding kind (doc/GIR.md stage 5c, the 2026-11-22
corpus group where `None` printed as 0). Predicate only: no C changes here.

Run:  python3 test_gimple_mixed_field_names.py
"""
import sys
import fire_compiler
from mojo.backend_gimple import emit_infra


def _struct(src):
    p = fire_compiler.Parser(fire_compiler.py_tokenize(src))
    p._filename = "t.mojo"
    for node in p.parse_module():
        if type(node).__name__ in ('StructDef', 'ClassDef'):
            return node
    raise AssertionError("no class in source")


def _mixed(src):
    return sorted(emit_infra.mixed_field_names(_struct(src)))


def main():
    fails = []

    reduction = '''
class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = 42
    def take(self):
        self.s = None
'''
    got = _mixed(reduction)
    if got != ['s']:
        fails.append(f"reduction: expected ['s'], got {got}")

    only_none = '''
class C:
    def __init__(self):
        self.s = None
    def take(self):
        self.s = None
'''
    if _mixed(only_none) != []:
        fails.append("only-None field must not be mixed")

    only_int = '''
class C:
    def __init__(self):
        self.n = 0
    def bump(self):
        self.n = 7
'''
    if _mixed(only_int) != []:
        fails.append("int-only field must not be mixed")

    nested = '''
class C:
    def __init__(self):
        self.s = None
    def set(self, flag):
        if flag:
            self.s = "text"
'''
    if _mixed(nested) != ['s']:
        fails.append(f"store inside an if block must count: got {_mixed(nested)}")

    non_literal = '''
class C:
    def __init__(self):
        self.s = None
    def set(self, x):
        self.s = x
'''
    if _mixed(non_literal) != []:
        fails.append("a non-literal store is no evidence of a kind")

    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print("mixed_field_names: 5 cases, 0 failures")
    return 0


if __name__ == '__main__':
    sys.exit(main())
