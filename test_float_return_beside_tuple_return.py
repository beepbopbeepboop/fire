"""Regression test: a function that returns a float on one path and a tuple
(or string) on another must compile AND print what CPython prints.

Before the fix, `_sce_simple_emit` routed the float through an `int64_t`
temp and the return-type join was a pointer, so the caller received the
truncated integer bits as a `MojoList *` / `char *` and the binary died with
SIGSEGV (`comptime.py`'s `eval_const` is the live case). The float now has to
travel as a boxed word beside the pointer returns.

Each program is compiled through the production path
(`compile_mojo_to_gimple_exe`), run, and its stdout is compared with the same
source run under CPython.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_gimple_runner import compile_mojo_to_gimple_exe, RUN_TIMEOUT_S


PICK_SRC = """\
def pick(x: Int) -> String:
    if x == 1:
        return "s"
    return 1.5


def main():
    print(pick(0))
    print(pick(1))
"""

TUP_SRC = """\
def tup(x: Int):
    if x == 1:
        return (1, 2)
    return 2.5


def main():
    print(tup(0))
    print(tup(1))
"""

NONE_SRC = """\
def pick(x: Int):
    if x == 1:
        return 1.5
    if x == 2:
        return (3, 4)
    return None


def main():
    print(pick(1))
    print(pick(2))
    print(pick(0))
"""

EVAL_CONST_SRC = """\
from dataclasses import dataclass


@dataclass
class FloatLit:
    value: float


@dataclass
class TupleE:
    elements: list


def eval_const(node):
    if isinstance(node, FloatLit):
        return node.value
    if isinstance(node, TupleE):
        res = []
        for e in node.elements:
            res.append(eval_const(e))
        return tuple(res)
    return None


def main():
    print(eval_const(FloatLit(1.5)))
    print(eval_const(TupleE([FloatLit(2.5)])))
"""

CASES = [
    ("float_str_none", PICK_SRC),
    ("float_tuple_none", TUP_SRC),
    ("float_tuple_none_with_nested_none", NONE_SRC),
    ("eval_const_repro", EVAL_CONST_SRC),
]


def _cpython_stdout(src: str) -> str:
    with tempfile.TemporaryDirectory(prefix="fbt_py_") as d:
        path = os.path.join(d, "prog.py")
        with open(path, "w") as f:
            f.write(src + "\nmain()\n")
        res = subprocess.run([sys.executable, "-I", path],
                             capture_output=True, text=True,
                             timeout=RUN_TIMEOUT_S)
        assert res.returncode == 0, res.stderr
        return res.stdout


def _gimple_stdout(src: str) -> str:
    exe = compile_mojo_to_gimple_exe(src + "\nmain()\n", filename="prog.py")
    try:
        res = subprocess.run([exe], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT_S)
        assert res.returncode == 0, (
            f"binary exited {res.returncode} (SIGSEGV is -11); "
            f"stdout so far: {res.stdout!r}")
        return res.stdout
    finally:
        try:
            os.unlink(exe)
        except OSError:
            pass


def test_float_beside_pointer_returns_match_cpython():
    for name, src in CASES:
        want = _cpython_stdout(src)
        got = _gimple_stdout(src)
        assert got == want, f"{name}: got {got!r}, CPython printed {want!r}"


if __name__ == "__main__":
    test_float_beside_pointer_returns_match_cpython()
    print("PASS")
