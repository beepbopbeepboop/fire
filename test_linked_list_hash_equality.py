#!/usr/bin/env python3
"""Regression: hash() of equal LinkedList[Int] values must be equal.

hash(l) must lower through the struct's __hash__ (hasher protocol) so
equal linked lists produce equal hashes and the program links.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SRC = '''from std.collections import LinkedList

def main():
    var a = LinkedList[Int](1, 2, 3)
    var b = LinkedList[Int](1, 2, 3)
    print(hash(a) == hash(b))
'''


def test_linked_list_hash_equality():
    path = os.path.join(HERE, '.tmp', 'll_hash_eq_test.mojo')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(SRC)
    env = os.environ.copy()
    env.setdefault('TMPDIR', os.path.join(HERE, '.tmp'))
    proc = subprocess.run(
        [sys.executable, 'tools/memslot.py', '--gb', '8', '--label', 'll-hash-eq',
         '--', sys.executable, 'fire.py', 'run', path],
        cwd=HERE, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # memcap/memslot emit progress; the program prints "True".
    out_lines = [l.strip() for l in proc.stdout.splitlines()
                 if l.strip() and not l.startswith('memcap:')]
    assert out_lines == ['True'], proc.stdout + proc.stderr


if __name__ == '__main__':
    test_linked_list_hash_equality()
    print('PASS')
