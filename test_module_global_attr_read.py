#!/usr/bin/env python3
"""A struct-typed module global read through its module: `print(a.BOX.n)`.

the module-global attribute-read bug (run-time AttributeError). The global's type comes from its annotation
(`BOX: Box = Box(1)`), so the module-attribute read is a static read of the global's field. Before the
fix the global had no type in the importing module and the read fell back to a dynamic getattr that
raised `AttributeError: BOX` at run time.

Run directly: python3 test_module_global_attr_read.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    'main.py': 'import a\nprint(a.BOX.n)\nprint(a.X)\n',
    'a.py': ('class Box:\n    def __init__(self, n):\n        self.n = n\n'
             'BOX: Box = Box(1)\nX: int = 5\n'),
}
PY = sys.executable


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as d:
        for name in FILES:
            with open(os.path.join(d, name), 'w') as f:
                f.write(FILES[name])
        expected = subprocess.run([PY, 'main.py'], cwd=d, capture_output=True, text=True)
        build = subprocess.run([PY, os.path.join(HERE, 'fire.py'), 'build', '-o', 'prog', 'main.py'],
                               cwd=d, capture_output=True, text=True)
        if build.returncode != 0:
            failures.append('build failed: ' + build.stderr[-800:])
        else:
            got = subprocess.run([os.path.join(d, 'prog')], capture_output=True, text=True)
            if got.returncode != 0 or got.stdout != expected.stdout:
                failures.append('output %r (exit %d), python gives %r' % (got.stdout, got.returncode, expected.stdout))
    for f in failures:
        print('FAIL', f)
    if not failures:
        print('PASS module.GLOBAL.field reads the struct global statically')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
