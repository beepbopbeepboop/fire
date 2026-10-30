"""Regression for CODEGEN_imported_callable_default_answers_zero.

Step 1 (root cause) is fixed in mojo/middle/calls_shared.py: a MemberExpr
default (os.getloadavg, a callable the runtime does not implement) routes to mojo_unavailable_callable_ptr, raising
NotImplementedError, rather than padding 0 and returning 0.
"""
import sys, subprocess, tempfile, os
sys.path.insert(0, '.')
from build_config import find_gcc
from exec_budget import COMPILE_TIMEOUT_S, LINK_TIMEOUT_S, RUN_TIMEOUT_S
from gimple_codegen import compile_to_gimple

def _compile_and_run(src):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        f.write(compile_to_gimple(src))
        c_file = f.name
    exe_file = c_file.replace('.c', '.exe')
    runtime_dir = os.path.join(os.getcwd(), 'runtime')
    sources = [c_file, os.path.join(runtime_dir, 'fire_runtime.c')]
    r = subprocess.run([find_gcc(), '-fgimple', f'-I{runtime_dir}', '-o', exe_file, *sources],
                       capture_output=True, text=True, timeout=LINK_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'compile failed: {r.stderr}')
    res = subprocess.run([exe_file], capture_output=True, timeout=RUN_TIMEOUT_S)
    try: os.unlink(exe_file); os.unlink(c_file)
    except: pass
    return res.returncode, res.stdout.decode('utf-8', 'replace'), res.stderr.decode('utf-8', 'replace')

def test_imported_callable_default_raises():
    rc, out, err = _compile_and_run("""\
def probe(x, *, g=os.getloadavg):
    return g(x)
def main():
    print(probe("."))
main()
""")
    assert rc != 0, f"expected non-zero exit, got {rc} stdout={out} stderr={err}"
    assert "NotImplementedError" in err or "NotImplementedError" in out, f"expected NotImplementedError in output, got err={err[:200]}"
    print("PASS test_imported_callable_default_raises")

def test_uncalled_imported_callable_default_is_silent():
    rc, out, err = _compile_and_run("""\
def probe(x, *, g=os.getloadavg):
    return x
def main():
    print(probe("hello"))
main()
""")
    assert rc == 0, f"expected 0 exit, got {rc} out={out} err={err}"
    assert out.strip() == "hello", f"expected hello, got {out!r}"
    print("PASS test_uncalled_imported_callable_default_is_silent")

if __name__ == '__main__':
    test_imported_callable_default_raises()
    test_uncalled_imported_callable_default_is_silent()
    print("ALL PASS")
