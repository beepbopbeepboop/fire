#!/usr/bin/env python3
"""Regression for bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part5:
inside a generator that stays on the C++20-coroutine path, a plain consuming
`for x in <nested generator>(...)` over a nested generator that captures an
enclosing name must compile and run.

Measured on the 2026-11-12 tree: `_cpp_iterable_is_delegatable_generator_call`
accepts the callee (the name is in `_all_generator_names`), so the loop is
routed to `cpp_core._cpp_for_generator_delegate`, which looks the handle up in
`_generator_api` only and refuses with

    `for ... in section(...)` does not consume a generator this compile has
    itself already translated via the C++20-coroutine path

even though the nested generator WAS translated and is registered in
`_nested_generator_api` by `cpp_async._compile_nested_generator_closures`
together with the captures that must be threaded into its `_start` call.

This is the consuming-loop sibling of part4's `yield from` case and the
"`for ... in <generator>` does not consume" family the parent doc has carried
since 2026-09-30.

Fixtures keep the enclosing generator on the coroutine path via
`items = list(analysis)` (see part4's note on why a stack-switch-eligible
fixture would not exercise this defect).

Run: `python3 test_nested_generator_for_in_coroutine.py`
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

# Single-target consuming loop over a captured nested generator.
FLAT_SRC = '''def fmt(analysis: list):
    def section():
        for x in analysis:
            yield x
    for x in section():
        yield x

for v in fmt([1, 2]):
    print(v)
'''

# Tuple-target consuming loop: the target's type comes from the nested
# generator's yielded tuple, so this also pins the tuple-slot agreement.
TUPLE_SRC = '''def fmt(analysis: list):
    items = list(analysis)
    def pairs():
        for x in items:
            yield x, x + 10
    for a, b in pairs():
        yield a + b

for v in fmt([1, 2]):
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
    except Exception as e:
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


def test_for_over_captured_nested_generator_flat_target():
    _check('flat', FLAT_SRC)


def test_for_over_captured_nested_generator_tuple_target():
    _check('tuple', TUPLE_SRC)


if __name__ == '__main__':
    failed = 0
    for fname, fn in list(globals().items()):
        if fname.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS  {fname}')
            except Exception as e:
                failed += 1
                print(f'FAIL  {fname}  {e}')
    if failed:
        print(f'FAILED: {failed}')
        sys.exit(1)
    print('PASS  test_nested_generator_for_in_coroutine')
