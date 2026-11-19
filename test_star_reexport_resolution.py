#!/usr/bin/env python3
"""Pin: `_find_symbol_home_module` follows `from X import *` re-export
edges, so a name surfaced through a star import resolves to its defining
module.

This is the `multi_kind_locals` stub class of
`bugs/GATE_red_recover-land_2026-11-02-part5-part1.md`: `emit_infra`
star-imports `multi_kind_locals` from `mojo.middle.infra_infer`, and the
re-export walk only followed explicit `from X import name` edges, so the
symbol's home could not be found.

The fixture must live inside the checkout (`build/`, git-ignored) so the
sibling/package resolution path is the one the compiled compiler uses.

Run: python3 test_star_reexport_resolution.py
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


def _write_tree(td: str) -> str:
    os.makedirs(os.path.join(td, 'p'))
    with open(os.path.join(td, 'p', '__init__.py'), 'w') as f:
        f.write('from .sub import *\n')
    with open(os.path.join(td, 'p', 'sub.py'), 'w') as f:
        f.write('def helper(x):\n    return x + 1\n')
    with open(os.path.join(td, 'consumer.py'), 'w') as f:
        f.write('from p import helper\n\n'
                'def main():\n    print(helper(41))\n\n'
                'main()\n')
    return os.path.join(td, 'consumer.py')


def _cpython_stdout(td: str, root: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, root], capture_output=True, text=True,
                       cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _build_and_run(ci: str, td: str) -> str:
    gcc = find_gcc()
    c_path = os.path.join(td, 'consumer.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'consumer.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'consumer.exe')
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


def test_star_reexport_resolution():
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_star_reexport_resolution')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        root_file = _write_tree(td)
        expected = _cpython_stdout(td, root_file)
        assert expected == '42\n', expected
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
    test_star_reexport_resolution()
    print('PASS')
