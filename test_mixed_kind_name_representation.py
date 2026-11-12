#!/usr/bin/env python3
"""Regression test: a name that holds more than one KIND of scalar.

`x = 1.5` then `x = "text"` (and every other int/float/str mixture, including
a float dict read followed by a string) used to be refused by
`MIXED_NAME_NON_INT64_REFUSAL`, because the codegen pinned the name to its
first C type and the second store was a bare C cast: a `double` truncated to
an int, a `char *` reinterpreted as a pointer, or a `double = char *` gcc
rejects outright. `ginf.mixed_scalar_locals` now declares such a name as the
runtime `MojoBox` (`int64_t`), boxes a float/str store by its own kind, and
every consumer reads the kind back (`mojo_repr_boxed`, `mojo_box_word`,
`mojo_float_arith_select`, `mojo_len_word`).

Every case is pinned against CPython on the SAME text (`print` output must be
byte-identical), so a written-down expected string cannot drift.

A container and a number passed to one parameter (the other shape the bug
doc names) is pinned too: the parameter keeps the int64_t box and `print`
dispatches on the value's runtime kind.

Quick test for bugs/CODEGEN_mixed_kind_names_need_a_representation.md.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_gimple_runner import compile_mojo_to_gimple_exe


def run_case(name: str, src: str, expected: str | None = None) -> bool:
    """Compile `src`, run it, and compare stdout/exit code with CPython.

    `expected`, when given, replaces the CPython answer for a program CPython
    cannot parse (`var x = ...` is Mojo syntax)."""
    try:
        exe = compile_mojo_to_gimple_exe(src)
    except Exception as e:
        print(f"FAIL  {name}: compile raised {str(e)[:400]}")
        return False
    got = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    if expected is not None:
        if got.stdout != expected or got.returncode != 0:
            print(f"FAIL  {name}: expected {expected!r}, "
                  f"compiled {got.stdout!r} (rc {got.returncode})")
            return False
        print(f"PASS  {name}")
        return True
    want = subprocess.run([sys.executable, "-c", src], capture_output=True,
                          text=True, timeout=60)
    if got.stdout != want.stdout or got.returncode != want.returncode:
        print(f"FAIL  {name}: CPython {want.stdout!r} (rc {want.returncode}), "
              f"compiled {got.stdout!r} (rc {got.returncode})")
        return False
    print(f"PASS  {name}")
    return True


CASES = {
    # The doc's shape: a float dict read, then a str store into the same
    # name (and the reverse order, and the int arm of the same box).
    "dict_float_read_then_str": '''
def test():
    d = {"key": 1.5}
    val = d["key"]
    print(val)
    print(val + 0.5)
    val = "text"
    print(val)
    print(len(val))
    val = 7
    print(val)
    print(val + 1)
def main():
    test()
main()
''',
    "float_then_str": '''
def main():
    x = 1.5
    print(x)
    x = "text"
    print(x)
    print(x + "!")
    print(len(x))
main()
''',
    "str_then_float": '''
def main():
    x = "s"
    print(x)
    x = 1.5
    print(x)
    print(x * 2)
main()
''',
    "str_then_int": '''
def main():
    x = "a"
    print(x)
    x = 2
    print(x)
    print(x + 3)
main()
''',
    "int_then_float": '''
def main():
    x = 1
    print(x)
    x = 2.5
    print(x)
    print(x + 1)
    print(x > 1)
main()
''',
    "bool_then_float": '''
def main():
    x = True
    print(x)
    x = 2.5
    print(x)
    x = False
    print(x)
main()
''',
    # A string store, then comparisons/concatenation/f-string on the box.
    "str_operations_after_float": '''
def main():
    x = 0.5
    x = "hello"
    print(x == "hello")
    print(x == "other")
    print(x != "hello")
    print(x + "!")
    print(f"<{x}>")
    print(str(x))
main()
''',
    # The branch-order shape: the first store seen by the codegen is not the
    # only kind the name can hold. The predicate is static, so this compiles.
    "branches": '''
def main():
    c = True
    if c:
        x = 1.5
    else:
        x = "s"
    print(x)
    x = "t"
    print(x)
main()
''',
    # A container at one call site and a number at another, to one parameter:
    # the print-only parameter keeps the int64_t box and print() dispatches on
    # the value's runtime kind.
    "container_and_number_parameter": '''
def show(x):
    print(x)
def main():
    show([1, 2])
    show(3)
    show("s")
main()
''',
}

# Programs CPython cannot run (`var` is Mojo syntax): name -> expected stdout.
MOJO_ONLY_CASES = {
    # `var` declarations reach the same representation through the VarDecl
    # store path.
    "var_decl_then_rebind": ('''\
def main():
    var x = 1.5
    print(x)
    x = "s"
    print(x)
main()
''', "1.5\ns\n"),
}


def main() -> int:
    failures = 0
    for name, src in CASES.items():
        if not run_case(name, src):
            failures += 1
    for name, (src, expected) in MOJO_ONLY_CASES.items():
        if not run_case(name, src, expected):
            failures += 1
    print()
    if failures:
        print(f"{failures} of {len(CASES) + len(MOJO_ONLY_CASES)} cases FAILED")
        return 1
    print(f"All {len(CASES) + len(MOJO_ONLY_CASES)} mixed-kind-name cases match CPython")
    return 0


if __name__ == "__main__":
    sys.exit(main())
