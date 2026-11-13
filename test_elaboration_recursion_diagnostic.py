#!/usr/bin/env python3
"""Regression test for generic elaboration recursion diagnostics.

- Direct self-recursion must still be refused with the existing wording.
- Mutually recursive generic instantiation must be refused (not silently
  compiled to a stub that answers 0, and not hang).
- Finite instantiation chains must still build and run.
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIRE = [sys.executable, os.path.join(ROOT, 'fire.py')]


def _build_and_run(source, *, timeout=120):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 't.mojo')
        exe = os.path.join(d, 'a.out')
        with open(src, 'w') as f:
            f.write(source)
        p = subprocess.run(
            FIRE + ['build', src, '-o', exe],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        out = p.stdout
        if p.returncode != 0:
            return p.returncode, out, None
        r = subprocess.run(
            [exe],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return 0, out, r


def test_direct_self_recursion_still_refused():
    src = (
        'def self_recursion[i: Int]() -> Int:\n'
        '    var x = self_recursion[i + 1]()\n'
        '    return x\n'
        '\n'
        'def main():\n'
        '    print(self_recursion[0]())\n'
    )
    rc, out, _ = _build_and_run(src)
    assert rc != 0, 'direct self-recursion compiled (expected diagnostic):\n' + out
    assert "self recursive call to 'self_recursion' will cause an infinite loop" in out, out


def test_mutual_recursion_refused():
    src = (
        'def a[i: Int]() -> Int:\n'
        '    return b[i + 1]()\n'
        '\n'
        'def b[i: Int]() -> Int:\n'
        '    return a[i + 1]()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, _ = _build_and_run(src)
    assert rc != 0, 'mutual recursion compiled (expected diagnostic):\n' + out
    assert ('infinite recursion' in out) or ('self recursive call' in out), out


def test_finite_chain_builds_and_runs():
    # A finite generic instantiation chain must still build and run.
    src = (
        'def b() -> Int:\n'
        '    return 7\n'
        '\n'
        'def a[i: Int]() -> Int:\n'
        '    return b()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'finite chain failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert r.stdout.strip() == '7', r.stdout


def test_finite_chain_few_levels_deep_builds():
    # Finite instantiations a few levels deep, below the recursion cap, build.
    src = (
        'def c[i: Int]() -> Int:\n'
        '    return 5\n'
        '\n'
        'def b[i: Int]() -> Int:\n'
        '    return c[1]()\n'
        '\n'
        'def a[i: Int]() -> Int:\n'
        '    return b[1]()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'finite chain (few levels) failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)


if __name__ == '__main__':
    tests = [
        test_direct_self_recursion_still_refused,
        test_mutual_recursion_refused,
        test_finite_chain_builds_and_runs,
        test_finite_chain_few_levels_deep_builds,
    ]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all passed')
