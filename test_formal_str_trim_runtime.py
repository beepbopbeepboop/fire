"""`strip()`/`rstrip()` on a receiver the compiler cannot fold, run on both backends.

The fold covers literals; a function parameter defeats it and takes the emitted
`_emit_str_trim` path. Regressions this pins: arm64 terminated the result with the
low byte of its own address (`mov x2, x0` instead of a zero), and x86-64 used the
wrong stack slot / pop count. Expected text comes from CPython.

    python3 test_formal_str_trim_runtime.py
"""
import os, subprocess, sys, tempfile

SRC = '''def a(s: String) -> String:
    return s.strip()

def b(s: String) -> String:
    return s.rstrip()

def main():
    printf("[%s]", a("  pad  "))
    printf("[%s]", a("pad"))
    printf("[%s]", a("  pad"))
    printf("[%s]", a("pad  "))
    printf("[%s]", b("pad  "))
    printf("[%s]", b("  pad  "))
    return 0
'''
WANT = "".join("[%s]" % x for x in (
    "  pad  ".strip(), "pad".strip(), "  pad".strip(), "pad  ".strip(),
    "pad  ".rstrip(), "  pad  ".rstrip()))

def main():
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.mojo")
        open(src, "w").write(SRC)
        for backend, pre in (("arm64", []), ("x86_64", ["arch", "-x86_64"])):
            exe = os.path.join(d, "t." + backend)
            r = subprocess.run([sys.executable, "fire.py", "build", "--formal", "--no-prove",
                                "--backend=" + backend, "-o", exe, src],
                               capture_output=True, text=True)
            if r.returncode:
                print("FAIL %s build: %s" % (backend, r.stderr[-300:])); bad += 1; continue
            out = subprocess.run(pre + [exe], capture_output=True).stdout.decode("latin-1")
            ok = out == WANT
            print("%s %s: %r" % ("ok  " if ok else "FAIL", backend, out))
            bad += not ok
    print("str trim runtime: %s" % ("PASS" if not bad else "FAIL=%d" % bad))
    return 1 if bad else 0

sys.exit(main())
