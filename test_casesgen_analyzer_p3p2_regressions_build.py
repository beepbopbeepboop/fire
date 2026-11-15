#!/usr/bin/env python3
"""End-to-end regression driver for
test_casesgen_analyzer_p3p2_regressions.py:

1. `fire.py build` of the sibling source exits 0 with no `error:` line
   (run under the 8 GB memslot reservation);
2. the compiled binary's stdout is byte-identical to CPython running
   the same source.

The sibling source fails (divergent output) on the pre-fix compiler and
passes on the fixed one — see the sibling file's docstring for which root
cause each output line pins down.

Run: `python3 test_casesgen_analyzer_p3p2_regressions_build.py`
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

SIBLING = os.path.join(
    HERE, 'test_casesgen_analyzer_p3p2_regressions.py')
RUN_TIMEOUT = 300


def main() -> int:
    if not os.path.isfile(SIBLING):
        print(f'SKIP  sibling source absent: {SIBLING}')
        return 0

    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        src = os.path.join(tmp, os.path.basename(SIBLING))
        shutil.copyfile(SIBLING, src)
        exe = os.path.join(tmp, 'casesgen-p3p2-bin')

        build = subprocess.run(
            [sys.executable, os.path.join(HERE, 'tools', 'memslot.py'), '--gb', '8',
             '--label', 'casesgen-p3p2-build', '--',
             sys.executable, os.path.join(HERE, 'fire.py'), 'build',
             '-o', exe, src],
            capture_output=True, text=True, cwd=HERE, timeout=RUN_TIMEOUT)
        out = build.stdout + build.stderr
        errors = [ln for ln in out.splitlines() if 'error:' in ln]
        if build.returncode != 0 or errors:
            print(f'FAIL  casesgen-p3p2 build exit {build.returncode}, '
                  f'{len(errors)} error line(s); first: {errors[:1]}')
            return 1

        compiled = subprocess.run([exe], capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT)
        if compiled.returncode != 0:
            print(f'FAIL  casesgen-p3p2 compiled exit {compiled.returncode}: '
                  f'{compiled.stderr[:500]}')
            return 1

        ref = subprocess.run([sys.executable, src], capture_output=True,
                             text=True, cwd=tmp, timeout=RUN_TIMEOUT)
        if ref.returncode != 0:
            print(f'FAIL  casesgen-p3p2 CPython exit {ref.returncode}: '
                  f'{ref.stderr[:500]}')
            return 1
        if compiled.stdout != ref.stdout:
            print(f'FAIL  casesgen-p3p2 compiled output differs from CPython:\n'
                  f'--- compiled ---\n{compiled.stdout}\n--- CPython ---\n'
                  f'{ref.stdout}')
            return 1

        print('PASS  casesgen p3p2 regressions build and match CPython')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
