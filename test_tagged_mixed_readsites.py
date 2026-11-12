import os
import subprocess
import sys
import tempfile

def run_cpython(src):
    r = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'CPython failed: {r.stderr}')
    return r.stdout

def build_and_run(src, workdir):
    path = os.path.join(workdir, 'case.mojo')
    out = os.path.join(workdir, 'case_bin')
    with open(path, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, 'tools/memslot.py', '--gb', '8', '--label', 'tagged-mixed-readsites',
                        '--', sys.executable, 'fire.py', 'build', path, '-o', out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'build failed:\n{r.stdout}\n{r.stderr}')
    r = subprocess.run([out], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'run failed rc={r.returncode}:\n{r.stdout}\n{r.stderr}')
    return r.stdout

def str_box_binops():
    src = r'''
def g():
    yield 1
    yield "a"
    yield 3
def main():
    x = 0
    for v in g():
        x = v
        print(x * 2)
        print(x + x)
main()
'''
    expected = run_cpython(src)
    with tempfile.TemporaryDirectory(dir='.tmp') as d:
        got = build_and_run(src, d)
    if got != expected:
        print('EXPECTED:', repr(expected))
        print('GOT:     ', repr(got))
        raise SystemExit(1)
    print('ok')

CASES = {
    'str_box_binops': str_box_binops,
}

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        print(f'usage: {sys.argv[0]} <case>', file=sys.stderr)
        print('cases:', ', '.join(CASES), file=sys.stderr)
        raise SystemExit(2)
    CASES[sys.argv[1]]()
