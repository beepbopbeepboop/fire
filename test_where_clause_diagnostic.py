#!/usr/bin/env python3
"""Regression: a call whose `where` clause evaluates to False for its bound
comptime parameters is rejected in the modular compiler's shape
(`error: invalid call to 'f': violated constraint`, the constraint note with
the pretty-printed expression, the `function declared here` note), instead of
being silently accepted. Expected text captured from `tools/mojo build`
(DIAGNOSTICS_formatting_modular part 1, group A)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')


def run(path):
    p = subprocess.run([sys.executable, FIRE, 'run', path],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


def test_violated_constraint_same_file():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'w.mojo')
        open(f, 'w').write('''def f[n: Int]() where n > 0:
    pass


def main():
    f[0]()
''')
        rc, out, err = run(f)
        want = f"""{f}:6:5: error: invalid call to 'f': violated constraint
    f[0]()
    ^
{f}:1:23: note: constraint declared here evaluated to False, expected '(n > Int(0))'
def f[n: Int]() where n > 0:
                      ^
{f}:1:5: note: function declared here
def f[n: Int]() where n > 0:
    ^
"""
        assert rc == 1 and err == want, err


def test_violated_constraint_through_a_package_member():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'pk'))
        init = os.path.join(d, 'pk', '__init__.mojo')
        open(init, 'w').write('def fc[n: Int]() where n > 0:\n    pass\n')
        f = os.path.join(d, 'm.mojo')
        open(f, 'w').write('import pk\n\n\ndef main():\n    pk.fc[0]()\n')
        rc, out, err = run(f)
        want = f"""{f}:5:7: error: invalid call to 'fc': violated constraint
    pk.fc[0]()
    ~~^~~
Imported from {f}:1:
{init}:1:24: note: constraint declared here evaluated to False, expected '(n > Int(0))'
def fc[n: Int]() where n > 0:
                       ^
Imported from {f}:1:
{init}:1:5: note: function declared here
def fc[n: Int]() where n > 0:
    ^
"""
        assert rc == 1 and err == want, err


def test_satisfied_constraint_runs():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 's.mojo')
        open(f, 'w').write('''def f[n: Int]() where n >= 0:
    print("ran", n)


def main():
    f[0]()
    f[3]()
''')
        rc, out, err = run(f)
        assert rc == 0 and out == 'ran 0\nran 3\n', (rc, out, err)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
