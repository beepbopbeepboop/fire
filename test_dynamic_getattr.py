#!/usr/bin/env python3
"""Regression: dynamic getattr of a method must agree with static spelling."""
from myinterpreter import Interpreter
import fire_compiler as N

def test_dynamic_getattr_method():
    source = '''
class C:
    def __init__(self):
        self.k = 9
    def add(self, a, b):
        return self.k + a + b

def main():
    c = C()
    t = getattr(c, "add")
    print(t(1, 2))
'''
    mod = N.Module(body=N.Parser(N.py_tokenize(source)).parse_module())
    interp = Interpreter()
    interp.execute(mod)

if __name__ == '__main__':
    test_dynamic_getattr_method()
    print("PASS")
