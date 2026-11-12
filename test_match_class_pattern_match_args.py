#!/usr/bin/env python3
"""Regression for bugs/mid/COMPILE_FAIL_Tools_cases_generator_analyzer-part1:
positional class patterns (`case C(x, y):`) must bind through
`C.__match_args__`, not through the capture names.

CPython: `isinstance(subject, C)`, then capture i is `subject.<__match_args__[i]>`.
The interpreter (`fire.py run`) already does this; the compiled path used to
bind `subject.<capture name>` and never read `__match_args__`.

Fixtures (expected values verified against CPython 3.14 semantics):

* reversed: `__match_args__ = ('b', 'a')`, captures (p, q) -> p = b, q = a.
  Expected `2-1`. The compiled path used to die with `AttributeError: p`.
* no __match_args__ at all: CPython raises `TypeError` on the match. The
  compiled path must NOT silently bind a same-named attribute: either it
  refuses at compile time or the binary fails; it must not exit 0 with
  output that depends on a bound value.
* too many sub-patterns for __match_args__: CPython raises `TypeError`;
  the same rule as above.

Run: `python3 test_match_class_pattern_match_args.py`
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import driver
from exec_budget import RUN_TIMEOUT_S

SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

REVERSED_SRC = '''class P:
    __match_args__ = ('b', 'a')
    def __init__(self, a: int, b: int):
        self.a = a
        self.b = b

def f(x: P) -> str:
    match x:
        case P(p, q):
            return str(p) + "-" + str(q)
        case _:
            return "no"

print(f(P(1, 2)))
'''

NO_MATCH_ARGS_SRC = '''class Q:
    def __init__(self, n: int):
        self.n = n

def f(x: Q) -> int:
    match x:
        case Q(n):
            return n
        case _:
            return -1

print(f(Q(3)))
'''

TOO_MANY_SRC = '''class R:
    __match_args__ = ('n',)
    def __init__(self, n: int, m: int):
        self.n = n
        self.m = m

def f(x: R) -> int:
    match x:
        case R(a, b):
            return a + b
        case _:
            return -1

print(f(R(1, 2)))
'''


def _cpython_run(src: str) -> tuple[int, str]:
    """Return (exit code, stdout) of CPython on the same text."""
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    p = os.path.join(tmp, 'ref.py')
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, '-I', p], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    return r.returncode, r.stdout


def _interp_run(src: str) -> tuple[int, str]:
    """`fire.py run` (the interpreter oracle) on the same text."""
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    p = os.path.join(tmp, 'interp.py')
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'run', p],
                       capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return r.returncode, r.stdout


def _compiled_run(src: str) -> tuple[str, int | None, str]:
    """Compile through driver.compile_program and run the binary.

    Returns ('refused', None, reason) when the compiler refuses the program,
    else ('built', exit code, stdout)."""
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    src_path = os.path.join(tmp, 'prog.py')
    with open(src_path, 'w') as f:
        f.write(src)
    exe = os.path.join(tmp, 'prog.exe')
    try:
        rc = driver.compile_program(src_path, src, output=exe, run=False)
    except Exception as e:  # a compile-time refusal is an acceptable outcome
        return 'refused', None, str(e)
    if rc is None:
        return 'refused', None, 'driver.compile_program returned None'
    r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return 'built', r.returncode, r.stdout + r.stderr


def test_reversed_match_args_binds_by_position_name():
    want_code, want = _cpython_run(REVERSED_SRC)
    assert want_code == 0 and want == '2-1\n', (want_code, want)
    code, got = _interp_run(REVERSED_SRC)
    assert code == 0 and got == want, f'interpreter printed {got!r}'
    status, rcode, out = _compiled_run(REVERSED_SRC)
    assert status == 'built', f'compiler refused a supported shape: {out}'
    assert rcode == 0 and out == want, (
        f'compiled binary exit {rcode}, printed {out!r}; CPython printed {want!r}')


def test_missing_match_args_does_not_bind_silently():
    want_code, _ = _cpython_run(NO_MATCH_ARGS_SRC)
    assert want_code != 0, 'CPython must reject this shape at run time'
    status, rcode, out = _compiled_run(NO_MATCH_ARGS_SRC)
    if status == 'refused':
        return
    assert rcode != 0, (
        f'class without __match_args__ bound a same-named attribute and '
        f'exited 0 with {out!r}; CPython raises TypeError')


def test_too_many_sub_patterns_does_not_bind_silently():
    want_code, _ = _cpython_run(TOO_MANY_SRC)
    assert want_code != 0, 'CPython must reject this shape at run time'
    status, rcode, out = _compiled_run(TOO_MANY_SRC)
    if status == 'refused':
        return
    assert rcode != 0, (
        f'too many positional sub-patterns exited 0 with {out!r}; '
        f'CPython raises TypeError')


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS  {name}')
            except Exception as e:
                failed += 1
                print(f'FAIL  {name}  {e}')
    if failed:
        print(f'FAILED: {failed}')
        sys.exit(1)
    print('PASS  test_match_class_pattern_match_args')
