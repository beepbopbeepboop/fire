#!/usr/bin/env python3
"""Reproduce the `non-trivial conversion in 'integer_cst'` failure that
`monomorphize.instantiate` hits on std/utils/index.mojo's `IndexList`.

Mirrors monomorphize.instantiate's own build() exactly: write the concrete
source to a real file, point GimpleGen._current_filename at it (several
gen_module passes are gated on it being a readable path), gen_module, then the
real gcc -fgimple -fPIC -c.

    python3 tools/repro_indexlist.py [--keep]
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import elaborate
import monomorphize as mm
from build_config import find_gcc
from fire_compiler import Parser, py_tokenize
from gimple_codegen import GimpleGen
from module_loader import STDLIB_PATH

SRC = os.path.join(STDLIB_PATH, 'std/utils/index.mojo')


def run(struct_name='IndexList', type_args=None, keep=False):
    type_args = type_args or {'size': '2', 'element_type': 'Int32'}
    src = open(SRC).read()
    tmpl = elaborate.extract_struct_source(src, struct_name)
    name, concrete = mm.monomorphize_source(tmpl, type_args)
    wd = tempfile.mkdtemp(prefix='repro_il_')
    mfile = os.path.join(wd, name + '.mojo')
    with open(mfile, 'w') as f:
        f.write(concrete)
    gen = GimpleGen(emit_entry_points=False, module_name=name, no_mangle={name})
    gen._current_filename = mfile
    c = gen.gen_module(Parser(py_tokenize(concrete)).with_filename(mfile).parse_module())
    cfile, ofile = os.path.join(wd, name + '.c'), os.path.join(wd, name + '.o')
    with open(cfile, 'w') as f:
        f.write(c)
    r = subprocess.run([find_gcc(), *mm._OBJ_FLAGS, '-c', '-o', ofile, cfile],
                       capture_output=True, text=True)
    print(f"=== {struct_name} {type_args}: rc={r.returncode}  ({wd})")
    sys.stdout.write(r.stderr)
    if keep:
        print(f"    mojo={mfile}\n    c={cfile}")
    return r


if __name__ == '__main__':
    run(keep='--keep' in sys.argv)