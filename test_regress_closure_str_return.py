"""Regression for CODEGEN_closure_str_return_is_lost."""
import sys, os, subprocess, tempfile
sys.path.insert(0, '.')
import gimple_codegen
from build_config import find_gcc
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S
GCC = find_gcc()
_PROJECT_DIR = '.'
_RUNTIME_INC = os.path.join(_PROJECT_DIR, 'runtime')

def cpython_stdout(src):
    import tempfile, sys, subprocess
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
        f.write(src)
        name = f.name
    try:
        result = subprocess.run([sys.executable, name], capture_output=True, text=True)
        return result.stdout
    finally:
        os.unlink(name)

def compiled_stdout(src, mode='single-TU'):
    with tempfile.TemporaryDirectory() as td:
        entry = os.path.join(td, 'case.py')
        with open(entry, 'w') as fh:
            fh.write(src)
        c_src = gimple_codegen._run_pipeline(
            src, filename=entry,
            **({'do_imports': True} if mode == 'single-TU'
               else {'link_mode': True}))[0]
        c_file = os.path.join(td, 'case.c')
        exe = os.path.join(td, 'case.exe')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
             os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if cc.returncode != 0:
            return f"GCC_ERROR: {cc.stderr}"
        run = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT_S)
        return run.stdout

if __name__ == '__main__':
    src = '''\
def mk_str():
    return lambda: "hi"
def use_str_factory():
    print(mk_str()())
use_str_factory()
'''
    want = cpython_stdout(src)
    got_single = compiled_stdout(src, 'single-TU')
    got_link = compiled_stdout(src, 'link-mode')
    print(f"CPython want: {want!r}")
    print(f"single-TU got: {got_single!r}")
    print(f"link-mode got: {got_link!r}")
    assert got_single == want, f"FAIL single-TU: {got_single!r} != {want!r}"
    assert got_link == want, f"FAIL link-mode: {got_link!r} != {want!r}"
    print("PASS")
