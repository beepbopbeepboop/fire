"""Regression pin: `mod.Class.method(args)` through a module alias calls the method.

`import pk.lat as L; L.Lat.is_x(t)`: the receiver `L.Lat` is a class reference,
which lowers to the zero placeholder, and `.is_x` on that word was the
unknown-method stub, so every call returned 0 (`True` came out `False`,
`join('a', 'b')` came out `'a'`). The compiler calls `TypeLattice.<predicate>`
through `gimple_ctypes` about 2600 times, so the self-hosted compiler's type
tests were all false: every function was emitted with no return type and `print`
of an int took the wrong arm.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = '''class Lat:
    @classmethod
    def is_x(cls, t: str) -> bool:
        return t == 'x'

    @classmethod
    def join(cls, a: str, b: str) -> str:
        return a if a == b else 'dyn'

    @staticmethod
    def twice(n: int) -> int:
        return n * 2
'''
SRC = '''import pk.lat as L

def f(t: str) -> bool:
    return L.Lat.is_x(t)

print(f('x'), f('y'), L.Lat.join('a', 'a'), L.Lat.join('a', 'b'), L.Lat.twice(4))
'''
WANT = 'True False a dyn 8\n'


def main() -> int:
    d = tempfile.mkdtemp(prefix='alias_class_method_')
    os.makedirs(os.path.join(d, 'pk'))
    open(os.path.join(d, 'pk', '__init__.py'), 'w').close()
    with open(os.path.join(d, 'pk', 'lat.py'), 'w') as f:
        f.write(LIB)
    with open(os.path.join(d, 'm.py'), 'w') as f:
        f.write(SRC)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'm.py', '-o', out], cwd=d, capture_output=True, text=True)
    if not os.path.exists(out):
        print('FAIL: did not build\n' + (r.stdout + r.stderr)[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout != WANT:
        print('FAIL: printed %r, CPython prints %r' % (run.stdout, WANT))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
