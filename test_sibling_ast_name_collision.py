#!/usr/bin/env python3
"""Regression for bugs/mid/COMPILE_FAIL_Tools_cases_generator_analyzer-part2:
a sibling module's class whose bare name is one of this compiler's own AST
node names (`IfStmt`, `ForStmt`, `WhileStmt`, `Parser`, ...) must keep its OWN
layout in the generated C, not the compiler's pre-seeded AST layout.

The repro is the real CPython `Tools/cases_generator` parser set
(parsing.py, parser.py, plexer.py, lexer.py, cwriter.py). The toy two-file
fixture passes on the current tree and proves nothing, so it is not used.

Checks (both through compile_to_gimple(do_imports=True)):
  (a) the `IfStmt` typedef carries if_/body/else_ and not then_body/elifs;
  (b) gcc -fgimple -fsyntax-only accepts the generated C with no `error:`.

SKIP (exit 0) when the CPython source tree is absent. Locate it with
$PYTHON_SRC, default /Users/mrs/net/Python-3.14.6.

Run: `python3 test_sibling_ast_name_collision.py`
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from gimple_codegen import compile_to_gimple

SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

PY_SRC = os.environ.get('PYTHON_SRC', '/Users/mrs/net/Python-3.14.6')
CG_DIR = os.path.join(PY_SRC, 'Tools', 'cases_generator')
SIBLINGS = ['parsing.py', 'parser.py', 'plexer.py', 'lexer.py', 'cwriter.py']

MAIN_SRC = '''import parser

def f() -> int:
    s = parser.IfStmt(1, 2, 3, 4, 5)
    return s.if_
'''


def _ifstmt_typedef(c_src: str) -> str | None:
    m = re.search(r'typedef struct IfStmt \{(.*?)\} IfStmt;', c_src, re.S)
    return m.group(1) if m else None


def main() -> int:
    if not os.path.isfile(os.path.join(CG_DIR, 'parsing.py')):
        print(f'SKIP  test_sibling_ast_name_collision: {CG_DIR}/parsing.py absent')
        return 0

    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        for name in SIBLINGS:
            shutil.copy(os.path.join(CG_DIR, name), tmp)
        main_path = os.path.join(tmp, 'main.py')
        with open(main_path, 'w') as f:
            f.write(MAIN_SRC)

        cwd, old_path = os.getcwd(), list(sys.path)
        os.chdir(tmp)
        sys.path.insert(0, tmp)
        try:
            c_src = compile_to_gimple(MAIN_SRC, do_imports=True, filename=main_path)
        finally:
            os.chdir(cwd)
            sys.path[:] = old_path

        body = _ifstmt_typedef(c_src)
        failures = []
        if body is None:
            failures.append('no `typedef struct IfStmt` in the generated C')
        else:
            for field in ('if_', 'body', 'else_'):
                if not re.search(r'\b%s;' % field, body):
                    failures.append(f'IfStmt typedef lacks field {field!r}')
            for field in ('then_body', 'elifs'):
                if re.search(r'\b%s;' % field, body):
                    failures.append(f'IfStmt typedef carries the compiler-layout field {field!r}')

        cfile = os.path.join(tmp, 'main.c')
        with open(cfile, 'w') as f:
            f.write(c_src)
        r = subprocess.run([find_gcc(), '-fgimple', '-fsyntax-only',
                            '-I' + os.path.join(HERE, 'runtime'), cfile],
                           capture_output=True, text=True)
        errors = [ln for ln in r.stderr.splitlines() if 'error:' in ln]
        if r.returncode != 0 or errors:
            failures.append(f'gcc -fgimple reports {len(errors)} error(s); first: '
                            f'{errors[:1]}')

        if failures:
            for msg in failures:
                print(f'FAIL  test_sibling_ast_name_collision  {msg}')
            return 1
        print('PASS  test_sibling_ast_name_collision')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
