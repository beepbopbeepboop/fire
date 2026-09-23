#!/usr/bin/env python3
"""Audit the self-host AST-struct field map against the real dataclasses.

`mojo/backend_gimple/module_gen.py` hardcodes `self.struct_field_types['<Node>'] = {...}`
for this compiler's OWN AST nodes (the "self-host" struct injection). A field
present on the real dataclass in `fire_compiler.py` but MISSING from that map
is silently dropped from the emitted C struct, its reflection
(`_mojo_getattr_<Node>`/`_mojo_setattr_<Node>`/`_mojo_fieldnames_<Node>`) and
its `_mojo_repr_<Node>` — so a compiled read of that attribute falls through
to `mojo_obj_getattr`, which returns a garbage sentinel (observed: 1).

Real fallout: `struct_field_types['CallExpr']` listed only `func`/`args`, so
`node.kwargs` read back 1 instead of the parsed kwarg list, and
`_resolve_overload`'s `len(kwargs)` SIGSEGV'd (mojo_list_len(0x1)) while
compiling std/collections/dict.mojo.

Usage:
    python3 tools/audit_selfhost_struct_fields.py [--all]

Default prints only structs with MISSING fields (and `--all` also lists
extra/typo'd map keys). `line`/`col` are reported but flagged, since they may
be intentionally omitted for error-message-only use.
"""
import argparse
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dataclass_fields(path: str) -> dict:
    """name -> [field names] for every @dataclass class in `path`."""
    src = open(path).read()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        is_dc = any(
            (isinstance(d, ast.Name) and d.id == 'dataclass')
            or (isinstance(d, ast.Call)
                and isinstance(d.func, ast.Name) and d.func.id == 'dataclass')
            for d in node.decorator_list
        )
        if not is_dc:
            continue
        fields = []
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                fields.append(st.target.id)
        if fields:
            out[node.name] = fields
    return out


def struct_field_map(path: str) -> dict:
    """name -> [keys] from `self.struct_field_types['<name>'] = { ... }`."""
    src = open(path).read()
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        tgt = node.targets[0] if node.targets else None
        if not (isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Attribute)
                and tgt.value.attr == 'struct_field_types'):
            continue
        try:
            name = ast.literal_eval(tgt.slice)
        except Exception:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        keys = []
        for k in node.value.keys:
            try:
                keys.append(ast.literal_eval(k))
            except Exception:
                keys.append('<dynamic>')
        out[name] = keys
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true',
                    help='also list structs with no missing fields / stray keys')
    args = ap.parse_args()

    dcs = dataclass_fields(os.path.join(HERE, 'fire_compiler.py'))
    mp = struct_field_map(os.path.join(HERE, 'mojo', 'backend_gimple',
                                       'module_gen.py'))

    n_missing = 0
    for name in sorted(mp):
        if name not in dcs:
            if args.all:
                print(f'  (map only) {name}: {mp[name]}')
            continue
        missing = [f for f in dcs[name] if f not in mp[name]]
        # only meaningful for structs whose emitted map is a full layout
        if missing:
            n_missing += 1
            semantic = [f for f in missing if f not in ('line', 'col')]
            tag = 'MISSING' if semantic else 'missing(lo/col)'
            print(f'{tag:16} {name}: {missing}   (map has {mp[name]})')

    if args.all:
        print('\n-- dataclasses with no self-host struct map entry --')
        for name in sorted(dcs):
            if name not in mp:
                print(f'  {name}: {dcs[name]}')

    print(f'\n{n_missing} struct(s) with fields missing from the map')
    return 0


if __name__ == '__main__':
    sys.exit(main())
