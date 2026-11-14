#!/usr/bin/env python3
"""Regression for the `str(<struct>)` / `repr(<struct>)` guard under `__GIMPLE`.

`user_dunder_repr_call` (mojo/middle/calls_shared.py) used to emit the
receiver-null guard as a parenthesized C conditional expression assigned to a
fresh temp:

    _t25 = (_t23 ? CacheEntry___str__ (_t23) : _slit_10243);

gcc `-fgimple` rejects both spellings in a `__GIMPLE`-tagged body: a
parenthesized conditional is not a legal operand ("expected expression
before '(' token"), and a call is not a legal ternary operand ("invalid
operands in ternary operation"). The guard is now real control flow
(`_select_val` in mojo/backend_gimple/emit_resolve.py, the same three-block
shape as `_lower_TernaryExpr`), with the dunder call lazy inside the taken
branch only.

The fixture puts the call in a struct method (a `__GIMPLE` body) — a
top-level function is not tagged and would not reproduce. Both the `str`
route (`str(x)`, `%s`, f-strings) and the `repr` route (`repr(x)`, `%r`) go
through `user_dunder_repr_call`, so both are checked.

Before the fix this exits non-zero with gcc's "expected expression before
'(' token" on the `", ".join(...)` line; after it, the compiled binary
prints what CPython prints on the same source.
"""
import os
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from gimple_codegen import compile_to_gimple

RUNTIME = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME, 'fire_runtime.c')
SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)
GCC = find_gcc()

SRC_STR = '''class Item:
    def __init__(self, n: int):
        self.n = n
    def __str__(self) -> str:
        return "I" + str(self.n)

class Holder:
    def __init__(self):
        self.items = [Item(1), Item(2)]
    def dump(self) -> None:
        print(", ".join([str(c) for c in self.items]))

Holder().dump()
'''

SRC_REPR = '''class Item:
    def __init__(self, n: int):
        self.n = n
    def __repr__(self) -> str:
        return "R" + str(self.n)

class Holder:
    def __init__(self):
        self.items = [Item(1), Item(2)]
    def dump(self) -> None:
        print(", ".join([repr(c) for c in self.items]))

Holder().dump()
'''


def _cpython_stdout(src: str) -> str:
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        p = os.path.join(tmp, 'prog_ref.py')
        with open(p, 'w') as f:
            f.write(src)
        r = subprocess.run([sys.executable, p], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f'CPython reference run failed: {r.stderr}')
        return r.stdout
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)


def _compiled_stdout(src: str, label: str) -> str:
    c = compile_to_gimple(src, do_imports=False)
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        cfile = os.path.join(tmp, 'prog.c')
        exe = os.path.join(tmp, 'prog')
        with open(cfile, 'w') as f:
            f.write(c)
        r = subprocess.run([GCC, '-fgimple', '-I' + RUNTIME, '-o', exe, cfile, RUNTIME_C],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(
                f'gcc -fgimple compile failed for the {label} fixture:\n{r.stderr}\n---\n{c}')
        p = subprocess.run([exe], capture_output=True, text=True)
        if p.returncode != 0:
            raise AssertionError(f'compiled {label} binary exited {p.returncode}: {p.stderr}')
        return p.stdout
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)


def test_paren_ternary_gimple_operand():
    for label, src in (('str', SRC_STR), ('repr', SRC_REPR)):
        expected = _cpython_stdout(src)
        got = _compiled_stdout(src, label)
        assert got == expected, (
            f'{label} fixture: compiled binary printed {got!r}, '
            f'CPython printed {expected!r}')


if __name__ == '__main__':
    try:
        test_paren_ternary_gimple_operand()
    except AssertionError as e:
        print(f'FAIL  test_paren_ternary_gimple_operand  {e}')
        sys.exit(1)
    except Exception as e:
        print(f'FAIL  test_paren_ternary_gimple_operand  {e}')
        sys.exit(1)
    print('PASS  test_paren_ternary_gimple_operand')
