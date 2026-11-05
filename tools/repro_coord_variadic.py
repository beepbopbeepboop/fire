#!/usr/bin/env python3
"""Repro + verification: variadic Coord instantiation with bracketed type args
(`ComptimeInt[5]`, `ComptimeInt[3]`, ...) failing to parse after
`monomorphize_source`'s variadic substitution.

BEFORE the fix (exact user report):
    Coord[ComptimeInt[5], Int32, ComptimeInt[3], Int64]  ->  147:71:
        Expected NAME or KW got COMMA(',')
    Coord[Int, ComptimeInt[1]]                           ->  147:53:
        Expected NAME or KW got RPAREN(')')

Run from anywhere:  python3 tools/repro_coord_variadic.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import monomorphize as mm
from elaborate import extract_struct_source
from fire_compiler import py_tokenize, Parser

STDLIB = '/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std'

# (rel, struct, targs, expect_parse_ok, tag)
CASES = [
    # the two reported failures (type args exactly as the codegen's
    # `_type_expr_to_ann` spells them — no quotes)
    ('utils/coord.mojo', 'Coord',
     {'*element_types': ['ComptimeInt[5]', 'Int32', 'ComptimeInt[3]',
                         'Int64']}),
    ('utils/coord.mojo', 'Coord',
     {'*element_types': ['Int', 'ComptimeInt[1]']}),
    # the same shapes with quoted type-arg strings (the mangled-name
    # display made it look like the args carry quotes)
    ('utils/coord.mojo', 'Coord',
     {'*element_types': ["'ComptimeInt[5]'", "'Int32'",
                         "'ComptimeInt[3]'", "'Int64'"]}),
    ('utils/coord.mojo', 'Coord',
     {'*element_types': ["'Int'", "'ComptimeInt[1]'"]}),
    # repro_indent.py's Coord baseline (previously also red at 147)
    ('utils/coord.mojo', 'Coord', {'*element_types': ["'Int'", "'Int'"]}),
    # the repro_indent.py regressions that were green and must stay green
    ('utils/coord.mojo', '_RegTuple', {'*element_types': ["'Int'"]}),
    ('ffi/unsafe_union.mojo', 'UnsafeUnion',
     {'*Ts': ["'Int32'", "'Float32'"]}),
    ('utils/variant.mojo', 'Variant',
     {'*Ts': ["'Int32'", "'Float32'"]}),
    # a multi-inner variadic in a bracket context only (no *args
    # annotation of its own) — the full join must survive
    ('utils/coord.mojo', '_RegTuple',
     {'*element_types': ["'Int32'", "'Float32'"]}),
]

failures = 0
for rel, name, targs in CASES:
    path = os.path.join(STDLIB, rel)
    with open(path) as f:
        module_src = f.read()
    print(f'=== {name}  targs={targs} ===')
    tmpl = extract_struct_source(module_src, name)
    if tmpl is None:
        print('  extract_struct_source: None')
        failures += 1
        continue
    try:
        mangled, concrete = mm.monomorphize_source(tmpl, targs)
    except ValueError as e:
        print(f'  monomorphize_source ValueError: {e}')
        failures += 1
        continue
    lines = concrete.splitlines(keepends=True)
    print(f'  mangled: {mangled[:80]}...')
    if name == 'Coord':
        # the construct on emitted line 147, and its bracket-context
        # neighbours (149: the _RegTuple constructor call, 155: the
        # Tuple[*...] parameter) — the join must land in the brackets,
        # the single type in the annotation.
        for i in (146, 148, 154):
            if i < len(lines):
                print(f'    line {i + 1}: {lines[i]!r}')
    try:
        Parser(py_tokenize(concrete)).parse_module()
        print('  PARSE: OK')
    except SyntaxError as e:
        print(f'  PARSE FAIL: {type(e).__name__}: {e}')
        failures += 1
    print()

print(f'{failures} failing case(s)' if failures else 'ALL CASES PASS')
sys.exit(1 if failures else 0)
