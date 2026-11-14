"""Regression: async context manager with non-scalar __aenter__ return in
compiled module/codegen path (cpp coroutine backend).

Covers COMPILE_FAIL_Lib_contextlib boxed non-scalar __aenter__ return / async with in cpp coroutine codegen (part2)
acceptance: async with CM() as v where __aenter__ returns a non-scalar value
must compile and run correctly, with the returned value observed at the use site.
"""
import os
import subprocess
import tempfile

os.environ.setdefault('MOJO_CORO', 'cpp')

import gimple_codegen
import fire
from build_config import find_gcc, find_gxx
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')
ASYNC_RUNTIME_CPP = os.path.join(RUNTIME_DIR, 'fire_async_runtime.cpp')

_PASS = 0
_FAIL = 0


def check(name, cond, detail=''):
    global _PASS, _FAIL
    if cond:
        print(f'PASS  {name}')
        _PASS += 1
    else:
        print(f'FAIL  {name}  {detail}')
        _FAIL += 1


def _build_async_program(mojo_src: str) -> str:
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
        mojo_src, filename='prog.mojo')
    if not cpp_code:
        raise RuntimeError('expected non-empty generated .cpp for async source')

    wd = tempfile.mkdtemp(prefix='mojo_async_with_aenter_boxed_')
    c_path = os.path.join(wd, 'prog.c')
    cpp_path = os.path.join(wd, 'prog_async.cpp')
    with open(c_path, 'w') as f:
        f.write(c_code)
    with open(cpp_path, 'w') as f:
        f.write(cpp_code)

    c_o = os.path.join(wd, 'prog.o')
    async_o = os.path.join(wd, 'prog_async.o')
    runtime_o = os.path.join(wd, 'fire_runtime.o')
    async_runtime_o = os.path.join(wd, 'fire_async_runtime.o')
    exe = os.path.join(wd, 'prog.exe')

    gcc = find_gcc()
    gxx = find_gxx()

    r = subprocess.run([gcc, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'gcc -fgimple compile of .c failed: {r.stderr}')

    r = subprocess.run([gxx, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_o, cpp_path],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'g++ compile of .cpp failed: {r.stderr}')

    r = subprocess.run([gcc, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o, RUNTIME_C],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'gcc compile of fire_runtime.c failed: {r.stderr}')

    r = subprocess.run([gxx, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_runtime_o,
                        ASYNC_RUNTIME_CPP], capture_output=True, text=True,
                       timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'g++ compile of fire_async_runtime.cpp failed: {r.stderr}')

    r = fire.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f'link failed: {r.stderr}')
    os.chmod(exe, 0o755)
    return exe


def test_async_with_aenter_boxed_list():
    src = r'''
import asyncio

class CM:
    async def __aenter__(self):
        return [1, 2, 3]
    async def __aexit__(self, exc_type, exc, tb):
        return False

async def main_async() -> Int:
    async with CM() as v:
        print(len(v))
        print(v[0])
        print(v[1])
        print(v[2])
    return 0

def main():
    asyncio.run(main_async())
'''
    try:
        exe = _build_async_program(src)
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        check('async with __aenter__ returning boxed list compiles and runs',
              r.returncode == 0, f'rc={r.returncode} stderr={r.stderr} stdout={r.stdout}')
        check('boxed __aenter__ value observed correctly in async with body',
              r.stdout == '3\n1\n2\n3\n', repr(r.stdout))
    except Exception as e:
        check('async with __aenter__ returning boxed list compiles and runs', False, f'exception: {e}')
        check('boxed __aenter__ value observed correctly in async with body', False, 'skipped due to previous failure')


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except Exception as e:
                check(name, False, f'exception: {e}')
    print(f'\nResults: {_PASS} passed, {_FAIL} failed')
    return _FAIL == 0


if __name__ == '__main__':
    import sys
    sys.exit(0 if run_all() else 1)
