# Pinning regression for FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.
# Fixed: a function that falls off the end returns None (CPython semantics).

def test_return_less_call_returns_none():
    import subprocess, sys, os
    src = ".tmp/reg/probe2.mojo"
    os.makedirs(".tmp/reg", exist_ok=True)
    with open(src, "w") as f:
        f.write("def g(a,b):\n    w=1\n\ndef main()->Int32:\n    print(g(1,2))\n    return 0\n")
    out = subprocess.run(
        [sys.executable, "fire.py", "build", "--formal", "--no-prove", "-o", ".tmp/reg/y2", src],
        capture_output=True, text=True)
    assert out.returncode == 0, "build failed: %s" % (out.stderr or out.stdout)[:500]
    # Run it
    run = subprocess.run([".tmp/reg/y2"], capture_output=True, text=True)
    assert "None" in run.stdout, "expected None, got: %s" % run.stdout


if __name__ == "__main__":
    test_return_less_call_returns_none()
    print("PASS")
