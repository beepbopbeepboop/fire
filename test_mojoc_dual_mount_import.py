#!/usr/bin/env python3
"""Regression: one .mojoc artifact reached under two names is one package.

Modular's `import_dual_mount_mojoc.mojo`: a package is precompiled, its
sources deleted, and a second name for the same artifact is created with a
symlink in the same import root. Importing via both names must resolve the
alias before the artifact is read (so the second name costs no second load),
warn about the duplicate, and keep using the first/canonical name.

Expected diagnostics/behavior (from the modular fixture):
  warning: 'dup' and 'utils' name the same package; remove the duplicate
           import root or file that reaches it twice
  note: 'utils' is the name used in error messages and debug info

The import itself must not be rejected as missing/ambiguous because the
package was reached under two names.
"""

import io
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

ROOT = os.path.join(HERE, '.tmp', 'mojoc_dual_mount')

PKG = {
    '__init__.mojo': '# pkg\n',
    'a.mojo': (
        'struct Thing:\n'
        '    var x: Int\n'
        '\n'
        '    def __init__(out self):\n'
        '        self.x = 7\n'
        '\n'
        '\n'
        'def make() -> Thing:\n'
        '    return Thing()\n'),
}

# Import via both names: the same package reached as utils and as dup.
CLIENT = (
    'from utils.a import Thing\n'
    'from dup.a import make\n'
    '\n'
    '\n'
    'def main():\n'
    '    var t: Thing = make()\n'
    '    print(t.x)\n')

WARN = ("warning: 'dup' and 'utils' name the same package; remove the "
        "duplicate import root or file that reaches it twice")
NOTE = "note: 'utils' is the name used in error messages and debug info"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def _fixture(name):
    base = os.path.join(ROOT, name)
    if os.path.exists(base):
        shutil.rmtree(base)
    src = os.path.join(base, 'src', 'utils')
    lib = os.path.join(base, 'lib')
    os.makedirs(lib, exist_ok=True)
    for fn, text in PKG.items():
        _write(os.path.join(src, fn), text)
    out = os.path.join(lib, 'utils.mojoc')
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'precompile', src,
         '-o', out],
        capture_output=True, text=True)
    assert r.returncode == 0, f'precompile failed:\n{r.stdout}\n{r.stderr}'
    shutil.rmtree(os.path.join(base, 'src'))
    os.symlink('utils.mojoc', os.path.join(lib, 'dup.mojoc'))
    return base, lib


def _compile_consumer(lib, text, name='main.mojo'):
    path = os.path.join(lib, name)
    _write(path, text)
    buf = io.StringIO()
    with redirect_stderr(buf):
        try:
            code = compile_to_gimple(text, do_imports=True, filename=path)
            err = None
        except Exception as e:
            code = None
            err = e
    return code, err, buf.getvalue()


def test_dual_mount_mojoc_warns_and_resolves():
    _base, lib = _fixture('warn')
    code, err, stderr = _compile_consumer(lib, CLIENT)
    out = stderr
    if err is not None:
        out = out + '\n' + str(err)
    assert WARN in out, f'expected duplicate-package warning, got:\n{out}'
    assert NOTE in out, f'expected canonical-name note, got:\n{out}'
    # The alias must be resolved, not rejected as a missing/unknown module.
    if err is not None:
        msg = str(err)
        assert 'unable to locate module' not in msg, msg
        assert 'No module named' not in msg, msg


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
