#!/usr/bin/env python3
"""Regression: `fire.py build` of a program whose generic instantiation the
elaborator rejects (modular's invalid_downcast_error.mojo: `rebind[downcast[T,
Writable]]` of a struct with no Writable witness) FAILS with that diagnostic and
exit 1. The compile error used to be swallowed by the driver try/except in
fire.py, which fell back to the inline single-unit compile of every stdlib module
(hours) and then built nothing."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')
MODULAR = ('/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/'
           'invalid_downcast_error.mojo')
FILECHECK = '/opt/homebrew/opt/llvm/bin/FileCheck'

SRC = '''@fieldwise_init
struct Foo(ImplicitlyCopyable):
    pass


def print_foo_invalid[T: Writable & Deinitable](var x: T):
    print(x)


def invalid[T: ImplicitlyCopyable & Deinitable](x: T):
    print_foo_invalid(rebind[downcast[T, Writable]](x))


def main():
    invalid(Foo())
'''


def test_build_reports_the_witness_diagnostic_and_fails():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'invalid_downcast_error.mojo')
        open(f, 'w').write(SRC)
        p = subprocess.run([sys.executable, FIRE, 'build', f, '-o', os.path.join(d, 'o')],
                           capture_output=True, text=True, timeout=900)
        out = p.stdout + p.stderr
        assert p.returncode == 1, (p.returncode, out[-500:])
        assert 'error: function instantiation failed' in out, out[-500:]
        assert ("struct 'invalid_downcast_error::Foo' does not have witness table for "
                "trait 'std::format::__init__::Writable'") in out, out[-500:]
        assert not os.path.exists(os.path.join(d, 'o'))
        if os.path.exists(MODULAR) and os.path.exists(FILECHECK):
            fc = subprocess.run([FILECHECK, MODULAR], input=out, capture_output=True, text=True)
            assert fc.returncode == 0, fc.stderr[-1500:]


if __name__ == '__main__':
    test_build_reports_the_witness_diagnostic_and_fails()
    print('ok test_build_reports_the_witness_diagnostic_and_fails')
    print('all tests passed')
