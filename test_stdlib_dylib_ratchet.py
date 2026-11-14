#!/usr/bin/env python3
"""`stdlib-dylib` must FAIL when the built stdlib dylib does not LOAD, and must
not fail on the lazy call references its documented source fallback covers.

Regression for the silent hole in the stdlib-dylib gate: the job linked the
dylib with `-undefined dynamic_lookup` and then read only the `skip` list, so a
dylib whose CLASS TABLES named `_std_iter___init____PeekableIterator_peek` —
a symbol no translation unit defines (fixed in 2b7ac5562) — passed the job
while every compiled program aborted at load with dyld's "symbol not found".

The fatal shape is a symbol ADDRESS stored in data (the class tables, the
reflection table): dyld binds those eagerly. A plain call is bound lazily and
is therefore not a load failure — measured on this tree, the real stdlib dylib
has 50 such lazy references and `dlopen(RTLD_LAZY)` succeeds, while a client
falls back to source for them (the dylib "need not be complete — it must only
link"). This test pins BOTH halves of that distinction, because the gate must
catch the first without reding on the second:

  - a dylib that stores `&peek` in data and never defines `peek`
    -> `dylib_load_error` fails and names the symbol;
  - the same dylib with `peek` defined -> it loads;
  - a dylib that only CALLS `peek` and never defines it -> it loads, and
    `unresolved_stdlib_refs` still names `peek` (the reported lazy gap).

No stdlib build is involved; the dylibs are a few lines of C.

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
from tools.stdlib_dylib_ratchet import (  # noqa: E402
    dylib_load_error, unresolved_stdlib_refs)

# The symbol the bug doc names. `nm` on Mach-O prints a C symbol with one
# leading underscore added, so the C identifier differs per platform; `PEEK`
# is nm's spelling in both worlds, and what the checks must report.
PEEK = '_std_iter___init____PeekableIterator_peek'

if platform.system() == 'Darwin':
    _CALL = PEEK[1:]
else:
    _CALL = PEEK


def _probe_src(shape, defined):
    """`shape` is 'call' (a lazy reference) or 'data' (an eager one)."""
    parts = ['#include <stdint.h>\n']
    if defined:
        parts.append('int64_t %s(int64_t it) { return it + 1; }\n' % _CALL)
    else:
        parts.append('extern int64_t %s(int64_t it);\n' % _CALL)
    if shape == 'data':
        # Taking the ADDRESS in a pointer initializer is what the class and
        # reflection tables do. `used` keeps a compiler from folding it away.
        parts.append('__attribute__((used)) void *mojo_peek_probe_addr = '
                     '(void *)&%s;\n' % _CALL)
    else:
        parts.append('__attribute__((unused)) int64_t mojo_peek_probe(int64_t x) '
                     '{ return %s(x); }\n' % _CALL)
    return ''.join(parts)


def _build_probe_dylib(workdir, shape, defined):
    os.makedirs(workdir)
    src = os.path.join(workdir, 'probe.c')
    obj = os.path.join(workdir, 'probe.o')
    with open(src, 'w') as f:
        f.write(_probe_src(shape, defined))
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
        data_missing = _build_probe_dylib(os.path.join(wd, 'data_missing'),
                                          'data', defined=False)
        data_defined = _build_probe_dylib(os.path.join(wd, 'data_defined'),
                                          'data', defined=True)
        call_missing = _build_probe_dylib(os.path.join(wd, 'call_missing'),
                                          'call', defined=False)
        call_defined = _build_probe_dylib(os.path.join(wd, 'call_defined'),
                                          'call', defined=True)

        err = dylib_load_error(data_missing)
        if not err or PEEK not in err:
            failures.append(
                'a dylib that stores &%s in data and never defines it must FAIL '
                'to load and name the symbol; got %r' % (PEEK, err))

        err = dylib_load_error(data_defined)
        if err is not None:
            failures.append(
                'a dylib that stores &%s in data and DEFINES it must load; '
                'dylib_load_error said %r' % (PEEK, err))

        err = dylib_load_error(call_missing)
        if err is not None:
            failures.append(
                'a dylib that only CALLS %s and never defines it is a lazy '
                'reference and must still LOAD (the client falls back to '
                'source); dylib_load_error said %r' % (PEEK, err))

        got = unresolved_stdlib_refs(call_missing)
        if got != [PEEK]:
            failures.append(
                'the static report on a dylib that CALLS %s but does not define '
                'it must name it; reported %r, expected exactly [%r]'
                % (PEEK, got, PEEK))

        got = unresolved_stdlib_refs(call_defined)
        if got != []:
            failures.append(
                'the static report on a dylib that DEFINES %s must be empty; '
                'reported %r' % (PEEK, got))
    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_dylib_ratchet: an eager (data) reference to undefined '
          '%s fails the load check by name, its definition loads, and a lazy '
          '(call) reference loads while the static report still names it' % PEEK)
    return 0


if __name__ == '__main__':
    sys.exit(main())
