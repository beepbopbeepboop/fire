"""Regression for the escaping half of the closure-env / boxed-local leak: a
returned `{mut}`-capturing closure's environment, box and bound-method entry
were never freed (the single-owner design now frees them with the closure at
its owner's scope exit).

Before the fix the slope was ~90 B/iter (10.55 MB at 100k, 36.39 MB at 400k).
After the single-owner fix it is flat: the 100k/400k peaks both sit at ~2 MB
with near-zero delta. This test is the tripwire that pins that flat profile —
if the escaping half regresses (e.g. the fresh-closure ownership is disabled),
the slope climbs again and this fails.
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
