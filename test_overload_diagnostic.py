#!/usr/bin/env python3
"""Regression: a call no overload accepts is reported in the modular
compiler's shape (`error: no matching function in call to 'f'` plus one
`note: candidate not viable: <reason>` per candidate, each with its source line
and caret), not as a one-line runtime TypeError.

Expected text was captured from `tools/mojo build` on the same sources
(DIAGNOSTICS_formatting_modular part 1, group B). Runs the interpreter only."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

OVERLOADS = '''def overloaded_function(n: Int):
    pass


def overloaded_function(n: Float64):
    pass


def overloaded_function(n: Int, m: Float64):
    pass


def main():
%s
'''


def run(path):
    p = subprocess.run([sys.executable, FIRE, 'run', path],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stderr


def test_missing_required_argument():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'o.mojo')
        open(f, 'w').write(OVERLOADS % '    overloaded_function()')
        rc, err = run(f)
        want = f"""{f}:14:24: error: no matching function in call to 'overloaded_function'
    overloaded_function()
    ~~~~~~~~~~~~~~~~~~~^
{f}:1:5: note: candidate not viable: missing required argument: 'n'
def overloaded_function(n: Int):
    ^
{f}:5:5: note: candidate not viable: missing required argument: 'n'
def overloaded_function(n: Float64):
    ^
{f}:9:5: note: candidate not viable: missing required argument: 'n'
def overloaded_function(n: Int, m: Float64):
    ^
"""
        assert rc == 1, rc
        assert err == want, err


def test_unexpected_argument_caret_on_callee():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'q.mojo')
        open(f, 'w').write('''def f(n: Int):
    pass


def f(n: Float64, m: Float64):
    pass


def main():
    f(1, 2, 3)
''')
        rc, err = run(f)
        want = f"""{f}:10:5: error: no matching function in call to 'f'
    f(1, 2, 3)
    ^
{f}:1:5: note: candidate not viable: unexpected argument
def f(n: Int):
    ^
{f}:5:5: note: candidate not viable: unexpected argument
def f(n: Float64, m: Float64):
    ^
"""
        assert rc == 1 and err == want, err


def test_candidates_in_an_imported_package():
    with tempfile.TemporaryDirectory() as d:
        pkg = os.path.join(d, 'diags_package')
        os.mkdir(pkg)
        init = os.path.join(pkg, '__init__.mojo')
        open(init, 'w').write('def g(n: Int):\n    pass\n\n\ndef g(n: Float64):\n    pass\n')
        f = os.path.join(d, 'm.mojo')
        open(f, 'w').write('import diags_package\n\n\ndef main():\n    diags_package.g()\n')
        rc, err = run(f)
        want = f"""{f}:5:20: error: no matching function in call to 'g'
    diags_package.g()
    ~~~~~~~~~~~~~~~^
Imported from {f}:1:
{init}:1:5: note: candidate not viable: missing required argument: 'n'
def g(n: Int):
    ^
Imported from {f}:1:
{init}:5:5: note: candidate not viable: missing required argument: 'n'
def g(n: Float64):
    ^
"""
        assert rc == 1 and err == want, err


def test_unverified_shape_keeps_plain_error():
    # An unknown keyword is not a shape verified against the real compiler, so
    # no modular block is printed; the one-line error survives.
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'k.mojo')
        open(f, 'w').write('''def h(n: Int):
    pass


def h(n: Float64, m: Float64):
    pass


def main():
    h(1, bogus=2)
''')
        rc, err = run(f)
        assert rc == 1 and "no overload of 'h'" in err, err
        assert 'note: candidate not viable' not in err


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
