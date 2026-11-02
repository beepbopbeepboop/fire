"""Regression test for CODEGEN_len_of_a_non_ascii_string_counts_bytes.

Before the fix, len(s) counted UTF-8 bytes (strlen) for plain char* strings
and MojoStr* byte lengths (MojoStr.len), giving 2 for "é" instead of 1.
After the fix, len(s) counts UTF-8 code points (mojo_str_codepoint_len).
"""

import sys, os, subprocess, tempfile
HERE = os.path.dirname(__file__)
_FIRE = os.path.join(os.path.dirname(HERE), 'fire.py')

TEST_SRC = '''
def main():
    # Four-line measurement from the bug doc
    print(len("\\u00e9"))
    print(len("\\U0001F600"))
    print(len("\\N{LATIN SMALL LETTER E WITH ACUTE}"))
    # Actual non-ASCII character literal
    print(len("\\u00e9"))
'''

def run_test():
    with tempfile.NamedTemporaryFile(suffix='.mojo', mode='w', delete=False) as f:
        f.write(TEST_SRC)
        tmp = f.name
    try:
        # 1. Get CPython reference output
        cp = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=30)
        want = cp.stdout.strip()
        
        # 2. Run via interpreter (fire.py run)
        ri = subprocess.run(
            [sys.executable, _FIRE, 'run', tmp],
            capture_output=True, text=True, timeout=30)
        got_i = ri.stdout.strip()
        
        # 3. Run via JIT (fire.py --jit)
        rj = subprocess.run(
            [sys.executable, _FIRE, '--jit', tmp],
            capture_output=True, text=True, timeout=30)
        got_j = rj.stdout.strip()
        
        # Both should match CPython: four lines of "1"
        want_lines = want.splitlines()
        ok = True
        if got_i != want:
            print(f'FAIL  interpreter: expected {want!r}, got {got_i!r}')
            ok = False
        if got_j != want:
            print(f'FAIL  jit: expected {want!r}, got {got_j!r}')
            ok = False
        if ok:
            print('PASS  nonascii_len_matches_cpython')
        return ok
    finally:
        os.unlink(tmp)

if __name__ == '__main__':
    ok = run_test()
    sys.exit(0 if ok else 1)