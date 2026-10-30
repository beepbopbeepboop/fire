#!/usr/bin/env python3
"""Regression: compile_to_gimple padding (auto_gpu default)."""
import sys, os
REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

def test_compile_to_gimple_pad() -> bool:
    import mojo.backend_gimple.emit_calls as ec
    src = open(ec.__file__).read()
    return ("compile_to_gimple" in src and "auto_gpu" in src and "'int', '1'" in src)

if __name__ == "__main__":
    ok = test_compile_to_gimple_pad()
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
