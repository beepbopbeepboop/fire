#!/usr/bin/env python3
"""Regression test for float/None/bytes print in polymorphic params."""
import os, sys, tempfile, subprocess
sys.path.insert(0, '.')
import driver

def run(src):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'prog.py')
        with open(path, 'w') as f:
            f.write(src)
        out = os.path.join(td, 'prog')
        rc = driver.compile_program(path, src, output=out, run=False)
        if rc != 0 or not os.path.exists(out):
            return None, f"compile failed rc={rc}"
        result = subprocess.run([out], capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout

# Float pair — currently prints '2' (bits of 2.5 as int), should print '2.5'
rc, out = run('def f(x):\n    print(x)\n\nf(2.5)\nf(1)\n')
print(f"float+int: rc={rc} stdout={out!r}")
# Should be 0 and '2.5\n1\n', currently fails
