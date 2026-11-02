#!/usr/bin/env python3
"""Regression for CODEGEN_tuple_key_int_and_str_elements_collide."""
import os, sys, tempfile, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_config import find_gcc
from gimple_codegen import compile_to_gimple
from test_dict_tuple_key import RUNTIME

def test_distinct_int_str_tuple():
    src = 'def main() raises:\n    d = {}\n    d[(1, 2, 3)] = 1\n    d[("1", "2", "3")] = 2\n    print(len(d))\n'
    tmp = tempfile.mkdtemp(dir=HERE)
    try:
        c = compile_to_gimple(src)
        cfile = os.path.join(tmp, "t.c")
        exe = os.path.join(tmp, "t")
        with open(cfile, "w") as f:
            f.write(c)
        sources = [cfile, os.path.join(RUNTIME, "fire_runtime.c")]
        r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe, *sources],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        p = subprocess.run([exe], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert p.stdout.strip() == "2", f"expected 2, got {p.stdout.strip()}"
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)

if __name__ == "__main__":
    test_distinct_int_str_tuple()
    print("PASS")
