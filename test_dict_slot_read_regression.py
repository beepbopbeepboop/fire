#!/usr/bin/env python3
"""Regression: a dict subscript read must carry the slot's runtime value kind.

`d['k']` for a dict whose value kind is not recoverable from the bare int64_t
word used to print as 0/1/bits. Stringification/repr of the read now consults
the slot's runtime kind via `mojo_dict_repr_slot`.
"""

import subprocess
import sys
from pathlib import Path

# Import helpers from the gimple runner (same tree).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gimple_runner import compile_mojo_to_gimple_exe  # noqa: E402


def run(src: str) -> str:
    exe = compile_mojo_to_gimple_exe(src)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (
        f"exit {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    )
    return r.stdout


def main():
    # Direct subscript reads: None and bool must not collapse to 0/1.
    out = run(r'''
def main():
    d = {}
    d['n'] = None
    d['b'] = True
    d['f'] = False
    print(d['n'])
    print(d['b'])
    print(d['f'])
    print(str(d['n']), repr(d['b']))
main()
''')
    assert out == "None\nTrue\nFalse\nNone True\n", repr(out)

    # Assigned to locals, the slot kind must still be visible.
    out = run(r'''
def main():
    d = {}
    d['n'] = None
    d['b'] = True
    x = d['n']
    y = d['b']
    print(x, y)
    print(str(x), repr(y))
main()
''')
    assert out == "None True\nNone True\n", repr(out)

    # A homogeneous literal whose per-read kind matters.
    out = run(r'''
def main():
    d = {'x': True, 'y': False}
    print(d['x'], d['y'])
main()
''')
    assert out == "True False\n", repr(out)

    # Bytes-keyed and None-keyed reads also carry the slot's runtime kind.
    out = run(r'''
def main():
    d = {}
    d[b'k'] = True
    d[b'n'] = None
    d[b'f'] = False
    print(d[b'k'], d[b'n'], d[b'f'])
    x = d[b'n']
    print(x, str(x), repr(x))
main()
''')
    assert out == "True None False\nNone None None\n", repr(out)

    out = run(r'''
def main():
    d = {}
    d[None] = False
    d['x'] = None
    print(d[None], d['x'])
    y = d[None]
    print(y, repr(y))
main()
''')
    assert out == "False None\nFalse False\n", repr(out)

    print("test_dict_slot_read_regression: ok")


if __name__ == "__main__":
    main()
