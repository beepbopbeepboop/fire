#!/usr/bin/env python3
"""Regression test: two interpreter faults found by running modular's own integration tests.

1. `f(named=6, **rest)`: the call's explicit keywords REPLACED what the `**rest` spread
   had collected instead of joining it, so the callee lost every key of `rest`
   (modular `variadic_kwargs.mojo`: `kitchen_sink(1, 2, 3, *args, named=6, **kwargs^)`
   raised `KeyError: 'k'`). Pinned against CPython on the same text.

2. `std.io.io._printf[fmt](*args)` is a C `printf` with a comptime format and no newline
   (modular `error_handling.mojo`: `_printf["third: "]()` then `print(0)` is `third: 0`).
   It was an auto-stubbed no-op, so the text vanished.

Both run through `fire.py run` (the interpreter).
"""

import os
import subprocess
import sys
import tempfile
import unittest

from exec_budget import RUN_TIMEOUT_S

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')


def _run(src, suffix):
    d = tempfile.mkdtemp(prefix='interp_kw_')
    p = os.path.join(d, 't' + suffix)
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, FIRE, 'run', p], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S, cwd=d)
    return r.returncode, r.stdout


def _cpython(src):
    d = tempfile.mkdtemp(prefix='interp_kw_ref_')
    p = os.path.join(d, 'ref.py')
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, '-I', p], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return r.returncode, r.stdout


_KWARGS_PY = '''
def callee(a, *args, named, **kwargs):
    print("callee", a, args[0], named, kwargs["k"], kwargs["z"])

def forward(*args, **kwargs):
    callee(1, *args, named=6, **kwargs)

def forward_only_spread(*args, **kwargs):
    callee(1, *args, **kwargs, named=6)

def explicit_wins_order(**kwargs):
    print(sorted(dict(kwargs, extra=1).items()))

forward(40, k=70, z=80)
forward_only_spread(41, k=71, z=81)
explicit_wins_order(a=1)
'''


class InterpreterCallAndPrintf(unittest.TestCase):

    def test_explicit_keywords_join_a_kwargs_spread(self):
        want_rc, want = _cpython(_KWARGS_PY)
        self.assertEqual(want_rc, 0)
        rc, out = _run(_KWARGS_PY, '.py')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, want)

    def test_explicit_keywords_join_a_kwargs_spread_in_mojo(self):
        src = (
            'def callee(a: Int, *args: Int, named: Int, var **kwargs: Int) raises:\n'
            '    print("callee", a, args[0], named, kwargs["k"])\n'
            '\n'
            'def forward(*args: Int, var **kwargs: Int) raises:\n'
            '    callee(1, *args, named=6, **kwargs^)\n'
            '\n'
            'def main() raises:\n'
            '    forward(40, k=70)\n')
        rc, out = _run(src, '.mojo')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, 'callee 1 40 6 70\n')

    def test_printf_writes_its_format_with_no_newline(self):
        src = (
            'from std.io.io import _printf\n'
            '\n'
            'def main():\n'
            '    _printf["third: "]()\n'
            '    print(0)\n'
            '    _printf["n=%d s=%s\\n"](7, "ok")\n'
            '    print("done")\n')
        rc, out = _run(src, '.mojo')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, 'third: 0\nn=7 s=ok\ndone\n')

    def test_other_names_in_std_io_io_still_resolve(self):
        # The shim is an auto-stub with ONE real name; importing anything else from the
        # module must still bind (to the stub) rather than raise.
        src = (
            'from std.io.io import _printf, FileDescriptor\n'
            '\n'
            'def main():\n'
            '    print("ok")\n')
        rc, out = _run(src, '.mojo')
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, 'ok\n')


if __name__ == '__main__':
    unittest.main()
