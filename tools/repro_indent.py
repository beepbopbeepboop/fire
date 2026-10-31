#!/usr/bin/env python3
"""Repro: Unexpected INDENT('') in monomorphized Coord / UnsafeUnion / Variant."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import monomorphize as mm
from elaborate import extract_struct_source
from fire_compiler import py_tokenize, Parser

STDLIB = '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std'

CASES = [
    ('utils/coord.mojo', 'Coord', {'*element_types': ["'Int'", "'Int'"]}),
    ('utils/coord.mojo', '_RegTuple', {'*element_types': ["'Int'"]}),
    ('ffi/unsafe_union.mojo', 'UnsafeUnion', {'*Ts': ["'Int32'", "'Float32'"]}),
    ('utils/variant.mojo', 'Variant', {'*Ts': ["'Int32'", "'Float32'"]}),
]

for rel, name, targs in CASES:
    path = os.path.join(STDLIB, rel)
    with open(path) as f:
        module_src = f.read()
    print(f'=== {name} from {rel}  targs={targs} ===')
    tmpl = extract_struct_source(module_src, name)
    if tmpl is None:
        print('  extract_struct_source: None')
        continue
    print(f'  template lines: {len(tmpl.splitlines())}')
    try:
        mangled, concrete = mm.monomorphize_source(tmpl, targs)
    except ValueError as e:
        print(f'  monomorphize_source ValueError: {e}')
        continue
    print(f'  mangled: {mangled}')
    print(f'  concrete lines: {len(concrete.splitlines())}')
    with open('/tmp/mono_' + name + '.mojo', 'w') as f:
        f.write(concrete)
    try:
        Parser(py_tokenize(concrete)).parse_module()
        print('  PARSE: OK')
    except SyntaxError as e:
        print(f'  PARSE FAIL: {type(e).__name__}: {e}')
        # print a window around the failing line
        ln = getattr(e, 'lineno', None)
        if ln:
            lines = concrete.splitlines(keepends=True)
            lo = max(0, ln - 6)
            for i in range(lo, min(len(lines), ln + 4)):
                mark = '>>' if i == ln - 1 else '  '
                print(f'{mark}{i+1:4d}: {lines[i]!r}')
    print()
