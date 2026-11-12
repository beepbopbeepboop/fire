#!/usr/bin/env python3
"""Regression: `dirname, basename = os.path.split(p)` on an untyped (word) `p`
read its unpacked elements as plain int64 numbers, so `if not dirname:` was
lowered as `dirname == 0`. An EMPTY str head (`os.path.split('*.py')` gives
`''`) is a live non-NULL pointer, so the test answered "not empty" and the
branch was taken wrongly. The element of a word split is a str OR a bytes
part -- a word of unknown kind -- and must be tested with `mojo_truthy_word`.

Bug doc: bugs/CODEGEN_coro_a3_os_path_split_empty_head_truthy.md (default
stackswitch coroutine path; the generator body is ordinary codegen).

Each case is one generator whose output is compared line-for-line with what
CPython prints for the same source. The bytes cases count their yields rather
than printing them: printing a bytes word yielded from a generator is a
separate, still-open defect (bugs/CODEGEN_coro_a3_generator_bytes_word_print.md). Built with `fire.py build` (no
MOJO_CORO setting), so the default coroutine path is what is under test.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PROGRAM = '''\
import os

def g_split(pathname):
    dirname, basename = os.path.split(pathname)
    if not dirname:
        yield basename
        return
    yield dirname
    yield basename

def count_yields(pathname):
    c = 0
    for n in g_split(pathname):
        c += 1
    return c

def main():
    for n in g_split('a/b.py'):
        print(n)
    for n in g_split('*.py'):
        print(n)
    print(count_yields(b'*.py'))
    print(count_yields(b'a/b.py'))
'''

def cpython_output(oracle):
    # The Mojo program relies on `main` being auto-invoked; CPython needs the call.
    with open(oracle, 'w') as f:
        f.write(PROGRAM + '\nmain()\n')
    r = subprocess.run([sys.executable, '-I', oracle], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('CPython failed on the oracle program:\n' + r.stderr)
    return r.stdout.split('\n')


def main():
    tmp = os.path.join(HERE, '.tmp')
    os.makedirs(tmp, exist_ok=True)
    drv = os.path.join(tmp, 'split_word_truthy.mojo')
    with open(drv, 'w') as f:
        f.write(PROGRAM)
    want = cpython_output(os.path.join(tmp, 'split_word_truthy_oracle.py'))
    exe = drv[:-len('.mojo')]
    # A binary left by an earlier run must not stand in for this build.
    if os.path.exists(exe):
        os.remove(exe)
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv, '-o', exe],
                       capture_output=True, text=True)
    if b.returncode != 0 or not os.path.exists(exe):
        print('FAIL build (exit %d)\n' % b.returncode, (b.stdout + b.stderr)[-1500:])
        return 1
    run = subprocess.run([exe], capture_output=True, text=True)
    got = run.stdout.split('\n')
    if got != want:
        print('FAIL output differs')
        print('want:', want)
        print('got: ', got)
        return 1
    print('PASS os.path.split word-element truthiness (%d lines)' % (len(want) - 1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
