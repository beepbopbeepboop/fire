"""Regression pin: `sys.maxsize` read as a VALUE compiles.

`mojo/middle/comptime.py` runs `_HOST_IS_32BIT = sys.maxsize <= 2**32` at import
time, so the self-hosted compiler died on startup with a fatal
`AttributeError: maxsize` (the produced binary of `test_selfhost.py` exited 1
on a two-line program). Builds a program through the real driver and runs it.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = ('import sys\nBIG = sys.maxsize <= 2**32\n'
       'def f() -> int:\n    return sys.maxsize\n'
       'print(BIG, f() == 9223372036854775807)\n')


def main() -> int:
    d = tempfile.mkdtemp(prefix='sys_maxsize_')
    with open(os.path.join(d, 'm.py'), 'w') as f:
        f.write(SRC)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'm.py', '-o', out], cwd=d, capture_output=True, text=True)
    if not os.path.exists(out):
        print('FAIL: did not build\n' + (r.stdout + r.stderr)[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout.strip() != 'False True':
        print('FAIL: printed %r (stderr %r), CPython prints %r'
              % (run.stdout, run.stderr, 'False True'))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
