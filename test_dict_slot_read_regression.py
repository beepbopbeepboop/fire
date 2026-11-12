#!/usr/bin/env python3
"""Regression test for the dict slot read refusal bug.

This test verifies that dict slot reads do NOT incorrectly trigger
MIXED_NAME_NON_INT64_REFUSAL.

Before the fix (with bug): compilation refuses with:
  "a name bound to a tagged generator word ... cannot also hold a value of another C type (str or float)"
After the fix: compilation succeeds without refusal
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

    # Test 2: Dict slot read followed by rebind to float
    src2 = '''
def test():
    d = {"key": 1.5}
    val = d["key"]  # dict slot read
    val = "text"    # rebind to string
    return val

def main():
    test()
main()
'''

    # A float and a str in ONE name have no representation (the box carries only int kinds). The compiler refuses the
    # program with the mixed-name reason, rather than emitting a double-to-pointer cast gcc rejects.
    print("\nTest 2: float dict read then rebind to string: refused with the mixed-name reason")
    try:
        run(src2)
        print("  FAIL: compiled, but a float and a str share one name")
        return 1
    except RuntimeError as e:
        if "cannot also hold a value of another C type" in str(e):
            print("  PASS: refused with the mixed-name reason")
        else:
            print(f"  FAIL: refused for another reason: {str(e)[:200]}")
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

    print("\n" + "="*60)
    print("All regression tests passed!")
    print("Dict slot reads are no longer incorrectly tagged as generator words.")
    print("The MIXED_NAME_NON_INT64_REFUSAL does not fire for dict reads.")
    print("="*60)
    return 0

if __name__ == "__main__":
    sys.exit(main())