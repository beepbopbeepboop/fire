#!/usr/bin/env python3
"""Run the REAL stdlib-compiler path on test/utils/test_variant.mojo."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_stdlib_dylib import compile_module_to_c_cached

SRC = '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/test/utils/test_variant.mojo'
path = SRC
src = open(SRC).read()
try:
    c = compile_module_to_c_cached(src, path, 'test_variant')
    print('COMPILE OK, C bytes:', len(c))
    # Private scratch directory, not a shared /tmp path: two runs must not hand
    # each other's generated C (the guard in test_formal_sweep_truth.py pins
    # this). Print where it went — the point of writing it is to read it.
    out = os.path.join(tempfile.mkdtemp(prefix="repro_variant_"),
                       'test_variant_generated.c')
    print('wrote', out)
    with open(out, 'w') as f:
        f.write(c)
except Exception as e:
    import traceback
    print(f'EXCEPTION {type(e).__name__}:')
    print(str(e)[:4000])
