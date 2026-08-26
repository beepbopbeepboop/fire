#!/usr/bin/env python3
"""Isolated compile repro for bugs/CODEGEN_generator_function_Lib_ftplib.md.

GimpleGen(do_imports=False, relaxed_imports=True) on ftplib.py, then
gcc-mp-15 -fgimple -fsyntax-only the .ci and g++-mp-15 -std=c++20
-fsyntax-only the companion coroutine .cpp.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gimple_codegen import GimpleGen

SRC = '/Users/mrs/net/Python-3.14.6/Lib/ftplib.py'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = open(SRC).read()
    import ast_rewriter
    from mojo_compiler import Parser, py_tokenize
    stmts = ast_rewriter.rewrite(Parser(py_tokenize(src)).with_filename(SRC).parse_module())
    gen = GimpleGen(do_imports=False, relaxed_imports=True)
    gen._current_filename = SRC
    gen._compiling_file_paths.add(os.path.abspath(SRC))
    ci = gen.gen_module(stmts)
    cpp = gen.generated_cpp or ''

    outdir = '/tmp/ftplib_repro_g3'
    os.makedirs(outdir, exist_ok=True)
    ci_path = os.path.join(outdir, 'ftplib.ci')
    cpp_path = os.path.join(outdir, 'ftplib.cpp')
    with open(ci_path, 'w') as f:
        f.write(ci)
    with open(cpp_path, 'w') as f:
        f.write(cpp)

    # Syntax checks
    r1 = subprocess.run(['gcc-mp-15', '-fgimple', '-fsyntax-only', ci_path],
                       capture_output=True, text=True)
    ci_errs = [l for l in (r1.stderr or '').splitlines() if 'error' in l]
    print(f'.ci syntax check: rc={r1.returncode}, {len(ci_errs)} error lines')
    for l in ci_errs[:20]:
        print(' ', l)

    r2 = subprocess.run(
        ['g++-mp-15', '-std=c++20', '-fsyntax-only',
         '-I', os.path.join(REPO, 'runtime'),
         cpp_path], capture_output=True, text=True)
    cpp_errs = [l for l in (r2.stderr or '').splitlines() if 'error' in l]
    print(f'.cpp syntax check: rc={r2.returncode}, {len(cpp_errs)} error lines')
    for l in cpp_errs[:40]:
        print(' ', l)


if __name__ == '__main__':
    main()
