#!/usr/bin/env python3
"""Two modules declare a module global of the SAME name with DIFFERENT struct types, and one
imports the other: each module's own global must keep its own type (bugs/GIR_type_solver_precision.md,
step 4b; the same shape as `sty.BOOL` vs `mojo/ir/types.py`'s `BOOL`).

Before the fix, the importing module's owner conclusion for `BOX` deferred to the shared cdecl the
imported module had written (`Tag *`), so the importer's store cast its `Box *` value to `Tag *`
and gcc rejected the translation unit. The check: the built binary prints what `python3 main.py`
prints.

Run directly: python3 test_global_homonym_struct.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    'main.py': 'import a\nimport b\nprint(a.box_n())\nprint(b.box_s())\n',
    'a.py': ('class Box:\n    def __init__(self, n):\n        self.n = n\n'
             'BOX: Box = Box(1)\n'
             'def box_n():\n    return BOX.n\n'
             'import b\n'),
    'b.py': ('class Tag:\n    def __init__(self, s):\n        self.s = s\n'
             'BOX: Tag = Tag("y")\n'
             'def box_s():\n    return BOX.s\n'),
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
            if got.stdout != expected.stdout:
                failures.append('output %r, python gives %r' % (got.stdout, expected.stdout))
    for f in failures:
        print('FAIL', f)
    if not failures:
        print('PASS homonym module globals keep their own struct types')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
