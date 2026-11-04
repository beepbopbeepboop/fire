#!/usr/bin/env python3
"""Regression for PLAN_linked-list-reflection_step1: LinkedList.__hash__ not stubbed."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SRC = '''from std.collections import LinkedList

def main():
    var l = LinkedList[Int](1, 2, 3)
    var h = hash(l)
    print(h)
'''


def _compile():
    from build_stdlib_dylib import compile_module_to_c
    path = os.path.join(HERE, '.tmp', 'll_hash_probe.mojo')
    return compile_module_to_c(SRC, path, 'll_hash_probe', linkable=False)


def test_linked_list_hash_not_stubbed():
    c = _compile()
    # LinkedList.__hash__ must not produce stubbed calls
    assert '__hash__() stubbed' not in c
    assert 'int64_t.__hash__() stubbed' not in c


if __name__ == '__main__':
    test_linked_list_hash_not_stubbed()
    print('PASS')
