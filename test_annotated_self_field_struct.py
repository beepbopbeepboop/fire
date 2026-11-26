"""Regression pin: `self.f: Cls = make()` types the field `Cls *`.

The field's type came from the VALUE, and a call to a function defined later (or
`self`) has no type yet, so the field was the erased `int64_t` and
`self.lhs.show()` was a method call on a word: the identity stub. The
self-hosted compiler printed `\\xd3\\b = 4368822592;` for every statement because
the IR's `Instr.lhs: Ex = ex_none()` was such a field. An explicit annotation
that names a known struct is the field's type when the value says nothing.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '''class Ex:
    def __init__(self, n: str):
        self.name: str = n
        self.next: Ex = self

    def show(self) -> str:
        return self.name

class Instr:
    def __init__(self, a: str, b: str):
        self.lhs: Ex = make(a)
        self.rhs: Ex = make(b)

    def show(self) -> str:
        return self.lhs.show() + ' = ' + self.rhs.show() + ';'

def make(n: str) -> Ex:
    return Ex(n)

print(Instr('x', 'y').show())
'''


def main() -> int:
    d = tempfile.mkdtemp(prefix='ann_self_field_')
    with open(os.path.join(d, 'm.py'), 'w') as f:
        f.write(SRC)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'm.py', '-o', out], cwd=d, capture_output=True, text=True)
    if not os.path.exists(out):
        print('FAIL: did not build\n' + (r.stdout + r.stderr)[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout != 'x = y;\n':
        print('FAIL: printed %r, CPython prints %r' % (run.stdout, 'x = y;\n'))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
