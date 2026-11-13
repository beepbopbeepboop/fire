#!/usr/bin/env python3
"""Regression for bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4:
inside a generator that stays on the C++20-coroutine path, `yield from` a
NESTED generator that captures an enclosing name must compile and run.

Measured on the 2026-11-12 tree: the nested generator is claimed by
`cpp_async._compile_nested_generator_closures` (registered in
`_nested_generator_api` with its captures threaded as trailing parameters),
but `cpp_core._cpp_yield_from` only recognises callees registered in
`_generator_api`, so the call falls through to the plain-collection path and
refuses with

    a call to unresolved callee 'section(...)' is not supported in a compiled
    generator/coroutine body

This is exactly the `c_analyzer/__main__.py` shape (`fmt_summary` doing
`yield from section('types')` where `section` reads `fmt_summary`'s `items`),
reduced to a minimal program.

Both fixtures deliberately keep the enclosing generator on the coroutine path
(a local initialised from `list(<param>)`, as `__main__.py`'s
`items = list(analysis)` is). The same shapes are accepted when A3 rewrites the
enclosing generator to a stack-switch body, so a fixture that fell into that
path would not exercise this defect.

Run: `python3 test_nested_generator_yield_from_in_coroutine.py`
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

# Minimal shape: one captured list local, delegated to via `yield from`.
MINIMAL_SRC = '''def fmt(analysis: list):
    items = list(analysis)
    def section():
        for x in items:
            yield x
    yield from section()

for v in fmt([1, 2]):
    print(v)
'''

# The parent file's shape: two `yield from` sites, a captured list local, and
# the delegated generator yields strings computed from its own parameter.
MAIN_SHAPE_SRC = '''def build_section(name: str, groupitems: list):
    def render():
        yield ''
        yield f'{name}:'
        for item in groupitems:
            yield f'{item}'
    return groupitems, render

def fmt_summary(analysis: list):
    items = list(analysis)
    def section(name: str):
        _, render = build_section(name, items)
        yield from render()
    yield from section('types')
    yield from section('functions')

for v in fmt_summary([1, 2]):
    print(v)
'''


def _cpython_run(src: str) -> tuple[int, str]:
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    p = os.path.join(tmp, 'ref.py')
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, '-I', p], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    return r.returncode, r.stdout


def _compiled_run(src: str) -> tuple[str, int | None, str]:
    """('refused', None, reason) or ('built', exit code, stdout+stderr)."""
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    src_path = os.path.join(tmp, 'prog.py')
    with open(src_path, 'w') as f:
        f.write(src)
    exe = os.path.join(tmp, 'prog.exe')
    try:
        rc = driver.compile_program(src_path, src, output=exe, run=False)
    except Exception as e:          # a compile-time refusal is the current state
        return 'refused', None, str(e)
    if rc is None:
        return 'refused', None, 'driver.compile_program returned None'
    r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return 'built', r.returncode, r.stdout + r.stderr


def _check(name: str, src: str):
    want_code, want = _cpython_run(src)
    assert want_code == 0, (name, 'CPython fixture failed', want_code)
    status, rcode, out = _compiled_run(src)
    assert status == 'built', f'{name}: compiler refused a supported shape: {out}'
    assert rcode == 0 and out == want, (
        f'{name}: compiled binary exit {rcode}, printed {out!r}; '
        f'CPython printed {want!r}')


def test_yield_from_captured_nested_generator_in_coroutine_generator():
    _check('minimal', MINIMAL_SRC)


def test_yield_from_captured_nested_generator_main_shape():
    _check('main-shape', MAIN_SHAPE_SRC)


CASES = {
    'minimal': test_yield_from_captured_nested_generator_in_coroutine_generator,
    'main-shape': test_yield_from_captured_nested_generator_main_shape,
}


if __name__ == '__main__':
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in CASES:
            print(f'unknown case {name!r}; expected one of {sorted(CASES)}')
            sys.exit(2)
        CASES[name]()
        print(f'PASS  {name}')
        sys.exit(0)
    failed = 0
    for fname, fn in CASES.items():
        try:
            fn()
            print(f'PASS  {fname}')
        except Exception as e:
            failed += 1
            print(f'FAIL  {fname}  {e}')
    if failed:
        print(f'FAILED: {failed}')
        sys.exit(1)
    print('PASS  test_nested_generator_yield_from_in_coroutine')
