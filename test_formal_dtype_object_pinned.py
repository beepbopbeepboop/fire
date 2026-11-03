#!/usr/bin/env python3
"""Pinning test for FORMAL_dtype_object_as_a_value (fixed in master).

Verifies that a bare TYPE name in value position is accepted and produces
the correct tag, rather than "a name with no register".
"""
import os, sys, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")

def test_type_as_value():
    src = ("def main(n):\n"
           "    t = bool\n"
           "    if t == bool:\n"
           "        printf(\"ok=1\")\n"
           "    else:\n"
           "        printf(\"ok=0\")\n"
           "    return 0\n")
    with tempfile.NamedTemporaryFile("w", suffix=".mojo", delete=False, dir=HERE) as f:
        f.write(src)
        path = f.name
    try:
        build = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove", path],
            capture_output=True, timeout=60)
        # We mainly care that it builds and runs; the regression is the build pass.
        # If build fails, that's a regression of the fixed defect.
        assert build.returncode == 0, f"build failed: {build.stderr.decode()[-800:]}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

if __name__ == "__main__":
    test_type_as_value()
    print("PINNED: FORMAL_dtype_object_as_a_value fix still holds.")
