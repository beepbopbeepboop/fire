#!/usr/bin/env python3
"""Test to demonstrate the dict slot read refusal bug.

This test creates a module where a dict slot read result is rebound to a different type,
which should trigger MIXED_NAME_NON_INT64_REFUSAL before the fix, but should pass after.
"""

import subprocess
import sys
from pathlib import Path

# Add the current directory to the path so we can import our test helpers
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gimple_runner import compile_mojo_to_gimple_exe

def run(src: str) -> str:
    exe = compile_mojo_to_gimple_exe(src)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"Command failed with exit code {r.returncode}")
        print(f"stderr: {r.stderr}")
        print(f"stdout: {r.stdout}")
    return r.stdout

def main():
    # Create a module where a dict read is used, then the result is rebound to a str
    # This should trigger the refusal before the fix
    src = '''
def problematic():
    d = {'key': None}  # dict read with None value
    # The next line should cause refusal if dict reads are incorrectly tagged
    node = d['key']  # dict subscript read
    node = "string"      # rebind to a string - this should cause refusal if tagged
    return node

def main():
    problematic()
main()
'''
    
    try:
        out = run(src)
        print("Output:")
        print(out)
        if "refused" in out.lower() or "MIXED_NAME_NON_INT64_REFUSAL" in out.upper():
            print("BUG REPRODUCED: MIXED_NAME_NON_INT64_REFUSAL triggered!")
            return 1
        else:
            print("No refusal detected - test may be passing or bug not present")
            return 0
    except subprocess.TimeoutExpired:
        print("Test timed out")
        return 1

if __name__ == "__main__":
    sys.exit(main())