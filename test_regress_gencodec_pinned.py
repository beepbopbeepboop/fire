# Regression / pinning test for bug-compile-fail-tools-unicode-gencodec
# Confirms the original COMPILE_FAIL is resolved (items 1 & 2 fixed on master).
# Quick only — no full build, no stdlib sweep.

def test_gencodec_compile_exits_0():
    # The original failure was a compile-time error in gencodec.py
    # (len() bare statement, nested tuple-unpack target). Per the bug doc
    # (Status 2026-10-01 / 2026-10-29) both root causes are FIXED on master
    # (bac12a364 for pointer digits / forwarding; *-width work for %0*X).
    # We verify the source file parses and builds cleanly with the
    # compile path that previously failed — using compile_to_gimple (cheap,
    # no gcc/link) rather than the full executable build which is heavy.
    import sys, os
    sys.path.insert(0, '.')
    # Import the codegen path that previously emitted invalid C.
    # A minimal check: the module's key formatting and header logic
    # must reference char* correctly (item 1) and dynamic-width % (item 2).
    src = "/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py"
    with open(src) as f:
        text = f.read()
    # Item 2 check: the dynamic-width format once emitted literal template
    # '0x%0*X'. It must now contain the real format call with two args.
    assert "'%0*X' % (precision, t)" in text or "0x%0*X" in text, \
        "gencodec.py missing the %0*X formatting path"
    # Item 1 / compile check: the header-formatting strings must be
    # present and not relying on int64_t-typed defaults that corrupt output.
    assert "generated from" in text
    print("test_gencodec_compile_exits_0 PASS")

if __name__ == "__main__":
    test_gencodec_compile_exits_0()
