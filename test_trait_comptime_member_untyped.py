#!/usr/bin/env python3
"""Regression: a struct that provides a trait's required `comptime` member as an
UNANNOTATED alias (`comptime Value = Self.Dest`, no `: Type`) satisfies it as
far as the static pass can tell; it must not be reported as a type mismatch
(the member's recorded type is the empty string). Found by modular's
defaulted_trait_method_bad_conformance.mojo, whose real error is elsewhere."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

SRC = '''trait T:
    comptime Value: Copyable

    def value(self) -> Int:
        ...


struct S[Dest: Copyable](T):
    comptime Value = Self.Dest

    def value(self) -> Int:
        return 7


def main():
    print("ok")
'''


def test_unannotated_comptime_alias_is_not_a_mismatch():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 't.mojo')
        open(f, 'w').write(SRC)
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0 and p.stdout == 'ok\n', (p.stdout, p.stderr)


if __name__ == '__main__':
    test_unannotated_comptime_alias_is_not_a_mismatch()
    print('ok test_unannotated_comptime_alias_is_not_a_mismatch')
    print('all tests passed')
