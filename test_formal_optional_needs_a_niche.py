"""
Regression test for the imported Optional parameter bug (FORMAL_optional_needs_a_niche).

The root cause bug: when None was passed to an imported function's Optional[T] parameter,
the callee compared the folded 0 word (None's word) against T's niche (e.g., 2 for Bool)
and took the "has a value" arm, answering as if Some(0) had been provided instead of None.

This was fixed by resolving imported callee parameter annotations through
formal/imports.py's external_declarations in apply_optional_none_representation,
and substituting the niche before the None name folds.

This test should FAIL before the fix and PASS after.
"""

import subprocess
import tempfile
import os
import sys


def test_imported_optional_param_none():
    """None passed to imported Optional[Bool] param must answer the None case."""
    tmpdir = tempfile.mkdtemp()

    # lib3.mojo - the imported callee with an Optional parameter
    lib3_path = os.path.join(tmpdir, "lib3.mojo")
    with open(lib3_path, "w") as f:
        f.write(
            "def tb(z: Optional[Bool]) -> int:\n"
            "    if z is None:\n"
            "        return 100\n"
            "    return 1 if z else 2\n"
        )

    # main3.mojo - calls tb(None) expecting 100 (None case)
    main3_path = os.path.join(tmpdir, "main3.mojo")
    with open(main3_path, "w") as f:
        f.write("from lib3 import tb\n")
        f.write('printf("%d\\n", tb(None))\n')

    fire = "/Users/mrs/net/chatgpt/claude/mojo-reference/fire.py"
    build_cmd = [
        "python3", fire,
        "build", "--formal", "--no-prove",
        "--backend=arm64", "-o", "main3", main3_path,
    ]

    build = subprocess.run(
        build_cmd, cwd=tmpdir, capture_output=True, text=True
    )

    if build.returncode != 0:
        print(f"Build stderr:\n{build.stderr}")
        print(f"Build stdout:\n{build.stdout}")
        sys.exit(f"Build failed: {build.returncode}")

    run_cmd = [os.path.join(tmpdir, "main3")]
    run = subprocess.run(run_cmd, capture_output=True, text=True)

    output = run.stdout.strip()
    expected = "100"

    if output != expected:
        sys.exit(
            f"Regression bug still present: expected {expected!r}, "
            f"got {output!r}. None was not treated as None."
        )

    print("PASSED: tb(None) correctly returns 100 (None branch taken).")


if __name__ == "__main__":
    test_imported_optional_param_none()