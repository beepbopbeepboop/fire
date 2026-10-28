#!/usr/bin/env python3
"""Run the REAL stdlib-compiler path on test/utils/test_variant.mojo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_stdlib_dylib import compile_module_to_c_cached

SRC = '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/test/utils/test_variant.mojo'
path = SRC
src = open(SRC).read()
try:
    c = compile_module_to_c_cached(src, path, 'test_variant')
    print('COMPILE OK, C bytes:', len(c))
    with open('/tmp/test_variant_generated.c', 'w') as f:
        f.write(c)
except Exception as e:
    import traceback
    print(f'EXCEPTION {type(e).__name__}:')
    print(str(e)[:4000])
