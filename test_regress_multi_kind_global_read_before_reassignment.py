#!/usr/bin/env python3
"""Regression for multi-kind global read before reassignment (CODEGEN_multi_kind)."""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')

def _run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors='replace', timeout=300, cwd=cwd or HERE)

def main():
    src = '''PREFIX = ["Library"]
SUFFIX = "undefined"

def configure():
    global SUFFIX
    SUFFIX = PREFIX[:] + ["Versions", "3.14"]
    return SUFFIX[:1]

def main():
    # READ BEFORE the reassignment runs — must not SIGSEGV
    print(SUFFIX)
    print(configure())
    print(SUFFIX)
'''
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'prog.py')
        with open(p, 'w') as f:
            f.write(src)
        exe = os.path.join(td, 'prog')
        b = _run([sys.executable, MOJO, 'build', '-o', exe, p], cwd=HERE)
        if b.returncode != 0 or not os.path.exists(exe):
            print("BUILD FAIL:", b.stderr[-500:] if b.stderr else b.stdout[-500:])
            sys.exit(1)
        r = _run([exe], cwd=HERE)
        ref = _run([sys.executable, '-c',
                    'PREFIX=["Library"]; SUFFIX="undefined"\n'
                    'def configure():\n'
                    '    global SUFFIX\n'
                    '    SUFFIX = PREFIX[:] + ["Versions", "3.14"]\n'
                    '    return SUFFIX[:1]\n'
                    'def main():\n'
                    '    print(SUFFIX)\n'
                    '    print(configure())\n'
                    '    print(SUFFIX)\n'
                    'main()'], cwd=HERE)
        print("compiled stdout:", repr(r.stdout))
        print("reference stdout:", repr(ref.stdout))
        print("exit:", r.returncode, "stderr:", (r.stderr or '')[:200])
        if r.returncode != 0:
            print("FAIL: compiled program crashed (SIGSEGV?")
            sys.exit(1)
        if r.stdout == ref.stdout:
            print("PASS")
            sys.exit(0)
        else:
            print("FAIL: output mismatch")
            sys.exit(1)

if __name__ == '__main__':
    sys.exit(main())
