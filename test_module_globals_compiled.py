#!/usr/bin/env python3
"""Regression for the module-scope `globals()` compile failure in
`Tools/cases_generator/analyzer.py`.

Tools/cases_generator/lexer.py builds its operator table from the module's own
uppercase constants, then rebinds each of those names to its own spelling:

    operators = {op: pattern for op, pattern in globals().items() if op == op.upper()}
    for op in operators:
        globals()[op] = op

Compiled, the `globals()` call is emitted as a weak "globals: unavailable in
compiled mode" stub, so the binary prints that line and then raises. The
program below is that idiom in miniature. It must build with `fire.py build`,
run, and print exactly what CPython prints.

Run: `python3 test_module_globals_compiled.py`   (a few seconds, < 1 GB)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

PROGRAM = r'''
ASSIGN = r"="
PLUS = r"\+"
LPAREN = r"\("
not_upper = 1
operators = {op: pattern for op, pattern in globals().items() if op == op.upper()}
for op in operators:
    globals()[op] = op
opmap = {pattern.replace("\\", "") or "\\": op for op, pattern in operators.items()}
print(sorted(operators))
print(ASSIGN, PLUS, LPAREN)
print(sorted(opmap.items()))
print(not_upper)
'''


def main() -> int:
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        src = os.path.join(tmp, 'globals_prog.py')
        with open(src, 'w') as f:
            f.write(PROGRAM)

        ref = subprocess.run([sys.executable, src], capture_output=True, text=True,
                             timeout=120)
        if ref.returncode != 0:
            print(f'FAIL  test_module_globals_compiled  CPython exit {ref.returncode}: '
                  f'{ref.stderr[:500]}')
            return 1

        exe = os.path.join(tmp, 'globals-bin')
        build = subprocess.run(
            [sys.executable, os.path.join(HERE, 'tools', 'memslot.py'), '--gb', '8',
             '--label', 'module-globals-build', '--',
             sys.executable, os.path.join(HERE, 'fire.py'), 'build', '-o', exe, src],
            capture_output=True, text=True, cwd=HERE, timeout=300)
        out = build.stdout + build.stderr
        if build.returncode != 0 or any('error:' in ln for ln in out.splitlines()):
            print(f'FAIL  test_module_globals_compiled  build exit {build.returncode}: '
                  f'{[ln for ln in out.splitlines() if "error:" in ln][:1]}')
            return 1

        got = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        if got.returncode != 0 or 'unavailable in compiled mode' in got.stdout + got.stderr:
            print(f'FAIL  test_module_globals_compiled  binary exit {got.returncode}: '
                  f'{(got.stdout + got.stderr)[:500]!r}')
            return 1
        if got.stdout != ref.stdout:
            print('FAIL  test_module_globals_compiled  binary output differs from CPython:\n'
                  f'  cpython: {ref.stdout!r}\n  binary:  {got.stdout!r}')
            return 1

        print('PASS  module-scope globals() matches CPython in the compiled path')
        return 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
