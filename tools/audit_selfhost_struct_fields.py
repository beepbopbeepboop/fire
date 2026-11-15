#!/usr/bin/env python3
"""Audit the self-host AST-struct field map against the real source classes.

`mojo/backend_gimple/module_gen.py` hardcodes `self.struct_field_types['<Node>'] = {...}`
for this compiler's OWN AST nodes (the "self-host" struct injection). A field
present on the real class in `fire_compiler.py` but MISSING from that map is
silently dropped from the emitted C struct, its reflection
(`_mojo_getattr_<Node>`/`_mojo_setattr_<Node>`/`_mojo_fieldnames_<Node>`) and
its `_mojo_repr_<Node>` — so a compiled read of that attribute falls through
to `mojo_obj_getattr`, which returns a garbage sentinel (observed: 1). When the
field is read in the closure itself, the emitted C names a member the struct
does not have and gcc rejects the whole self-host translation unit.

Real fallout: `struct_field_types['CallExpr']` listed only `func`/`args`, so
`node.kwargs` read back 1 instead of the parsed kwarg list, and
`_resolve_overload`'s `len(kwargs)` SIGSEGV'd (mojo_list_len(0x1)) while
compiling std/collections/dict.mojo; and `Parser._lazy_import_blockers` /
`_last_bracket_variadics` / `errors` each went missing, which gcc reported as
`'Parser' has no member named ...` in the self-host closure.

The reader is the class-level ANNOTATIONS, not `@dataclass` decorators: the
rows this map needs are exactly the annotated members, and `Parser` is a plain
class whose annotations are its fields. A dataclass-only reader missed the
three `Parser` fields above, which is the one shape the tool cannot afford to
miss.

Usage:
    python3 tools/audit_selfhost_struct_fields.py [--all]

Default prints only structs with MISSING fields (and `--all` also lists
extra/typo'd map keys). `line`/`col` are reported but do not fail: they are
source-position fields an error-only struct may deliberately omit. Exits 1
when a field other than `line`/`col` is missing, so this is usable as a check;
`test_selfhost_struct_layout_map_regression.py` calls the same two readers.
"""
import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fields a source class may declare that the emitted struct deliberately omits.
# Error-message-only source positions: no generated code reads them.
OPTIONAL_FIELDS = ('line', 'col')


def annotated_fields(path: str) -> dict:
    """name -> [annotated member names] for every class in `path` that has any.

    Class-level annotations, not the `@dataclass` decorator: the map rows this
    compares against cover plain classes too (`Parser`), and their annotations
    are their emitted struct's fields exactly as a dataclass's are.
    """
    src = open(path).read()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
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


def missing_fields(fields: dict, layout: dict) -> dict:
    """name -> [fields absent from that struct's map row].

    Only names the map HAS an opinion about: a class with no row is not this
    check's subject (module_gen decides which structs it materializes).
    `line`/`col` are exempt — see OPTIONAL_FIELDS. Kept as a pure function so
    the regression test can hand it a control pair and prove it can fail.
    """
    out = {}
    for name in layout:
        if name not in fields:
            continue
        missing = [f for f in fields[name]
                   if f not in layout[name] and f not in OPTIONAL_FIELDS]
        if missing:
            out[name] = missing
    return out


def audit(repo: str = HERE) -> dict:
    """`missing_fields` over this tree's fire_compiler.py and module_gen.py."""
    fields = annotated_fields(os.path.join(repo, 'fire_compiler.py'))
    layout = struct_field_map(os.path.join(repo, 'mojo', 'backend_gimple',
                                           'module_gen.py'))
    return missing_fields(fields, layout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true',
                    help='also list structs with no missing fields / stray keys')
    args = ap.parse_args()

    fields = annotated_fields(os.path.join(HERE, 'fire_compiler.py'))
    layout = struct_field_map(os.path.join(HERE, 'mojo', 'backend_gimple',
                                           'module_gen.py'))
    missing = missing_fields(fields, layout)

    for name in sorted(layout):
        if name not in fields:
            if args.all:
                print(f'  (map only) {name}: {layout[name]}')
            continue
        absent = [f for f in fields[name] if f not in layout[name]]
        if absent:
            tag = 'MISSING' if name in missing else 'missing(lo/col)'
            print(f'{tag:16} {name}: {absent}   (map has {layout[name]})')

    if args.all:
        print('\n-- classes with no self-host struct map entry --')
        for name in sorted(fields):
            if name not in layout:
                print(f'  {name}: {fields[name]}')

    print(f'\n{len(missing)} struct(s) with fields missing from the map')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
