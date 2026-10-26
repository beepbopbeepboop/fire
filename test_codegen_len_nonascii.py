import subprocess, sys, os

def run_jit(src):
    p = '.tmp/_lenc.mojo'
    os.makedirs('.tmp', exist_ok=True)
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, 'fire.py', '--jit', p],
                       capture_output=True, text=True)
    return r.stdout.strip(), r.returncode

def test_len_nonascii_codepoints():
    src = ('def main():\n'
           '    print(len("\\u00e9"))\n'
           '    print(len("\\U0001F600"))\n'
           '    print(len("\\N{LATIN SMALL LETTER E WITH ACUTE}"))\n'
           '    print(len("é"))\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '1\n1\n1\n1', repr(out)

if __name__ == '__main__':
    test_len_nonascii_codepoints()
    print("OK")