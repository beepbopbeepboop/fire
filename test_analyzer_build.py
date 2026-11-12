#!/usr/bin/env python3
"""End-to-end acceptance for bugs/mid/COMPILE_FAIL_Tools_cases_generator_analyzer-part3
(the original bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md):

1. `fire.py build` of CPython's Tools/cases_generator/analyzer.py exits 0 with
   no `error:` line (run under the 8 GB memslot reservation);
2. the compiled analyzer's stdout on Python/bytecodes.c is byte-identical to
   CPython running the same analyzer, and the binary exits 0.

SKIP (exit 0) when the CPython source tree is absent. Locate it with
$PYTHON_SRC, default /Users/mrs/net/Python-3.14.6.

Run: `python3 test_analyzer_build.py`   (~20 s, < 1 GB)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

PY_SRC = os.environ.get('PYTHON_SRC', '/Users/mrs/net/Python-3.14.6')
CG_DIR = os.path.join(PY_SRC, 'Tools', 'cases_generator')
BYTECODES = os.path.join(PY_SRC, 'Python', 'bytecodes.c')
RUN_TIMEOUT = 300


def main() -> int:
    if not (os.path.isfile(os.path.join(CG_DIR, 'analyzer.py'))
            and os.path.isfile(BYTECODES)):
        print(f'SKIP  test_analyzer_build: {CG_DIR}/analyzer.py or {BYTECODES} absent')
        return 0

    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        work = os.path.join(tmp, 'cases_generator')
        shutil.copytree(CG_DIR, work, ignore=shutil.ignore_patterns('__pycache__'))
        exe = os.path.join(tmp, 'analyzer-bin')

        build = subprocess.run(
            [sys.executable, os.path.join(HERE, 'tools', 'memslot.py'), '--gb', '8',
             '--label', 'analyzer-build', '--',
             sys.executable, os.path.join(HERE, 'fire.py'), 'build',
             '-o', exe, os.path.join(work, 'analyzer.py')],
            capture_output=True, text=True, cwd=HERE, timeout=RUN_TIMEOUT)
        out = build.stdout + build.stderr
        errors = [ln for ln in out.splitlines() if 'error:' in ln]
        if build.returncode != 0 or errors:
            print(f'FAIL  test_analyzer_build  build exit {build.returncode}, '
                  f'{len(errors)} error line(s); first: {errors[:1]}')
            return 1

        compiled = subprocess.run([exe, BYTECODES], capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT)
        if compiled.returncode != 0:
            print(f'FAIL  test_analyzer_build  compiled analyzer exit '
                  f'{compiled.returncode}: {compiled.stderr[:500]}')
            return 1

        ref = subprocess.run([sys.executable, 'analyzer.py', BYTECODES],
                             capture_output=True, text=True, cwd=work, timeout=RUN_TIMEOUT)
        if ref.returncode != 0:
            print(f'FAIL  test_analyzer_build  CPython analyzer exit {ref.returncode}: '
                  f'{ref.stderr[:500]}')
            return 1
        if compiled.stdout != ref.stdout:
            print(f'FAIL  test_analyzer_build  compiled output differs from CPython '
                  f'({len(compiled.stdout.splitlines())} vs '
                  f'{len(ref.stdout.splitlines())} lines)')
            return 1

        print('PASS  analyzer.py builds and matches CPython')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
