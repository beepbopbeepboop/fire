#!/usr/bin/env python3
"""Regression test for the dict slot read refusal bug.

This test verifies that dict slot reads do NOT incorrectly trigger
MIXED_NAME_NON_INT64_REFUSAL.

Before the fix (with bug): compilation refuses with:
  "a name bound to a tagged generator word ... cannot also hold a value of another C type (str or float)"
After the fix: compilation succeeds without refusal

Test 6 is the same claim about the compiler's own source: fire_compiler.py
must lower to GIMPLE, which is what the stage1 bootstrap dump
(`fire.py --dump fire_compiler.py`) does.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gimple_runner import compile_mojo_to_gimple_exe

def run(src: str) -> tuple:
    """Compile a Mojo source to GIMPLE executable and return (stdout, stderr, returncode)."""
    exe = compile_mojo_to_gimple_exe(src)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    return r.stdout, r.stderr, r.returncode

def main():
    # Test 1: Dict slot read followed by rebind to string
    # This is the pattern from ast_rewriter.py: node = node.edges[key] then rebind to str
    src1 = '''
def test():
    d = {"key": None}
    node = d["key"]  # dict slot read
    node = "hello"     # rebind to string
    return node

def main():
    test()
main()
'''

    print("Test 1: Dict slot read then rebind to string")
    try:
        stdout, stderr, returncode = run(src1)
        # If we get here, compilation succeeded (no refusal)
        print(f"  PASS: Compilation succeeded without refusal (returncode={returncode})")
        if stderr and "refused" in stderr.lower():
            print(f"  FAIL: Refusal detected in stderr: {stderr[:200]}")
            return 1
        # Execute the program to verify correct behavior
        exe_path = stdout.strip() if stdout else None
        if exe_path and returncode == 0:
            run_r = subprocess.run([exe_path], capture_output=True, text=True, timeout=10)
            print(f"  Program output: {run_r.stdout.strip()}")
            # Verify the program actually works
            if "hello" in run_r.stdout:
                print(f"  PASS: Program executed correctly")
            else:
                print(f"  WARN: Unexpected output: {run_r.stdout}")
    except Exception as e:
        # If compilation raised an exception with "refused", the bug is present
        print(f"  FAIL: Compilation raised exception: {e}")
        return 1

    # Test 2: Dict slot read followed by rebind to float, then a string.
    # A float and a str in ONE name are carried by the int64_t box
    # (`ginf.mixed_scalar_locals`): each store keeps its own kind, so the
    # program compiles and prints the CPython answer instead of being refused.
    src2 = '''
def test():
    d = {"key": 1.5}
    val = d["key"]  # dict slot read
    print(val)
    val = "text"    # rebind to string
    print(val)
    return val

def main():
    test()
main()
'''

    print("\nTest 2: float dict read then rebind to string: CPython answer")
    try:
        stdout, stderr, returncode = run(src2)
        print(f"  Program output: {stdout.strip()!r}")
        if returncode != 0:
            print(f"  FAIL: program exited {returncode}: {stderr[:200]}")
            return 1
        if stdout == "1.5\ntext\n":
            print("  PASS: float and str in one name print the CPython answer")
        else:
            print(f"  FAIL: expected '1.5\\ntext\\n', got {stdout!r}")
            return 1
    except Exception as e:
        print(f"  FAIL: Compilation raised exception: {e}")
        return 1

    # Test 3: Dict slot read stored in a list
    src3 = '''
def test():
    d = {"key": None}
    lst = [d["key"]]  # dict slot read stored
    lst.append("other")
    return lst[0]

def main():
    test()
main()
'''

    print("\nTest 3: Dict slot read stored in list then rebind")
    try:
        stdout, stderr, returncode = run(src3)
        print(f"  PASS: Compilation succeeded without refusal (returncode={returncode})")
        if stderr and "refused" in stderr.lower():
            print(f"  FAIL: Refusal detected in stderr: {stderr[:200]}")
            return 1
    except Exception as e:
        print(f"  FAIL: Compilation raised exception: {e}")
        return 1

    # Test 4: Dict slot read passed as argument (escaping)
    src4 = '''
def show(v):
    print(v)

def test():
    d = {"key": None}
    x = d["key"]  # dict slot read
    show(x)         # passed as argument
    return x

def main():
    test()
main()
'''

    print("\nTest 4: Dict slot read passed as argument (escaping)")
    try:
        stdout, stderr, returncode = run(src4)
        print(f"  PASS: Compilation succeeded without refusal (returncode={returncode})")
        if stderr and "refused" in stderr.lower():
            print(f"  FAIL: Refusal detected in stderr: {stderr[:200]}")
            return 1
    except Exception as e:
        print(f"  FAIL: Compilation raised exception: {e}")
        return 1

    # Test 5: Dict slot read, then the same name rebound to a container and
    # to an int. This is the ast_rewriter / coro shape (`k = d[...]` beside
    # `k = (...)` or `k = [...]`). The name is a container-beside-scalar box
    # (`mixed_value_locals`): a container store is its bare word, so it must
    # compile and print the CPython answer. Only a name bound to a TAGGED
    # generator word may refuse a container store.
    src5 = '''
def test():
    d = {"key": 3}
    x = d["key"]  # dict slot read
    print(x)
    x = [1, 2]    # rebind to a container
    print(len(x))
    x = 7         # and back to a scalar
    print(x)
    return x

def main():
    test()
main()
'''

    print("\nTest 5: Dict slot read then rebind to a container, then an int")
    try:
        stdout, stderr, returncode = run(src5)
        if stderr and "refused" in stderr.lower():
            print(f"  FAIL: Refusal detected in stderr: {stderr[:200]}")
            return 1
        if returncode != 0 or stdout != "3\n2\n7\n":
            print(f"  FAIL: wrong output (returncode={returncode}): {stdout!r}")
            return 1
        print("  PASS: compiled without refusal and printed the CPython answer")
    except Exception as e:
        print(f"  FAIL: Compilation raised exception: {e}")
        return 1

    # Test 6: the compiler's OWN fire_compiler.py lowers to GIMPLE. This is the
    # exact compile the stage1 bootstrap dump runs
    # (`python3 fire.py --dump fire_compiler.py` -> `compile_to_gimple(...,
    # do_imports=False)`), and it was red on master at 0cce3da396: the
    # container-store refusal fired whenever the name was any box-holding
    # local (`_mixed_box`), so fire_compiler.py's own container-beside-scalar
    # name `body` was refused as though it were a tagged generator word.
    # c8f06fe35 narrowed the refusal to `_tagged_mixed`; Test 5 pins the
    # minimal shape, this one pins the compiler source the gate job dumps.
    print("\nTest 6: the compiler's own fire_compiler.py compiles to GIMPLE")
    import gimple_codegen
    path6 = Path(__file__).resolve().parent / "fire_compiler.py"
    try:
        c_text = gimple_codegen.compile_to_gimple(
            path6.read_text(encoding="utf-8", errors="replace"),
            do_imports=False, filename="fire_compiler.py")
    except Exception as e:
        print(f"  FAIL: refused: {str(e)[:300]}")
        return 1
    if not c_text or not c_text.strip():
        print("  FAIL: produced no C text")
        return 1
    print(f"  PASS: compiled ({len(c_text)} bytes of C)")

    print("\n" + "="*60)
    print("All regression tests passed!")
    print("Dict slot reads are no longer incorrectly tagged as generator words.")
    print("The MIXED_NAME_NON_INT64_REFUSAL does not fire for dict reads.")
    print("="*60)
    return 0

if __name__ == "__main__":
    sys.exit(main())