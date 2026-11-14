#!/usr/bin/env python3
"""Regression: calls the module's own text proves wrong are reported by the
static pass, BEFORE anything runs and TOGETHER with the declaration errors, in
source order -- as the modular compiler does -- instead of the interpreter
stopping at the first one it happens to execute. Covers a violated `where`
clause (`f[0]()`), an overload failure with no argument (`g()`), one with an
extra argument whose caret lands on that argument (`g(1, 2)`: every candidate
runs out at the second argument), and a struct missing a trait requirement
after them. Expected text captured from `tools/mojo build`
(DIAGNOSTICS_formatting_modular part 1)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

SRC = 'trait Need:\n    def go(self):\n        ...\n\n\ndef f[n: Int]() where n > 0:\n    pass\n\n\ndef g(n: Int):\n    pass\n\n\ndef g(n: Float64):\n    pass\n\n\ndef main():\n    print("must not run")\n    f[0]()\n    g()\n    f[2]()\n    g(1, 2)\n\n\nstruct Bad(Need):\n    pass\n'

WANT = "F:20:5: error: invalid call to 'f': violated constraint\n    f[0]()\n    ^\nF:6:23: note: constraint declared here evaluated to False, expected '(n > Int(0))'\ndef f[n: Int]() where n > 0:\n                      ^\nF:6:5: note: function declared here\ndef f[n: Int]() where n > 0:\n    ^\nF:21:6: error: no matching function in call to 'g'\n    g()\n    ~^\nF:10:5: note: candidate not viable: missing required argument: 'n'\ndef g(n: Int):\n    ^\nF:14:5: note: candidate not viable: missing required argument: 'n'\ndef g(n: Float64):\n    ^\nF:23:10: error: no matching function in call to 'g'\n    g(1, 2)\n    ~    ^\nF:10:5: note: candidate not viable: unexpected argument\ndef g(n: Int):\n    ^\nF:14:5: note: candidate not viable: unexpected argument\ndef g(n: Float64):\n    ^\nF:26:8: error: 'Bad' does not implement all requirements for 'Need'\nstruct Bad(Need):\n       ^\nF:2:9: note: required function 'go' is not implemented\n    def go(self):\n        ^\nF:1:7: note: trait 'Need' declared here\ntrait Need:\n      ^\n"


def test_static_calls_and_declarations_in_source_order():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 's.mojo')
        open(f, 'w').write(SRC)
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(f, 'F')
        assert p.returncode == 1 and p.stdout == '' and err == WANT, (p.stdout, err)


def test_valid_calls_still_run():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'v.mojo')
        open(f, 'w').write('''def f[n: Int]() where n > 0:
    print("f", n)


def g(n: Int):
    print("int", n)


def g(n: Int, m: Int):
    print("two", n, m)


def main():
    f[2]()
    g(1)
    g(1, 2)
''')
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr
        assert p.stdout.split() == ['f', '2', 'int', '1', 'two', '1', '2'], p.stdout


def test_a_local_binding_shadows_the_function():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'x.mojo')
        open(f, 'w').write('''def g(n: Int):
    pass


def g(n: Float64):
    pass


def main():
    var g = 5
    print(g)
''')
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0 and p.stdout.strip() == '5', (p.stdout, p.stderr)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
