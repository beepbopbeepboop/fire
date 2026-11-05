# Pinning regression for FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.
# Before fix: print(g(...)) for a no-return g built and printed 0 (wrong word).
# After fix: it is refused with a message naming the callee and CPython's None.

def test_return_less_call_refused_at_print():
    import subprocess, sys, os
    src = ".tmp/reg/probe.mojo"
    os.makedirs(".tmp/reg", exist_ok=True)
    with open(src, "w") as f:
        f.write("def g(a,b):\n    w=1\n\ndef main()->Int32:\n    print(g(1,2))\n    return 0\n")
    out = subprocess.run(
        [sys.executable, "fire.py", "build", "--formal", "--no-prove", "-o", ".tmp/reg/y", src],
        capture_output=True, text=True)
    # Must refuse (non-zero exit) and mention the cause.
    assert out.returncode != 0, "expected refusal, got exit 0 (bug still present)"
    stderr = (out.stderr or "") + (out.stdout or "")
    assert "g returns nothing" in stderr or "returns nothing" in stderr, \
        "expected refusal message naming return-less call; got: %s" % stderr[:500]

if __name__ == "__main__":
    test_return_less_call_refused_at_print()
    print("PASS")
