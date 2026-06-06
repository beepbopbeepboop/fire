"""Test runner that compiles and executes mojo programs.

Uses the mojo CLI to compile mojo source to dylib, then loads and executes
the resulting shared library to verify behavior.
"""
import os
import sys
import subprocess
import tempfile
import ctypes
from ctypes import c_int, CFUNCTYPE
from io import StringIO
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO_CLI = os.path.join(HERE, 'build', 'mojo')
RUNTIME_HDR = os.path.join(HERE, 'runtime', 'mojo_runtime.h')

_PASS = 0
_FAIL = 0


def compile_mojo_to_executable(mojo_src: str) -> str:
    """Compile mojo source to executable, return path to executable."""
    from gimple_codegen import compile_to_c

    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        # Compile mojo to C (without GIMPLE annotations for executability)
        c_code = compile_to_c(mojo_src)
        f.write(c_code)
        c_file = f.name

    exe_file = c_file.replace('.c', '.exe')

    try:
        # Compile C to executable using gcc
        runtime_dir = os.path.join(HERE, 'runtime')
        result = subprocess.run(
            [find_gcc(),
             f'-I{runtime_dir}',
             '-o', exe_file, c_file,
             os.path.join(runtime_dir, 'mojo_runtime.c')],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"gcc compilation failed: {result.stderr}")
        return exe_file
    finally:
        try:
            os.unlink(c_file)
        except:
            pass


def run_executable(exe_path: str) -> int:
    """Execute the program and return its exit code."""
    result = subprocess.run(
        [exe_path],
        capture_output=True,
        timeout=10
    )
    return result.returncode


def test_execution(name: str, mojo_src: str, expected_return: int = 0):
    """Test that mojo code compiles and executes with expected return code."""
    global _PASS, _FAIL
    exe_path = None
    try:
        exe_path = compile_mojo_to_executable(mojo_src)
        result = run_executable(exe_path)
        if result == expected_return:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected return {expected_return}, got {result}")
            _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        if exe_path:
            try:
                os.unlink(exe_path)
            except:
                pass


def run_tests():
    """Run all execution tests."""

    # 1. Simple return
    test_execution("simple_return", """\
def main() -> Int:
    return 42
""", expected_return=42)

    # 2. Arithmetic
    test_execution("arithmetic", """\
def main() -> Int:
    var x: Int = 10
    var y: Int = 32
    return x + y
""", expected_return=42)

    # 3. Control flow
    test_execution("control_flow", """\
def main() -> Int:
    var x: Int = 5
    if x > 0:
        return 42
    else:
        return 0
""", expected_return=42)

    # 4. Loops
    test_execution("loop_sum", """\
def main() -> Int:
    var s: Int = 0
    for i in range(10):
        s = s + i
    return s
""", expected_return=45)

    # 5. Function call
    test_execution("function_call", """\
def add(a: Int, b: Int) -> Int:
    return a + b

def main() -> Int:
    return add(20, 22)
""", expected_return=42)

    # 6. While loop
    test_execution("while_loop", """\
def main() -> Int:
    var x: Int = 1
    var result: Int = 0
    while x < 8:
        result = result + x
        x = x + 1
    return result
""", expected_return=28)

    # 7. Factorial
    test_execution("factorial", """\
def factorial(n: Int) -> Int:
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

def main() -> Int:
    return factorial(5)
""", expected_return=120)

    # 8. Print statement
    test_execution("print_stmt", """\
def main():
    print(42)
""", expected_return=0)

    # 9. Int is the 64-bit machine word (ABI: Int = int64_t). 3e9 overflows a
    #    32-bit int, so this returns 42 only if Int arithmetic is genuinely 64-bit.
    test_execution("int_is_64bit", """\
def main() -> Int:
    var x: Int = 3000000000
    var y: Int = x + x
    if y == 6000000000:
        return 42
    return 1
""", expected_return=42)

    # 10. Slice of an unannotated list param, then concat. Regression for the
    #     slice->'int' hallucination: the param `items` must infer as a list (it
    #     is sliced), the slice must carry the list type, and list+list must be
    #     concat. Before the fix this compiled to pointer-arithmetic garbage and
    #     crashed at runtime. [1,2] + [99] -> len 3.
    test_execution("slice_then_concat", """\
def take(items):
    head = items[:2]
    return head + [99]

def main() -> Int:
    xs = [1, 2, 3, 4]
    r = take(xs)
    return len(r)
""", expected_return=3)

    # 11. Nested list of floats: append inner double-lists, then read grid[i][j].
    #     Regression for lost nested element type on append -> inner read used the
    #     int getter on a double list and returned 0 (silent). The append must carry
    #     the inner list's element type as the container's nested element type so
    #     grid[i][j] reads with mojo_list_get_double.
    test_execution("nested_float_list", """\
def main() -> Int:
    grid = []
    grid.append([10.0, 20.0, 30.0])
    grid.append([40.0, 50.0, 60.0])
    a = grid[0][0]
    b = grid[1][2]
    if a == 10.0:
        if b == 60.0:
            return 42
    return 1
""", expected_return=42)

    # 12. Cross-call element-type contract: a function receives a list-of-float-
    #     lists and reads grid[0][0]. The element type must cross the call
    #     boundary (caller knows it; the param does not, on its own), so the
    #     callee reads with mojo_list_get_double and its return infers as double.
    #     Before the contract this returned/printed 0 (silent).
    test_execution("xcall_nested_elem", """\
def head_x(grid):
    return grid[0][0]

def main() -> Int:
    g = []
    g.append([7.0, 8.0])
    g.append([9.0, 10.0])
    if head_x(g) == 7.0:
        return 42
    return 1
""", expected_return=42)

    # 13. Cross-call scalar contract: an unannotated scalar param defaults to the
    #     int64_t machine word, so a double argument truncated (bnbody's dt=0.01
    #     -> 0 froze the sim). The param type must follow the (unanimous) call-site
    #     argument type: scale(double, double) -> double. 4.0 * 0.5 == 2.0.
    test_execution("xcall_scalar_double", """\
def scale(x, factor):
    return x * factor

def main() -> Int:
    f = 0.5
    r = scale(4.0, f)
    if r == 2.0:
        return 42
    return 1
""", expected_return=42)

    # 14. Nested tuple unpacking: (a, b), (c, d) = pairs[0], pairs[1]. The unpack
    #     targets are themselves tuples; before the fix the inner names were never
    #     declared ('a'/'c' undeclared). 10 + 30 == 40.
    test_execution("nested_tuple_unpack", """\
def f(pairs):
    (a, b), (c, d) = pairs[0], pairs[1]
    return a + c

def main() -> Int:
    p = []
    p.append([10, 20])
    p.append([30, 40])
    return f(p)
""", expected_return=40)


def main():
    if not os.path.exists(MOJO_CLI):
        print(f"ERROR: {MOJO_CLI} not found. Run 'make stdlib' first.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("MOJO EXECUTION TESTS")
    print("=" * 60)

    run_tests()

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)


if __name__ == '__main__':
    main()
