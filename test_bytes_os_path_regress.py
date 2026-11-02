#!/usr/bin/env python3
"""Regression: os.path.* and len() on a BYTES value read as text (os.path / len lowered as str only).

Each case is one print line of the compiled program; the expected line is what
CPython prints for the same source. The program and the expectation come from
the same table, so they cannot drift apart.
"""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

# (source expression, how it is printed). Booleans are printed as 1/0 so the
# compiled and CPython outputs are the same bytes.
CASES = [
    # len() of a bytes value that came out of os.path.split (a word element).
    ("len(os.path.split(b'*.py')[0] or b'xy')",   "len"),
    ("len(os.path.split(b'a/b.py')[0])",          "len"),
    # os.path.join of bytes is bytes.
    ("len(os.path.join(b'/tmp', b'x'))",          "len"),
    # os.path.basename / dirname of bytes are bytes; an empty result is falsy,
    # so `or` must fall through to the right operand.
    ("len(os.path.basename(b'a/b.py'))",          "len"),
    ("len(os.path.dirname(b'a/b.py'))",           "len"),
    ("len(os.path.dirname(b'/a'))",               "len"),
    ("len(os.path.basename(b'x/') or b'none')",   "len"),
    # splitext of bytes: the root and the extension are bytes.
    ("len(os.path.splitext(b'a/b.py')[0])",       "len"),
    ("len(os.path.splitext(b'a/b.py')[1])",       "len"),
    ("len(os.path.splitext(b'noext')[0])",        "len"),
    # The predicates answer for a bytes path.
    ("1 if os.path.exists(b'/') else 0",          "int"),
    ("1 if os.path.isdir(b'/') else 0",           "int"),
    ("1 if os.path.isfile(b'/') else 0",          "int"),
    ("1 if os.path.exists(b'/no-such-path-xyz') else 0", "int"),
]


def build_program():
    lines = ["import os"]
    for expr, _ in CASES:
        lines.append(f"print({expr})")
    return "\n".join(lines) + "\n"


def cpython_expected():
    out = []
    ns = {"os": os}
    for expr, _ in CASES:
        out.append(str(eval(expr, ns)))
    return out


def main():
    tmp = os.path.join(HERE, '.tmp')
    os.makedirs(tmp, exist_ok=True)
    drv = os.path.join(tmp, 'bytes_regress.mojo')
    with open(drv, 'w') as f:
        f.write(build_program())
    exe = drv[:-len('.mojo')]
    # A binary left by an earlier run must not stand in for this build.
    if os.path.exists(exe):
        os.remove(exe)
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv, '-o', exe],
                       capture_output=True, text=True)
    if b.returncode != 0 or not os.path.exists(exe):
        print('FAIL build (exit %d)\n' % b.returncode, (b.stdout + b.stderr)[-1500:])
        return 1
    run = subprocess.run([exe], capture_output=True, text=True)
    got = run.stdout.split('\n')[:len(CASES)]
    want = cpython_expected()
    if got != want:
        print('FAIL output differs')
        for (expr, _), w, g in zip(CASES, want, got):
            mark = '  ' if w == g else '!!'
            print(f'{mark} {expr}: want {w!r} got {g!r}')
        return 1
    print('PASS bytes os.path and len dispatch (%d cases)' % len(CASES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
