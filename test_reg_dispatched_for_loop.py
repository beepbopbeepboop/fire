# Regression for bug:CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms
# Repro from bugs/hard/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md
# Expected: for i in o.read(): print(i) produces 10 / 20, not SIGSEGV.

import os, sys, tempfile, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_config import find_gcc
from gimple_codegen import compile_to_gimple
from test_dict_tuple_key import RUNTIME


def test_dispatched_for_loop_regression():
    src = '''
class Reader:
    def __init__(self, items):
        self.items = items
class Owner:
    def __init__(self, items):
        self._items = items
    def read(self):
        return Reader(self._items).items
def main():
    o = Owner([10, 20])
    for i in o.read():
        print(i)
main()
'''
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
        out = p.stdout.strip().replace('\r\n', '\n')
        assert out == "10\n20" or out == "10\n20\n" or out == "10\n20", f"got {p.stdout!r}"
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)


if __name__ == "__main__":
    test_dispatched_for_loop_regression()
    print("PASS")
