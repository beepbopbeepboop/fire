"""Regression for CODEGEN_none_attribute_is_none_false_after_closure_store_probe.
Sibling reads a cell another closure rebinds (boxed by-value capture)."""
import driver, subprocess, sys, tempfile, os

SOURCE = """\
def outer(seed):
    total = seed
    def add(k):
        nonlocal total
        total = total + k
    add(3)
    def read(extra):
        return total + extra
    return read

def main(n):
    f = outer(2)
    print(f(10))
"""

wd = tempfile.mkdtemp(prefix='reg_')
with open(os.path.join(wd,'p.mojo'),'w') as f: f.write(SOURCE)
exe = os.path.join(wd,'p.exe')
rc = driver.compile_program(os.path.join(wd,'p.mojo'), SOURCE, output=exe, run=False)
assert rc is not None, "compile failed"
r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
assert r.returncode == 0, f"run failed: {r.stderr}"
assert r.stdout == "15\n", f"wrong output: {r.stdout!r}"
print("PASS regression sibling-reads-boxed-cell")
