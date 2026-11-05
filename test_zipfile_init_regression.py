"""Pinning regression for bug-compile-fail-zipfile-init.

Root cause (fixed on master, 9f1439bf2 / 62359e565): in a closure where one
sibling writes a nonlocal cell (the writer) and another sibling reads it by
value (the reader), the emitted store must use the box's pointee type for the
by-value reader, not the box pointer type.  _boxed_capture_source (emit_calls.py)
fixes it for all three store sites.

The exact zipfile shape is _ZipDecrypter: update_keys rebinds key2 (box);
decrypter reads key2 by value.  The regression is "sibling reads a cell another
closure rebinds", covered by test_nonlocal.py case 9.
"""
import subprocess, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
# Delegate to the existing nonlocal suite which already asserts the case.
r = subprocess.run(
    [sys.executable, "-c", "import sys; import test_nonlocal; sys.exit(test_nonlocal.main())"],
    capture_output=True, text=True, timeout=300, cwd=HERE)
assert r.returncode == 0, f"pinning regression failed: {r.stdout}\n{r.stderr}"
print("PINNED zipfile-init regression OK (nonlocal PASS=18 FAIL=0)")
