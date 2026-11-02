#!/usr/bin/env python3
"""Quick regression for bytes-os-path and len on word kind."""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

CODE = r'''
import os

# len: word kind (bytes from split, then or with bytes -> word)
d = os.path.split(b'*.py')[0]
print(len(d or b'xy'))

# os.path.split / join on bytes
print(len(os.path.split(b'a/b.py')[0]))
print(len(os.path.join(b'/tmp', b'x')))
'''

def main():
    drv = os.path.join(HERE, '.tmp', 'bytes_regress.mojo')
    os.makedirs(os.path.dirname(drv), exist_ok=True)
    with open(drv, 'w') as f:
        f.write(CODE)
    # compile with fire.py build
    exe = drv.replace('.mojo', '')
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv, '-o', exe],
                        capture_output=True, text=True)
    if not os.path.exists(exe):
        print('FAIL build missing\n', (b.stdout + b.stderr)[-1500:])
        return 1
    run = subprocess.run([exe], capture_output=True, text=True)
    got = run.stdout
    # CPython equivalents
    import os as pysysos
    want = []
    d = pysysos.path.split(b'*.py')[0]
    want.append(str(len(d or b'xy')))
    want.append(str(len(pysysos.path.split(b'a/b.py')[0])))
    want.append(str(len(pysysos.path.join(b'/tmp', b'x'))))
    if got.strip().split() != want:
        print('FAIL output differs')
        print('want:', want)
        print('got :', got.strip().split())
        return 1
    print('PASS bytes-os-path and len word dispatch')
    return 0

if __name__ == '__main__':
    sys.exit(main())
