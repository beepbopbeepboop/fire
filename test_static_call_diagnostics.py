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


BIND_PACKAGE = 'def cf[a: Int, b: Int]() where a > 0:\n    pass\n'

BIND_MAIN = '''import pk


def lf[a: Int, b: Int]() where a > 0:
    pass


def main():
    comptime x = pk.cf[0, 1]
    comptime y = lf[0, 1]
    comptime ok = lf[1, 1]
'''

BIND_WANT = "M:9:20: error: violated constraint\n    comptime x = pk.cf[0, 1]\n                   ^\nImported from M:1:\nP:1:32: note: constraint declared here evaluated to False, expected '(a > Int(0))'\ndef cf[a: Int, b: Int]() where a > 0:\n                               ^\nImported from M:1:\nP:1:5: note: function declared here\ndef cf[a: Int, b: Int]() where a > 0:\n    ^\nM:10:18: error: violated constraint\n    comptime y = lf[0, 1]\n                 ^\nM:4:32: note: constraint declared here evaluated to False, expected '(a > Int(0))'\ndef lf[a: Int, b: Int]() where a > 0:\n                               ^\nM:4:5: note: function declared here\ndef lf[a: Int, b: Int]() where a > 0:\n    ^\n"


def test_violated_where_clause_in_a_comptime_binding():
    # `comptime x = f[0, 1]` instantiates f without calling it: the message has
    # no callee, and the caret sits on the callee (the `.` of a member callee)
    # with no `~` run.
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'pk'))
        pk = os.path.join(d, 'pk', '__init__.mojo')
        open(pk, 'w').write(BIND_PACKAGE)
        m = os.path.join(d, 'g.mojo')
        open(m, 'w').write(BIND_MAIN)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(pk, 'P').replace(m, 'M')
        assert p.returncode == 1 and err == BIND_WANT, err


LONG_NAMES = {'r': ('def lf[n: Int]() where n > 0:\n    pass\n\n\ndef lg[n: Int]() -> Int where n > 0:\n    return 1\n\n\ndef main():\n    lf[0]()\n    _ = lg[0]()\n    var v = lg[0]()\n', "F:10:5: error: invalid call to 'lf': violated constraint\n    lf[0]()\n    ^~\nF:1:24: note: constraint declared here evaluated to False, expected '(n > Int(0))'\ndef lf[n: Int]() where n > 0:\n                       ^\nF:1:5: note: function declared here\ndef lf[n: Int]() where n > 0:\n    ^\nF:11:9: error: invalid call to 'lg': violated constraint\n    _ = lg[0]()\n        ^~\nF:5:31: note: constraint declared here evaluated to False, expected '(n > Int(0))'\ndef lg[n: Int]() -> Int where n > 0:\n                              ^\nF:5:5: note: function declared here\ndef lg[n: Int]() -> Int where n > 0:\n    ^\nF:12:13: error: invalid call to 'lg': violated constraint\n    var v = lg[0]()\n            ^~\nF:5:31: note: constraint declared here evaluated to False, expected '(n > Int(0))'\ndef lg[n: Int]() -> Int where n > 0:\n                              ^\nF:5:5: note: function declared here\ndef lg[n: Int]() -> Int where n > 0:\n    ^\n"), 'u': ('def longname(n: Int):\n    pass\n\n\ndef longname(n: Float64, m: Float64):\n    pass\n\n\ndef main():\n    longname(1, 2, 3)\n', "F:10:5: error: no matching function in call to 'longname'\n    longname(1, 2, 3)\n    ^~~~~~~~\nF:1:5: note: candidate not viable: unexpected argument\ndef longname(n: Int):\n    ^\nF:5:5: note: candidate not viable: unexpected argument\ndef longname(n: Float64, m: Float64):\n    ^\n")}


def test_the_caret_underlines_the_whole_callee_name():
    # The one-character names above hide it: a callee's name is underlined
    # `^~~~` whatever the reason (violated constraint, unexpected argument).
    for key, (src, want) in LONG_NAMES.items():
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, key + '.mojo')
            open(f, 'w').write(src)
            p = subprocess.run([sys.executable, FIRE, 'run', f],
                               capture_output=True, text=True, timeout=300)
            assert p.returncode == 1 and p.stderr.replace(f, 'F') == want, (key, p.stderr)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
