"""Build a Mojo program through the real `fire.py build` path, for diagnostics.

The in-process `compile_to_gimple` path does not instantiate a generic function,
so a diagnostic that only the instantiated body can trigger (a `comptime assert`
or `constrained` that is provably false for the argument the call binds) is not
reached there. `fire.py build` writes the instantiated module to a file and
checks that, which is the path a user's program takes. Tests of diagnostics
inside a called generic go through this helper.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def build_refusal(src: str):
    """`(returncode, combined output)` of `fire.py build` on `src`."""
    d = tempfile.mkdtemp(prefix="diag_build_")
    path = os.path.join(d, "t.mojo")
    with open(path, "w") as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, "fire.py"), "build", path,
                        "-o", os.path.join(d, "t.bin")],
                       capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr
