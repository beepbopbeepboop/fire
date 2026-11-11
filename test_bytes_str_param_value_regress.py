#!/usr/bin/env python3
"""Regression: an erased BYTES word coerced into a `char *` (str-typed)
parameter slot must stay a BYTES VALUE, not become its quoted repr.

Root cause pinned (bugs/SUITE_globcompiled, L8): the call-site coercion of an
unprovable int64 word into a `char *` argument — the shape of every erased
value (a dict value, a lambda parameter; and every unannotated parameter of a
Python-source module, where a `str` parameter is lowered to an `int64_t` word
slot) — used the DISPLAY spelling `mojo_cstr_or_int_str`, whose bytes arm
returns the quoted repr. `glob.glob(b'*.py', root_dir=b'...')` therefore
reached `iglob` with the 7-character string `b'*.py'`; CPython's own
`fnmatch._compile_pattern` branches on `isinstance(pat, bytes)`, saw a str,
translated the quoted text, fnmatch'd the literal `b'` prefix, and the result
was [] instead of [b'a.py'].

The probe is `isinstance(x, bytes)`: it is the exact dispatch CPython's
stdlib uses, and in this runtime it is a registry check
(`mojo_isinstance_p(word, 9)`) on the word the callee receives — 1 only if the
coercion handed over the bytes object itself, 0 if it handed over the repr
string. (`len(x)` is deliberately NOT a probe here: on a `str`-typed slot it
lowers to `mojo_str_codepoint_len`, a plain strlen that does not dispatch on
bytes, so it would be testing a different path than the one the stdlib takes.)

Cases: the three dict values are the pin (erased word -> fixed branch ->
must arrive as bytes); the bytes literal fails the same way pre-fix, so it
is a pin too; the str and dict-int cases pin the neighbourhood (strs and
integers must keep their old answers).

Each case is one print line of the compiled program; the expectation is what
CPython prints for the same source. The program and the expectation come from
the same table, so they cannot drift apart.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The callee's parameter is `str`-typed (`char *` slot). `dd['k']` is an
# erased dict value (an int64 word holding a bytes object), so the call site
# goes through the ambiguous word->char* branch this test pins.
HELPERS = '''
def bisbytes(x: str):
    return 1 if isinstance(x, bytes) else 0

dd = {"k1": b"ab", "k2": b"", "k3": b"abcd"}
di = {"a": 5}
'''

CASES = [
    # The pin: a forwarded bytes word. Pre-fix the word reached the callee as
    # its quoted repr (a str), so isinstance saw 0.
    "bisbytes(dd['k1'])",
    # Empty bytes: the repr is the 3-character str b'' — equally not a bytes.
    "bisbytes(dd['k2'])",
    # A longer value, so the answer cannot be a constant.
    "bisbytes(dd['k3'])",
    # Neighbour: a forwarded STR must stay a str.
    "bisbytes('ab')",
    # Pin: a bytes literal through the same slot, measured to fail pre-fix
    # like the dict cases (isinstance saw 0) and to pass on the fix.
    "bisbytes(b'ab')",
    # Neighbour: an erased INTEGER through the same branch keeps the old
    # answer (the decimal string is not a bytes).
    "bisbytes(di['a'])",
]


def build_program():
    lines = ["", HELPERS]
    for expr in CASES:
        lines.append("print(%s)" % expr)
    return "\n".join(lines) + "\n"


def cpython_expected():
    ns = {}
    exec(HELPERS, ns)
    return [str(eval(expr, ns)) for expr in CASES]


def main():
    tmp = os.path.join(HERE, '.tmp')
    os.makedirs(tmp, exist_ok=True)
    drv = os.path.join(tmp, 'bytes_str_param_regress.mojo')
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
        for expr, w, g in zip(CASES, want, got):
            mark = '  ' if w == g else '!!'
            print(f'{mark} {expr}: want {w!r} got {g!r}')
        return 1
    print('PASS bytes value reaches a str-typed param as bytes (%d cases)' % len(CASES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
