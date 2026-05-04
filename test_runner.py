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
            ['/opt/local/bin/gcc-mp-15',
             f'-I{runtime_dir}',
             '-o', exe_file, c_file],
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
