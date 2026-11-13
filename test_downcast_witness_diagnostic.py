#!/usr/bin/env python3
"""Regression test for downcast witness-table diagnostics (trait conformance part 7).

`rebind[downcast[T, Trait]](x)` must diagnose when the concrete type `T` does
not have a witness table for `Trait`.
"""

import elaborate
from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_downcast_witness_missing_fails():
    src = r'''
trait LocalWritable:
    pass

struct Foo(ImplicitlyCopyable):
    var x: Int
    def __init__(out self, x: Int):
        self.x = x

def needs_writable[T: LocalWritable](x: T):
    pass

def invalid[T: ImplicitlyCopyable](x: T):
    needs_writable(rebind[downcast[T, LocalWritable]](x))
'''
    try:
        elaborate.Elaborator().elaborate_generic_call(src, 'invalid', ['Foo'], arg_count=1)
    except RuntimeError as e:
        s = str(e)
        assert 'function instantiation failed' in s, s
        assert 'does not have witness table for trait' in s, s
        return
    raise AssertionError('expected downcast witness-table diagnostic')


def test_downcast_witness_conforming_passes():
    src = r'''
trait LocalWritable:
    pass

struct Foo(ImplicitlyCopyable, LocalWritable):
    var x: Int
    def __init__(out self, x: Int):
        self.x = x

def needs_writable[T: LocalWritable](x: T):
    pass

def valid[T: ImplicitlyCopyable & LocalWritable](x: T):
    needs_writable(rebind[downcast[T, LocalWritable]](x))

def main():
    valid(Foo(1))
'''
    _compile(src)


def test_downcast_witness_generic_t_passes():
    # Generic T: no concrete witness can be decided, so accepted.
    src = r'''
trait LocalWritable:
    pass

struct Foo(ImplicitlyCopyable):
    var x: Int
    def __init__(out self, x: Int):
        self.x = x

def needs_writable[T: LocalWritable](x: T):
    pass

def maybe_ok[T: ImplicitlyCopyable](x: T):
    needs_writable(rebind[downcast[T, LocalWritable]](x))
'''
    _compile(src)


if __name__ == '__main__':
    test_downcast_witness_missing_fails()
    test_downcast_witness_conforming_passes()
    test_downcast_witness_generic_t_passes()
    print('ok')
