#!/usr/bin/env python3
"""
Compile a single stdlib file through codegen + gcc -fgimple -fsyntax-only,
printing full gcc output. Useful for debugging a single failure reported by
compile_stdlib.py without rerunning the whole corpus.

Usage:
  python3 tools/compile_one.py test/memory/test_span.mojo [--keep]

  --keep   don't delete the generated .c tempfile; print its path
"""
import sys
import os
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from module_loader import STDLIB_PATH
from build_config import find_gcc
from build_stdlib_dylib import compile_module_to_c

_GCC = find_gcc()
_RUNTIME_INC = str(Path(__file__).resolve().parent.parent / 'runtime')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    keep = '--keep' in sys.argv

    mojo_file = os.path.join(STDLIB_PATH, path)
    src = open(mojo_file).read()
    rel = os.path.relpath(mojo_file, STDLIB_PATH)
    name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')

    c_src = compile_module_to_c(src, str(mojo_file), name)

    with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as tf:
        tf.write(c_src)
        cpath = tf.name

    if keep:
        print("C file:", cpath)

    r = subprocess.run(
        [_GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-fsyntax-only',
         '-D__MOJO_STDLIB_MODE__', '-x', 'c', cpath],
        capture_output=True, text=True, timeout=30,
    )
    print(r.stdout)
    print(r.stderr)
    print("RC:", r.returncode)
    if not keep:
        os.unlink(cpath)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
