"""Regression test for the INDEX half of
CODEGEN_len_of_a_non_ascii_string_counts_bytes.

`len(s)` counts code points on the compiled path (test_nonascii_len_regression),
but `s[i]`, `s[a:b]` and `s.find` still read the `char *` as UTF-8 BYTES, so the
two units disagree: `while i < len(s): s[i]` over "aéb" splits the e-acute
into two invalid one-byte strings. Every row below must print what CPython
prints, on the interpreter (`fire.py run`) AND the compiled path (`--jit`).

KNOWN RED on the compiled path until the string representation lands (see the
bug doc's 2026-10-29 Status); the interpreter column passes today. Not
registered in tools/suite.py for that reason.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_FIRE = os.path.join(HERE, 'fire.py')

TEST_SRC = '''
def walk(s):
    i = 0
    out = []
    while i < len(s):
        out.append(s[i])
        i += 1
    print("|".join(out))

def main():
    s = "a\\u00e9b"
    print(len(s))
    print(len(s[1:]))
    print(s[1])
    print(s.find("b"))
    walk(s)
    walk("\\u00e9" * 3)
    for c in s:
        print(c)
'''


def _run(cmd, path):
    r = subprocess.run(cmd + [path], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    return r.stdout.strip()


def run_test():
    with tempfile.NamedTemporaryFile(suffix='.mojo', mode='w', delete=False,
                                     encoding='utf-8') as f:
        f.write(TEST_SRC + '\nmain()\n')
        tmp = f.name
    try:
        want = _run([sys.executable], tmp)
        ok = True
        for label, cmd in (('interpreter', [sys.executable, _FIRE, 'run']),
                           ('jit', [sys.executable, _FIRE, '--jit'])):
            got = _run(cmd, tmp)
            if got != want:
                print(f'FAIL  {label}: expected {want!r}, got {got!r}')
                ok = False
        if ok:
            print('PASS  nonascii_index_matches_cpython')
        return ok
    finally:
        os.unlink(tmp)


if __name__ == '__main__':
    sys.exit(0 if run_test() else 1)
