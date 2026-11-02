#!/usr/bin/env python3
"""Quick regression for bytes-pattern re.compile / fnmatch."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = r'''
import fnmatch, re
print(fnmatch.translate("*.py"))
print(fnmatch.translate(b"*.py"))
print(re.compile(".*").search("abc"))
print(re.compile(b".*").search(b"abc"))
print(re.compile(b".*").match(b"abc"))
print(re.compile(b".*").fullmatch(b"abc"))
'''

def main():
    prog = tempfile.mkdtemp(prefix='re_reg_')
    drv_path = os.path.join(prog, 'drv.py')
    with open(drv_path, 'w') as f:
        f.write(DRIVER)
    want = subprocess.run([sys.executable, drv_path], capture_output=True, text=True).stdout
    exe = os.path.join(prog, 'drv')
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv_path, '-o', exe], capture_output=True, text=True)
    if not os.path.exists(exe):
        print('FAIL build missing\n', (b.stdout+b.stderr)[-1500:])
        return 1
    got = subprocess.run([exe], capture_output=True).stdout.decode('utf-8', 'replace')
    lines_want = [l for l in want.splitlines() if l.startswith('b') or 'compile' in l or 're' in l]
    if got != want:
        print('FAIL compiled re bytes differs from CPython')
        print('--- CPython ---')
        print(want)
        print('--- compiled ---')
        print(got)
        return 1
    print('PASS compiled re bytes matches CPython')
    return 0
if __name__ == '__main__':
    sys.exit(main())
