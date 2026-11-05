#!/usr/bin/env python3
"""Regression for PLAN_linked-list-reflection_step4: struct-valued elements."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SRC = '''from std.collections import LinkedList

struct CopyCountedStruct:
    var x: Int

    fn __init__(out self, x: Int):
        self.x = x

def main():
    var l = LinkedList[CopyCountedStruct]()
    l.append(CopyCountedStruct(5))
    var it = l.__iter__()
    print(it.__next__().x)
'''


def _compile():
    from build_stdlib_dylib import compile_module_to_c
    path = os.path.join(HERE, '.tmp', 'll_struct_elem_probe.mojo')
    return compile_module_to_c(SRC, path, 'll_struct_elem_probe', linkable=False)


def _main_body(c):
    i = c.index('_ll_struct_elem_probe_main (void)')
    return c[i:c.index('\n}\n', i)]


def test_linked_list_struct_element():
    c = _compile()
    body = _main_body(c)
    assert 'int64_t l;' not in body
    assert '__next__() stubbed' not in c
    assert 'CopyCountedStruct' in c


if __name__ == '__main__':
    test_linked_list_struct_element()
    print('PASS')
