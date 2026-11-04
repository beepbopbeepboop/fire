#!/usr/bin/env python3
"""Regression for FORMAL_known_limits: bare comptime expression must not be silent.

Before fix: `comptime _s()` evaluates to 0 with no diagnostic.
After fix: it should either evaluate correctly or emit a diagnostic.
Pins the one remaining silent cell from bugs/formal/FORMAL_known_limits.md §7.
"""
import subprocess, sys, tempfile, textwrap, os

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    with tempfile.NamedTemporaryFile("w", suffix=".mojo", delete=False, dir=HERE) as f:
        f.write("def _s() -> Int:\n    return 7\n\nfn main():\n    var a = comptime _s()\n    print(\"val:\", a)\n")
        name = f.name
    try:
        # Build and run — we only assert the build succeeds and does NOT silently
        # return 0 without any on-stdout/on-stderr diagnostic.
        p = subprocess.run([sys.executable, "fire.py", "build", "-o", name + ".bin", name],
                           capture_output=True, text=True, cwd=HERE)
        if p.returncode != 0:
            # Build refusal is acceptable — the key is that it is NOT silent.
            return 0
        r = subprocess.run([name + ".bin"], capture_output=True, text=True)
        # Silent wrong-value (0 with no message) is the failure mode.
        if "val: 0" in (r.stdout or "") and ("unavailable" not in (r.stdout or "")) and ("unavailable" not in (r.stderr or "")):
            print("FAIL: bare comptime <expr> is silent wrong-value (0, no diag)")
            return 1
        return 0
    finally:
        for s in (name, name + ".bin"):
            try:
                os.unlink(s)
            except OSError:
                pass

if __name__ == "__main__":
    sys.exit(main())
