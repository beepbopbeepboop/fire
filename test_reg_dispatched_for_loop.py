# Pin for the dict/list runtime dispatch in emit_loops._gen_for_iter (the arm taken when a
# loop's iterable is a word of unknown type). One C variable is shared by the dict arm
# (string keys, `char *`) and the list arm (any element), and the doc that tracked this
# (a `for i in o.read(): print(i)` SIGSEGV) described the list-of-ints crash. Every program
# below goes through that arm or its static neighbours and must print exactly what CPython
# prints; a regression to `char *` for the shared variable shows up as a crash or as a
# pointer-decimal in the output.
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_config import find_gcc
from gimple_codegen import compile_to_gimple
from test_dict_tuple_key import RUNTIME

PROGRAMS = {
    "doc_repro_two_hop_field": '''
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
''',
    "untyped_param_list_dict_str_float": '''
def show(xs):
    for i in xs:
        print(i)
def main():
    show([10, 20])
    show({"a": 1, "b": 2})
    show(["x", "y"])
    show([1.5, 2.5])
main()
''',
    "word_iterables": '''
class R:
    def __init__(self, items):
        self.items = items
def main():
    r = R([10, 20])
    for i in getattr(r, 'items'):
        print(i)
    d = {"a": [1, 2], "b": "s"}
    for i in d["a"]:
        print(i)
    box = [[3, 4]]
    w = box[0]
    for i in w:
        print(i)
    t = (1, [7, 8])
    for i in t[1]:
        print(i)
main()
''',
    "int_elements_keep_int_arithmetic": '''
def main():
    q = {"n": [10, 20], "s": "z"}
    for x in q["n"]:
        print(x + 1)
main()
''',
    # Doubles reached through a word of unknown type used to print as their raw
    # IEEE-754 bits (4609434218613702656); the kind-aware read fixed that, and
    # the target must then still do INT arithmetic on int slots and float
    # arithmetic on float slots (a boxed-but-untagged target made `x + 1` 11.0).
    "float_elements_print_and_compute": '''
def main():
    d = {"f": [1.5, 2.5], "i": [10, 20], "s": ["u", "v"]}
    total = 0
    for x in d["i"]:
        total = total + x
        print(x * 2, x > 12, x - 1)
    print(total)
    for y in d["f"]:
        print(y, y * 2, y + 1, y > 2.0)
    for z in d["s"]:
        print(z + "!")
main()
''',
    # `+ - * / %` on a float slot reached through the dispatch (the target is a tagged word,
    # `emit_infra._float_param_arith`). Float `//` is NOT here: the dict arm lowers the shared
    # variable as a `char *` key and `y // 2` does not compile (see the bug doc).
    "float_slot_arithmetic": '''
def main():
    d = {"f": [7.5, 2.5], "s": "z"}
    for y in d["f"]:
        print(y % 2, y - 1, y * 3, y + 1, y / 2)
main()
''',
    "floats_through_dispatch_with_dict_and_str_siblings": '''
def main():
    d = {"a": [1.5, 2.5], "b": ["u", "v"], "c": {"k": 1}}
    for key in ["a", "b", "c"]:
        for x in d[key]:
            print(x)
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


def _cpython(src):
    return subprocess.run([sys.executable, "-c", src], capture_output=True, text=True).stdout


def test_dispatched_for_loop_matches_cpython():
    for name, src in PROGRAMS.items():
        p = _run_compiled(src)
        assert p.returncode == 0, f"{name}: exit {p.returncode}: {p.stderr[-200:]}"
        assert p.stdout == _cpython(src), f"{name}: got {p.stdout!r}, CPython {_cpython(src)!r}"


if __name__ == "__main__":
    test_dispatched_for_loop_matches_cpython()
    print("PASS")
