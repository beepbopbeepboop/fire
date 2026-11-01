"""Regression for bug:CODEGEN_closure_env_and_boxed_local_never_freed.

The escaping half (a returned closure's captured box lives with it) is
still open — measured slope is ~86 B/iter (10.55 MB at 100k, 36.38 MB at
400k). This test documents that state and serves as a tripwire: if the
single-owner design lands, the slope must go flat (within noise) and the
100k/400k peaks must both sit well under 40 MB with near-zero delta.
"""
import os, sys
sys.path.insert(0, '.')
from test_gimple_runner import compile_mojo_to_gimple_exe

def measure(iterations):
    src = f"""def make_counter(n: Int):
    var x = n
    def bump() -> Int:
        nonlocal x
        x = x + 1
        return x
    return bump

def main():
    var total = 0
    for r in range({iterations}):
        var f = make_counter(r)
        total += f() % 1000
    print(total)
"""
    exe = compile_mojo_to_gimple_exe(src)
    pid = os.fork()
    if pid == 0:
        os.execv(exe, [exe])
    else:
        _, _, rusage = os.wait4(pid, 0)
        peak_mb = rusage.ru_maxrss / (1024.0 * 1024.0)
        try: os.unlink(exe)
        except: pass
        return peak_mb

if __name__ == "__main__":
    mb100 = measure(100000)
    mb400 = measure(400000)
    delta = mb400 - mb100
    slope_bytes = (delta * 1024 * 1024) / 300000.0  # B/iter
    print(f"100k={mb100:.2f}MB 400k={mb400:.2f}MB delta={delta:.2f}MB slope~{slope_bytes:.1f}B/iter")
    # Tripwire: before the fix the slope is ~86 B/iter; after it must be flat.
    if slope_bytes > 20:
        print("TRIPWIRE: slope > 20 B/iter — escaping-half fix not yet applied")
        sys.exit(1)
    else:
        print("PASS: flat slope (escaping half fixed)")
        sys.exit(0)
