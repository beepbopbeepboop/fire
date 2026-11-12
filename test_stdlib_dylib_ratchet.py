#!/usr/bin/env python3
"""`stdlib-dylib` must FAIL when the built stdlib dylib references a `_std_`
symbol it does not define.

Regression for the silent hole in the stdlib-dylib gate: the job linked the
dylib with `-undefined dynamic_lookup` and then read only the `skip` list, so a
dylib that referenced `_std_iter___init____PeekableIterator_peek` — the class
tables named the refused generic-method bodies' symbols, which no translation
unit defines (fixed in 2b7ac5562) — passed the job while every compiled program
aborted at load with dyld's "symbol not found". The tree's own instruments
(`nm -u` against `nm -gU`, the same two commands the bug doc's repro uses) were
available and unrun.

This test builds a SYNTHETIC dylib with exactly that shape — it references
`_std_iter___init____PeekableIterator_peek` and never defines it — and asserts
`tools/stdlib_dylib_ratchet.unresolved_stdlib_refs` names it, by the exact
symbol the bug was about. It then builds the same dylib with the symbol
DEFINED and asserts the check is quiet, so the red above cannot come from the
check firing on every dylib.

No stdlib build is involved; the two dylibs are a few lines of C.

    python3 test_stdlib_dylib_ratchet.py
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)

from build_config import find_gcc  # noqa: E402
from tools.stdlib_dylib_ratchet import unresolved_stdlib_refs  # noqa: E402

# The symbol the bug doc names. `nm` on Mach-O prints a C symbol with one
# leading underscore added, so the C identifier differs per platform; `PEEK`
# is nm's spelling in both worlds, and what the check must report.
PEEK = '_std_iter___init____PeekableIterator_peek'

if platform.system() == 'Darwin':
    _CALL = PEEK[1:]
else:
    _CALL = PEEK


def _probe_src(defined):
    parts = ['#include <stdint.h>\n']
    if defined:
        parts.append('int64_t %s(int64_t it) { return it + 1; }\n' % _CALL)
    else:
        parts.append('extern int64_t %s(int64_t it);\n' % _CALL)
    parts.append('__attribute__((unused)) int64_t mojo_peek_probe(int64_t x) '
                 '{ return %s(x); }\n' % _CALL)
    return ''.join(parts)


def _build_probe_dylib(workdir, defined):
    os.makedirs(workdir)
    src = os.path.join(workdir, 'probe.c')
    obj = os.path.join(workdir, 'probe.o')
    with open(src, 'w') as f:
        f.write(_probe_src(defined))
    gcc = find_gcc()
    subprocess.run([gcc, '-fPIC', '-c', '-o', obj, src], check=True,
                   capture_output=True)
    if platform.system() == 'Darwin':
        dylib = os.path.join(workdir, 'probe.dylib')
        subprocess.run([gcc, '-dynamiclib',
                        '-install_name', '@rpath/probe.dylib',
                        '-undefined', 'dynamic_lookup',
                        '-o', dylib, obj], check=True, capture_output=True)
    else:
        dylib = os.path.join(workdir, 'probe.so')
        subprocess.run([gcc, '-shared', '-o', dylib, obj], check=True,
                       capture_output=True)
    return dylib


def main():
    failures = []
    with tempfile.TemporaryDirectory(prefix='std_dylib_ratchet_') as wd:
        missing_dylib = _build_probe_dylib(os.path.join(wd, 'missing'),
                                           defined=False)
        defined_dylib = _build_probe_dylib(os.path.join(wd, 'defined'),
                                           defined=True)
        got = unresolved_stdlib_refs(missing_dylib)
        if got != [PEEK]:
            failures.append(
                'undefined-reference check on a dylib that references %s but does not '
                'define it reported %r, expected exactly [%r]' % (PEEK, got, PEEK))
        got = unresolved_stdlib_refs(defined_dylib)
        if got != []:
            failures.append(
                'undefined-reference check on a dylib that DEFINES %s reported %r, '
                'expected []' % (PEEK, got))
    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_dylib_ratchet: the check names %s when the dylib '
          'references but does not define it, and is quiet when it does' % PEEK)
    return 0


if __name__ == '__main__':
    sys.exit(main())
