#!/usr/bin/env python3
"""Dump the generated C (and the gcc verdict) for one stdlib .mojo file.

    python3 tools/dumpc.py test/itertools/test_count.mojo [--gcc]

Writes the C next to it as <name>.gen.c in build/ and, with --gcc, runs the
same `gcc -fgimple -fsyntax-only` compile_stdlib.py runs. This is the
inspection tool the bug docs reference; it does not change any gate.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_config import find_gcc
from build_stdlib_dylib import compile_module_to_c
from module_loader import STDLIB_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('relpath')
    ap.add_argument('--gcc', action='store_true')
    ap.add_argument('-o', default=None)
    args = ap.parse_args()

    src_path = os.path.join(STDLIB_PATH, args.relpath)
    src = open(src_path).read()
    name = os.path.splitext(args.relpath)[0].replace(os.sep, '_').replace('-', '_')
    c_src = compile_module_to_c(src, src_path, name)

    out = args.o or os.path.join('build', name + '.gen.c')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        f.write(c_src)
    print(f'wrote {out} ({len(c_src)} bytes)')

    if args.gcc:
        rc = subprocess.run(
            [find_gcc(), '-fgimple', '-Iruntime', '-fsyntax-only',
             '-D__MOJO_STDLIB_MODE__', '-x', 'c', out],
            capture_output=True, text=True)
        print(f'gcc rc={rc.returncode}')
        errs = [l for l in rc.stderr.splitlines() if ': error:' in l]
        for l in errs[:15]:
            print('  ' + l)
        return rc.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
