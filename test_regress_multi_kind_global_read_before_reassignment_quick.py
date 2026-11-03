#!/usr/bin/env python3
"""Quick regression: read multi-kind global before reassignment."""
import os, subprocess, sys, tempfile
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')

def _run(cmd, cwd=None, timeout=RUN_TIMEOUT_S):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors='replace', timeout=timeout, cwd=cwd or HERE)

def main():
    src = open('.tmp/regress_src.py').read() if os.path.exists('.tmp/regress_src.py') else '''PREFIX = ["Library", "Frameworks"]
SUFFIX = "--undefined--"

def configure():
    global SUFFIX
    SUFFIX = PREFIX[:] + ["Versions", "3.14"]
    return SUFFIX[:1]

def main():
    print(SUFFIX)
    print(configure())
    print(SUFFIX)
'''
    with open('.tmp/regress_src.py', 'w') as f:
        f.write(src)
    p = '.tmp/regress_src.py'
    exe = '.tmp/regress_bin'
    b = _run([sys.executable, MOJO, 'build', '-o', exe, p], cwd=HERE,
             timeout=COMPILE_TIMEOUT_S)
    if b.returncode != 0 or not os.path.exists(exe):
        print("BUILD FAIL:", b.stderr[-500:] if b.stderr else b.stdout[-500:])
        sys.exit(1)
    r = _run([exe], cwd=HERE)
    print("exit:", r.returncode)
    print("stdout:", repr(r.stdout))
    print("stderr:", (r.stderr or '')[:200])
    sys.exit(0 if r.returncode == 0 else 1)

if __name__ == '__main__':
    sys.exit(main())
