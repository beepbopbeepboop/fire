"""Regression pin: a call to an imported module's defaulted free function pads
the omitted arguments with the callee's own defaults, whatever order the
modules compile in.

`_func_param_defaults` is registered by bare name while a definer compiles, so
an importer compiled earlier (an import cycle) or one that sees a same-named
homonym found no defaults and padded `0`/NULL: the self-hosted compiler lost
the `indent: int = 2` of `build.assign(...)` and printed every statement at
column 0. The `<alias>.<fn>` resolution now records the definer's defaults.
Builds through the real link-mode driver and runs the program.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

FILES = {
    'a.py': 'from b import g\n\n'
            'def assign(a: int, note: str = "n", indent: int = 2) -> str:\n'
            '    return note + str(indent) + str(a)\n\n'
            'def run() -> str:\n    return g(7)\n',
    'b.py': 'import a as build\n\n'
            'def g(n: int) -> str:\n    return build.assign(n)\n',
    'main.py': 'from a import run\nprint(run())\n',
}


def main() -> int:
    d = tempfile.mkdtemp(prefix='imported_default_padding_')
    for name, text in FILES.items():
        with open(os.path.join(d, name), 'w') as f:
            f.write(text)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'main.py', '-o', out], cwd=d, capture_output=True, text=True)
    if not os.path.exists(out):
        print('FAIL: did not build')
        print((r.stdout + r.stderr)[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout.strip() != 'n27':
        print('FAIL: program printed %r, CPython prints %r' % (run.stdout, 'n27'))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
