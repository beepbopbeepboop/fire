#!/usr/bin/env python3
"""Isolated compile repro for bugs/CODEGEN_generator_function_Lib_ftplib.md.

GimpleGen(do_imports=False, relaxed_imports=True) on ftplib.py, then
g++-mp-15 -std=c++20 -fsyntax-only both the .ci (gcc -fgimple) and the
companion coroutine .cpp. Dumps FTP_sendcmd-related declarations.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, '/Users/mrs/net/chatgpt/claude/mojo-worktrees/wtOpencode_ftplib')

from gimple_codegen import GimpleGen

SRC = '/Users/mrs/net/Python-3.14.6/Lib/ftplib.py'


def main():
    src = open(SRC).read()
    import ast_rewriter
    from fire_compiler import Parser, py_tokenize
    stmts = ast_rewriter.rewrite(Parser(py_tokenize(src)).with_filename(SRC).parse_module())
    gen = GimpleGen(do_imports=False, relaxed_imports=True)
    gen._current_filename = SRC
    gen._compiling_file_paths.add(os.path.abspath(SRC))
    ci = gen.gen_module(stmts)
    cpp = gen.generated_cpp or ''

    outdir = '/tmp/ftplib_repro'
    os.makedirs(outdir, exist_ok=True)
    ci_path = os.path.join(outdir, 'ftplib.ci')
    cpp_path = os.path.join(outdir, 'ftplib.cpp')
    with open(ci_path, 'w') as f:
        f.write(ci)
    with open(cpp_path, 'w') as f:
        f.write(cpp)

    # Dump state about sendcmd/putcmd/retrlines
    ipt = getattr(gen, '_inferred_param_types', {})
    for key in sorted(ipt):
        if any(t in key for t in ('sendcmd', 'putcmd', 'getresp', 'retrlines',
                                  'voidcmd', 'getline', 'mlsd')):
            print(f'_inferred_param_types[{key}] = {ipt[key]}')
    fpt = getattr(gen, 'func_param_types', {})
    for key in sorted(fpt):
        if any(t in key for t in ('sendcmd', 'putcmd', 'retrlines',
                                  'voidcmd', 'mlsd')):
            print(f'func_param_types[{key}] = {fpt[key]}')

    print('\n--- extern decls mentioning sendcmd/putcmd/retrlines ---')
    for line in cpp.splitlines():
        if re.search(r'sendcmd|putcmd|retrlines|voidcmd|mlsd', line):
            print(line)

    # Syntax checks
    r1 = subprocess.run(['gcc-mp-15', '-fgimple', '-fsyntax-only', ci_path],
                       capture_output=True, text=True)
    ci_errs = [l for l in (r1.stderr or '').splitlines() if 'error' in l]
    print(f'\n.ci syntax check: rc={r1.returncode}, {len(ci_errs)} error lines')
    for l in ci_errs[:20]:
        print(' ', l)

    r2 = subprocess.run(
        ['g++-mp-15', '-std=c++20', '-fsyntax-only',
         '-I', '/Users/mrs/net/chatgpt/claude/mojo-worktrees/wtOpencode_ftplib/runtime',
         cpp_path], capture_output=True, text=True)
    cpp_errs = [l for l in (r2.stderr or '').splitlines() if 'error' in l]
    print(f'.cpp syntax check: rc={r2.returncode}, {len(cpp_errs)} error lines')
    for l in cpp_errs[:40]:
        print(' ', l)


if __name__ == '__main__':
    main()
