#!/usr/bin/env python3
"""A C string passed to a `StringSlice[_]` parameter reaches the callee as a
real Span, so a callee that reads the slice does not dereference garbage.

The bug (a StringSlice tuple return segfaulting at run time; fixed): a
`char *` argument to a `Span *` parameter went through the generic
pointer-cast arm, which reinterpreted the string's first bytes as the Span's
`_data`. `get_sign("-abc")` then read `x->_data` from that bogus Span and
died with SIGSEGV on the first `print`. The fix builds the Span at the call
site (emit_infra.py's `_emit_call`).

Every case is checked against the answer real Mojo gives for the same
program (exit 0, the printed value), not against "it did not crash".

Usage:
    python3 test_str_slice_tuple_return.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TIMEOUT = 300

# The original repro: the tuple-returning branch dereferences the slice.
TUPLE_SLICE = '''from std.collections.string import StringSlice

def get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]:
    if x[byte=0] == "-":
        return (-1.0, x[byte=1:])
    return (1.0, x)

def main():
    var s = get_sign("-abc")
    print(s[0])
'''

# The positive branch: the literal's bytes are read through the Span too.
TUPLE_SLICE_POSITIVE = '''from std.collections.string import StringSlice

def get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]:
    if x[byte=0] == "-":
        return (-1.0, x[byte=1:])
    return (1.0, x)

def main():
    var s = get_sign("abc")
    print(s[0])
'''

CASES = {
    'tuple_return_negative_literal': (TUPLE_SLICE, '-1.0\n'),
    'tuple_return_positive_literal': (TUPLE_SLICE_POSITIVE, '1.0\n'),
}

_PASS = 0
_FAIL = 0


def check(name, cond, detail=''):
    global _PASS, _FAIL
    if cond:
        print(f'PASS  {name}')
        _PASS += 1
    else:
        print(f'FAIL  {name}  {detail}')
        _FAIL += 1


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors='replace', timeout=TIMEOUT, cwd=HERE)


def _case(name, src, want):
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, f'{name}.mojo')
        with open(p, 'w') as fh:
            fh.write(src)
        exe = os.path.join(tmp, name)
        b = _run([sys.executable, MOJO, 'build', '-o', exe, p])
        if b.returncode != 0 or not os.path.exists(exe):
            check(name, False, f'BUILD FAILED: {b.stderr.strip().splitlines()[-1:]}')
            return
        r = _run([exe])
        check(name, r.returncode == 0 and r.stdout == want,
              f'exit={r.returncode} stdout={r.stdout!r} want={want!r}')


def main(argv):
    names = argv[1:] or list(CASES)
    for name in names:
        if name not in CASES:
            print(f'SKIP  {name}  (no such case)')
            continue
        src, want = CASES[name]
        _case(name, src, want)
    print(f'\n{_PASS} passed, {_FAIL} failed')
    return 1 if _FAIL else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
