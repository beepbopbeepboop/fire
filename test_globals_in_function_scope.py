#!/usr/bin/env python3
"""Pin: a bare `globals()` call inside a function body must lower to a
snapshot of the module's globals struct, not to the unavailable
"globals: unavailable in compiled mode" stub.

This is the `globals`-in-function-scope stub class of
`bugs/GATE_red_recover-land_2026-11-02-part5-part1.md`: the compiler's
own `mojo/middle/types.py` reads module state with `globals()` inside a
function, and the closure emitted a weak stub for that builtin call
because `is_module_globals_call` only accepted module-scope reads.

The fixture must live inside the checkout (`build/`, git-ignored): the
compiler resolves sibling modules relative to the source file's tree.

Run: python3 test_globals_in_function_scope.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')

SRC = r'''
X = 42
Y = "hi"

def read_globals():
    g = globals()
    print(g.get("X", -1))
    print(g.get("Y", "no"))
    print("X" in g)
    print("MISSING" in g)
    print(g.get("MISSING", 7))

def main():
    read_globals()

main()
'''


def _cpython_stdout(root: str) -> str:
    r = subprocess.run([sys.executable, root], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _build_and_run(ci: str, td: str) -> str:
    gcc = find_gcc()
    c_path = os.path.join(td, 'prog.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'prog.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'prog.exe')
    r = subprocess.run([gcc, '-O0', '-fgimple', '-x', 'c',
                        f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([gcc, '-O0', f'-I{RUNTIME_DIR}', '-c', '-o', rt_o,
                        RUNTIME_C],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([gcc, '-o', exe, c_o, rt_o], capture_output=True,
                       text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([exe], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def test_globals_in_function_scope():
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_globals_in_function_scope')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        root_file = os.path.join(td, 'prog.py')
        with open(root_file, 'w') as f:
            f.write(SRC)
        expected = _cpython_stdout(root_file)
        assert expected == '42\nhi\nTrue\nFalse\n7\n', expected
        with open(root_file) as f:
            ci = gimple_codegen.compile_to_gimple(
                f.read(), do_imports=True, filename=root_file)
        assert 'unavailable in compiled mode' not in ci, '\n'.join(
            ln for ln in ci.splitlines() if 'unavailable in compiled mode' in ln)
        assert _build_and_run(ci, td) == expected
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_globals_in_function_scope()
    print('PASS')
