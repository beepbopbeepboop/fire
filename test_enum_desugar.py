# Plain `Enum` classes (ast_rewriter.desugar_enums): members have identity, `.name` / `.value`,
# `str` / `repr`, iteration, `Color(v)` lookup, aliases, methods and a ValueError on a bad value,
# and every program must print exactly what CPython prints. Before the desugar a member was the
# bare int, so `.name` / `.value` / iteration failed and `print(Color.RED)` printed `1`.
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_config import find_gcc
from gimple_codegen import compile_to_gimple
from test_dict_tuple_key import RUNTIME

PROGRAMS = {
    "members_name_value_str": '''
from enum import Enum
class Color(Enum):
    RED = 1
    GREEN = 2
print(Color.RED, Color.GREEN.value, Color.RED.name, repr(Color.RED))
print(Color(2), [c.name for c in Color], len(Color))
print(Color.RED == Color.RED, Color.RED is Color.GREEN)
print(Color.__name__)
''',
    "methods_aliases_functions_and_errors": '''
from enum import Enum
class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
    CRIMSON = 1

    def describe(self):
        return self.name.lower() + "=" + str(self.value)

class Mode(Enum):
    READ = "r"
    WRITE = "w"

def pick(c):
    if c is Color.RED:
        return "is red"
    if c == Color.GREEN:
        return "is green"
    return "other " + c.name

def main():
    print(Color.CRIMSON is Color.RED, Color.CRIMSON.name)
    print(Color.BLUE.describe())
    for c in Color:
        print(c.name, c.value, pick(c))
    print(Mode("w"), Mode.READ.value, [m.value for m in Mode])
    try:
        Color(9)
    except ValueError as e:
        print("error:", e)
    x = Color.GREEN
    print(x, repr(x), f"{x}", "%s" % x, isinstance(x, Color))
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


def test_plain_enums_match_cpython():
    for name, src in PROGRAMS.items():
        p = _run_compiled(src)
        want = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True).stdout
        assert p.returncode == 0, f"{name}: exit {p.returncode}: {p.stderr[-200:]}"
        assert p.stdout == want, f"{name}: got {p.stdout!r}, CPython {want!r}"


if __name__ == "__main__":
    test_plain_enums_match_cpython()
    print("PASS")
