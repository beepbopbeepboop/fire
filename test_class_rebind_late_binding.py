#!/usr/bin/env python3
"""Done-when test for bugs/CODEGEN_class_rebind_late_binding.md.

A method of a class declared inside a function reads a name that the enclosing function rebinds AFTER the class
statement. Python late-binds that name, so the method must see the rebound value. The compiled path must answer
what CPython answers, not refuse the program and not snapshot the value at the class statement.

    python3 test_class_rebind_late_binding.py

Uses the compiled path's own helpers from test_gimple_runner, so the compile and run match every other gimple test."""
import os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_gimple_runner import compile_mojo_to_gimple_exe, run_executable_stdout  # noqa: E402

PROGRAM = """\
def outer(args: int) -> int:
    class C:
        def m(self) -> int:
            return args
    args = 2
    return C().m()

def main():
    print(outer(1))
"""
EXPECTED = "2\n"   # CPython: late binding, so the method sees the rebound args


def main():
    exe = None
    try:
        exe = compile_mojo_to_gimple_exe(PROGRAM)
        out = run_executable_stdout(exe)
    except Exception as e:      # a refusal at compile time is the bug itself
        print("FAIL: did not compile and run: %s" % str(e).splitlines()[0][:200])
        return 1
    finally:
        if exe:
            try:
                os.unlink(exe)
            except OSError:
                pass
    if out == EXPECTED:
        print("PASS class_rebind_late_binding: printed %r" % out)
        return 0
    print("FAIL class_rebind_late_binding: expected %r, got %r" % (EXPECTED, out))
    return 1


if __name__ == "__main__":
    sys.exit(main())
