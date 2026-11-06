# A dict's None KEY is its own key domain (runtime keykind 3), not the integer 0 that `None`
# lowers to. The literal `{None: v}` and `None in d` were right; `d[None] = v`, `d[None]` and
# `d.get(None)` used the integer-0 entry, so `d[None] = 5` made a second entry and a read of the
# None key returned a different slot. Every program is diffed against CPython.
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_config import find_gcc
from gimple_codegen import compile_to_gimple
from test_dict_tuple_key import RUNTIME

PROGRAMS = {
    "none_key_store_read_get": '''
def main():
    d = {None: 1, "a": 2}
    print(0 in d, None in d)
    print(d[None])
    d[None] = 5
    print(d)
    e = {0: "z"}
    print(None in e, 0 in e)
    print(len(d))
    d2 = {}
    d2[None] = 7
    d2[0] = 8
    print(d2, len(d2), d2[None], d2[0])
    print(d.get(None), d.get(None, 99), d.get("zz", 99))
main()
''',
    "none_key_with_str_float_bool_values": '''
def main():
    s = {}
    s[None] = "str"
    print(s[None], s)
    f = {None: 1.5}
    f[None] = 2.5
    print(f[None], f)
    b = {}
    b[None] = True
    print(b)
main()
''',
}


def _run_compiled(src):
    tmp = tempfile.mkdtemp(dir=HERE)
    try:
        cfile, exe = os.path.join(tmp, "t.c"), os.path.join(tmp, "t")
        with open(cfile, "w") as f:
            f.write(compile_to_gimple(src))
        r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe, cfile,
                            os.path.join(RUNTIME, "fire_runtime.c")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        return subprocess.run([exe], capture_output=True, text=True)
    finally:
        for f in os.listdir(tmp):
            os.unlink(os.path.join(tmp, f))
        os.rmdir(tmp)


def test_dict_none_key_matches_cpython():
    for name, src in PROGRAMS.items():
        p = _run_compiled(src)
        want = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True).stdout
        assert p.returncode == 0, f"{name}: exit {p.returncode}: {p.stderr[-200:]}"
        assert p.stdout == want, f"{name}: got {p.stdout!r}, CPython {want!r}"


if __name__ == "__main__":
    test_dict_none_key_matches_cpython()
    print("PASS")
