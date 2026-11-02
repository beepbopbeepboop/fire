#!/usr/bin/env python3
"""CPython's own `glob.py` and `fnmatch.py`, compiled as sibling modules of a driver
and RUN against a real directory tree, required to print exactly what CPython prints
for the same driver.

This is the end-to-end pin for what the generator work was for: `glob.py` is a module
of nested generators that escape their method as values (`wildcard_selector`,
`recursive_selector`), recursive generators, generators handed around as words
(`dirs = _iglob(...)` / `dirs = [dirname]`), `yield from` delegation, a regex built
at run time (`fnmatch.translate`), and `os.scandir`.

Skipped (not failed) when the host Python has no `glob.py`/`fnmatch.py` to copy.
"""
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

DRIVER = r'''
import glob
import fnmatch

ROOT = "@ROOT@"

def main():
    print(sorted(glob.glob(ROOT + '/*.py')))
    print(sorted(glob.glob(ROOT + '/s*/*')))
    print(sorted(glob.glob(ROOT + '/*/*.py')))
    print(sorted(glob.glob(ROOT + '/?.py')))
    print(sorted(glob.glob(ROOT + '/**', recursive=True)))
    print(sorted(glob.glob(ROOT + '/**/*.py', recursive=True)))
    print(sorted(glob.glob('*.py', root_dir=ROOT)))
    print(sorted(glob.glob('**/*.py', root_dir=ROOT, recursive=True)))
    print(sorted(glob.glob('**/', root_dir=ROOT, recursive=True)))
    print(sorted(glob.glob(ROOT + '/nothing*')))
    print(glob.has_magic('a*'), glob.has_magic('plain'), glob.escape('a*b?c'))
    print(fnmatch.translate('*.py'), fnmatch.fnmatch('abc.py', '*.py'), fnmatch.fnmatch('abc.txt', '*.py'))

main()
'''


def main():
    lib = sysconfig.get_paths()['stdlib']
    srcs = [os.path.join(lib, n) for n in ('glob.py', 'fnmatch.py')]
    if not all(os.path.exists(p) for p in srcs):
        print('SKIP  glob compiled: the host Python has no glob.py / fnmatch.py')
        return 0
    work = tempfile.mkdtemp(prefix='glob_compiled_')
    tree = os.path.join(work, 'tree')
    for rel in ('a.py', 'b.txt', 'sub/c.py', 'sub/deep/d.py', 'other/e.txt'):
        path = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w').close()
    prog = os.path.join(work, 'prog')
    os.makedirs(prog)
    for p in srcs:
        shutil.copy(p, prog)
    with open(os.path.join(prog, 'drv.py'), 'w') as fh:
        fh.write(DRIVER.replace('@ROOT@', tree))
    want = subprocess.run([sys.executable, os.path.join(prog, 'drv.py')], capture_output=True, text=True).stdout
    exe = os.path.join(prog, 'drv')
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        os.path.join(prog, 'drv.py'), '-o', exe], capture_output=True, text=True)
    if not os.path.exists(exe):
        print('FAIL  glob compiled: build failed\n' + (b.stdout + b.stderr)[-1500:])
        return 1
    got = subprocess.run([exe], capture_output=True).stdout.decode('utf-8', 'replace')
    if got != want:
        print('FAIL  glob compiled differs from CPython\n--- CPython\n' + want + '--- compiled\n' + got)
        return 1
    print('PASS  glob.py + fnmatch.py compiled and run: 12 lines identical to CPython')
    return 0


if __name__ == '__main__':
    sys.exit(main())
