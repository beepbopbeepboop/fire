"""Regression pin: a module-level global read through a dotted project import
links.

`from pk.sub.lib import LABEL` is compiled under its own spelling, so the
definer emits the accessor `pk_sub_lib__mojo_global_get_LABEL`. The importer
named it after the file's basename (`lib__mojo_global_get_LABEL`) and the link
failed with an undefined symbol -- the `_types__mojo_global_get_PRESENCE_WORD`
family of the `mojoc` / `selfhost` gate failures (`mojo.middle.types` vs
`types`). Builds a program through the real link-mode driver and runs it.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    d = tempfile.mkdtemp(prefix='dotted_global_')
    os.makedirs(os.path.join(d, 'pk', 'sub'))
    for p in ('pk/__init__.py', 'pk/sub/__init__.py'):
        open(os.path.join(d, p), 'w').close()
    with open(os.path.join(d, 'pk', 'sub', 'lib.py'), 'w') as f:
        f.write('LABEL: str = "hello"\n'
                'def g(x: int) -> int:\n    return x + 1\n')
    with open(os.path.join(d, 'main.py'), 'w') as f:
        f.write('from pk.sub.lib import LABEL, g\n'
                'def f() -> str:\n    return LABEL\n'
                'print(f(), g(2))\n')
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'main.py', '-o', out], cwd=d, capture_output=True, text=True)
    text = r.stdout + r.stderr
    if 'link failed' in text.lower() or 'Linking failed' in text or not os.path.exists(out):
        print('FAIL: link-mode build of a dotted global import did not link')
        print(text[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout.strip() != 'hello 3':
        print('FAIL: program printed %r, CPython prints %r' % (run.stdout, 'hello 3'))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
