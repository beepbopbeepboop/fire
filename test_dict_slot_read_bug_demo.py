#!/usr/bin/env python3
"""Test to demonstrate the dict slot read refusal bug with a mixed-slots generator.

This test creates a module with:
1. A mixed-slots generator (yields more than one kind)
2. A dict subscript read
3. The resulting name rebound to a string
This should trigger MIXED_NAME_NON_INT64_REFUSAL before the fix, but should pass after.
"""

import subprocess
import sys
from pathlib import Path

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
    # Create a module with a mixed-slots generator AND dict slot read with rebind
    src = '''
def g():  # mixed-slots generator (yields int, str, float)
    yield 1
    yield "hello"
    yield 3.14

def test_refusal():
    # Get a tagged word from generator
    gen = g()
    # Read from dict
    d = {"key": None}
    node = d["key"]  # dict subscript read
    # Rebind to a string - this should trigger refusal if tagged word in _tagged_word_vals
    node = "hello"  # rebind to string from dict read
    return node

def main():
    test_refusal()
main()
'''
    
    try:
        out = run(src)
        print("Output:")
        print(out)
        
        # Check if refusal was triggered
        if "refused" in out.lower() or "MIXED_NAME_NON_INT64_REFUSAL" in out.upper():
            print("BUG REPRODUCED: MIXED_NAME_NON_INT64_REFUSAL triggered!")
            print("This confirms the bug: dict read is incorrectly tagged as generator word.")
            return 1
        else:
            print("No refusal detected - test may be passing or bug not present")
            # Check for gcc errors
            if "error" in out.lower():
                print("Other error detected")
            return 0
            
    except subprocess.TimeoutExpired:
        print("Test timed out")
        return 1

if __name__ == "__main__":
    sys.exit(main())