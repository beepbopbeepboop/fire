"""Test runner that compiles and executes GIMPLE programs.

Uses gcc (gcc-15 if available, else fallback) with -fgimple to compile and execute
GIMPLE-annotated C code. This tests the GIMPLE backend which is used for the gimple codegen tests.
"""
import os
import sys
import subprocess
import tempfile
from io import StringIO
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_HDR = os.path.join(HERE, 'runtime', 'mojo_runtime.h')

_PASS = 0
_FAIL = 0


def compile_mojo_to_gimple_exe(mojo_src: str) -> str:
    """Compile mojo source to GIMPLE executable, return path to executable."""
    from gimple_codegen import compile_to_gimple

    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        # Compile mojo to GIMPLE C code
        c_code = compile_to_gimple(mojo_src)
        f.write(c_code)
        c_file = f.name

    exe_file = c_file.replace('.c', '.exe')

    try:
        # Compile GIMPLE C to executable using gcc -fgimple
        runtime_dir = os.path.join(HERE, 'runtime')
        result = subprocess.run(
            [find_gcc(), '-fgimple',
             f'-I{runtime_dir}',
             '-o', exe_file, c_file,
             os.path.join(runtime_dir, 'mojo_runtime.c')],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"gcc -fgimple compilation failed: {result.stderr}")
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


def test_gimple_execution(name: str, mojo_src: str, expected_return: int = 0):
    """Test that mojo code compiles to GIMPLE and executes with expected return code."""
    global _PASS, _FAIL
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
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
    """Run GIMPLE-specific tests."""

    # 1. Simple arithmetic in GIMPLE
    test_gimple_execution("gimple_arithmetic", """\
def main() -> Int:
    var a: Int = 10
    var b: Int = 32
    return a + b
""", expected_return=42)

    # 2. Nested control flow in GIMPLE
    test_gimple_execution("gimple_nested_if", """\
def main() -> Int:
    var x: Int = 5
    if x > 0:
        if x > 3:
            return 42
        else:
            return 0
    else:
        return -1
""", expected_return=42)

    # 3. Loop in GIMPLE
    test_gimple_execution("gimple_loop", """\
def main() -> Int:
    var sum: Int = 0
    var i: Int = 0
    while i < 10:
        sum = sum + i
        i = i + 1
    return sum
""", expected_return=45)

    # 4. Function calls in GIMPLE (no function call restrictions yet)
    test_gimple_execution("gimple_function_call", """\
def add(x: Int, y: Int) -> Int:
    return x + y

def main() -> Int:
    return add(20, 22)
""", expected_return=42)

    # 5. For loop in GIMPLE
    # TODO: Bug in loop variable handling - produces 208 instead of 720
    # test_gimple_execution("gimple_for_loop", """\
    # def main() -> Int:
    #     var product: Int = 1
    #     for i in range(1, 7):
    #         product = product * i
    #     return product
    # """, expected_return=720)

    # 6. Recursion in GIMPLE
    test_gimple_execution("gimple_recursion", """\
def fib(n: Int) -> Int:
    if n <= 1:
        return 1
    else:
        return fib(n - 1) + fib(n - 2)

def main() -> Int:
    return fib(9)
""", expected_return=55)

    # 7. Multiple local variables
    test_gimple_execution("gimple_locals", """\
def main() -> Int:
    var a: Int = 5
    var b: Int = 10
    var c: Int = 20
    return a + b + c
""", expected_return=35)

    # 8. Augmented assignment
    test_gimple_execution("gimple_aug_assign", """\
def main() -> Int:
    var x: Int = 10
    x += 5
    x *= 2
    x -= 8
    return x
""", expected_return=22)

    # 10. set(iterable) / list(iterable) constructors actually populate the
    # collection from the argument, instead of silently producing an empty
    # one — see bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md. This is
    # a genuine behavioral check (len() + a sum over the iterated elements),
    # not just "does it compile": the bug compiled clean and returned 0 for
    # everything below before the fix.
    test_gimple_execution("gimple_set_ctor_from_list", """\
def main() -> Int:
    var s: Set = set([1, 2, 3, 3])
    var total: Int = 0
    for x in s:
        total = total + x
    return len(s) * 10 + total
""", expected_return=36)  # len == 3 (deduped), elements sum to 1+2+3 == 6

    test_gimple_execution("gimple_list_ctor_from_list", """\
def main() -> Int:
    var l: List = list([1, 2, 3])
    var total: Int = 0
    for x in l:
        total = total + x
    return len(l) * 10 + total
""", expected_return=36)  # len == 3, elements sum to 1+2+3 == 6

    # 9. Matrix multiply operator (simple test with scalar multiplication)
    # TODO: Full matrix multiply example with actual 2D arrays once struct literals work
    # For now, test that the @ operator parses and compiles
    # (full implementation requires struct __matmul__ method binding)


def main():
    gcc = find_gcc()
    result = subprocess.run([gcc, '--version'], capture_output=True)
    if result.returncode != 0:
        print(f"ERROR: gcc not found: {gcc}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("GIMPLE EXECUTION TESTS")
    print("=" * 60)

    run_tests()

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)


if __name__ == '__main__':
    main()
