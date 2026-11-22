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
import re
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

# `file:line:col: error:` — the shape of every gcc/codegen diagnostic that
# carries a location. Used to tell THIS program's diagnostics from the stdlib
# dylib's own fallback blocks; see `_program_errors`.
_LOCATED_ERROR = re.compile(r'\S+:\d+:\d+: error:')
# gcc's source-echo line under a located diagnostic (`  634 |   code`). It repeats
# the offending source text, so it can contain `error:` without being one.
_SOURCE_ECHO = re.compile(r'^\s*\d+\s*\|')


def _program_errors(out: str, src: str) -> list:
    """`error:` lines attributable to THIS program's own translation.

    `fire.py build` compiles the stdlib dylib on demand and streams its
    per-module fallback diagnostics to the same stdout/stderr: a
    `  skip <module>: ... error: ...` line per module that did not compile,
    plus the gcc block that killed it (whose first line is
    `<stdlib path>:<line>:<col>: error: ...`). Those are the `stdlib-dylib`
    job's verdict, which it reaches by comparing that job's skip count -- not
    a verdict on THIS program, which does not import the failing module and
    still builds and runs correctly. Counting them here made this job red
    whenever an unrelated stdlib module regressed (2026-11-15: a `(void)`
    extern for the overloaded `std.time.sleep` made
    `std/testing/assert_aborts.mojo` fall back), so only a diagnostic that
    names THIS program's source, or one carrying no location at all (the
    compiler's own refusals), counts.
    """
    src = os.path.abspath(src)
    errs = []
    for ln in out.splitlines():
        if 'error:' not in ln or _SOURCE_ECHO.match(ln):
            continue
        if src in ln or _LOCATED_ERROR.search(ln) is None:
            errs.append(ln)
    return errs


def _filter_selfcheck(src: str) -> str | None:
    """Pin both directions of `_program_errors`' provenance rule.

    The filter IS part of the guard: widened back to "any line containing
    `error:`", this test goes red whenever the stdlib dylib falls back for a
    module it does not use, which is the `stdlib-dylib` job's verdict and not
    this one's. Narrowed to "only the program's own file", a location-less
    compiler refusal would be missed.
    """
    stdlib_block = (
        '  skip ../new-modular/Mojo/stdlib/std/x.mojo: '
        '/s/stdlib/std/x.mojo:2:0: error: nope\n'
        '/s/stdlib/std/x.mojo:9:3: error: too many arguments\n')
    if _program_errors(stdlib_block, src):
        return 'stdlib fallback diagnostics are attributed to the program'
    own = f'{src}:1:1: error: own program diagnostic\n'
    if _program_errors(own, src) != [own.rstrip('\n')]:
        return 'a program diagnostic carrying its own path is not reported'
    bare = 'error: violated constraint\n'
    if _program_errors(bare, src) != [bare.rstrip('\n')]:
        return 'a location-less compiler refusal is not reported'
    # The gcc source excerpt under a stdlib fallback's located `error:` line
    # echoes the stdlib source line, and that line can contain the word
    # `error:` (std/testing/suite.mojo:634 is `if error:`). It is an echo of
    # the stdlib's text, not a diagnostic, so it must not be attributed here.
    excerpt = (
        '  skip ../new-modular/Mojo/stdlib/std/testing/suite.mojo: '
        '/s/stdlib/std/testing/suite.mojo:634:13: error: bad\n'
        '  634 |             if error:\n'
        '      |             ^~~~~~~~~\n')
    if _program_errors(excerpt, src):
        return 'a stdlib source excerpt containing "error:" is attributed to the program'
    return None


def main() -> int:
    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        src = os.path.join(tmp, 'globals_prog.py')
        with open(src, 'w') as f:
            f.write(PROGRAM)

        bad = _filter_selfcheck(src)
        if bad:
            print(f'FAIL  test_module_globals_compiled  {bad}')
            return 1

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
        errs = _program_errors(build.stdout + build.stderr, src)
        if build.returncode != 0 or errs:
            print(f'FAIL  test_module_globals_compiled  build exit {build.returncode}: '
                  f'{errs[:1]}')
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
