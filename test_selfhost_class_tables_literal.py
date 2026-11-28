"""Regression pin: the class-level tables of `GimpleGen` stay literal, or the compiled compiler gets none of them.

The self-hosted class-attribute emitter (`module_gen._gmp_class_attr_globals`) fills a dict
table only when EVERY entry has a shape it can emit as C: `str: str`, or
`str: (str, [str, ...])` for the signature tables. One entry that is computed leaves the
whole dict EMPTY in the compiled compiler, with no diagnostic. That happened to
`_KNOWN_SIGS` (624 entries): `'mojo_rtobj_method_call': ('int64_t', [...] + ['int64_t'] * 8)`
emptied it, so `bin`/`hex`/`oct` and every other runtime builtin lowered with the
`int64_t` default return type and the compiled compiler's C diverged from the reference's.

Checked on the parse tree, so it needs no build: every entry of each table below is a
literal of the shape the emitter understands.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# table -> what every value must be
TABLES = {
    '_KNOWN_SIGS': 'sig',
    '_LIBC_SIGS': 'sig',
    'BUILTIN_VALUE_MAP': 'str',
}


def _is_str(n) -> bool:
    return isinstance(n, ast.Constant) and isinstance(n.value, str)


def _value_ok(kind: str, v) -> bool:
    if kind == 'str':
        return _is_str(v)
    return (isinstance(v, ast.Tuple) and len(v.elts) == 2 and _is_str(v.elts[0])
            and isinstance(v.elts[1], (ast.List, ast.Tuple))
            and all(_is_str(e) for e in v.elts[1].elts))


def main() -> int:
    tree = ast.parse(open(os.path.join(HERE, 'gimple_codegen.py')).read())
    seen = set()
    bad = []
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == 'GimpleGen'):
            continue
        for n in cls.body:
            name = getattr(n, 'target', None)
            name = getattr(name, 'id', '')
            if isinstance(n, ast.AnnAssign) and name in TABLES and isinstance(n.value, ast.Dict):
                seen.add(name)
                for k, v in zip(n.value.keys, n.value.values):
                    if k is None:
                        bad.append('%s: a ** splat at line %d' % (name, n.lineno))
                    elif not _is_str(k) or not _value_ok(TABLES[name], v):
                        bad.append('%s: line %d: %s' % (name, k.lineno, ast.unparse(v)[:70]))
    for name in TABLES:
        if name not in seen:
            bad.append('%s: table not found in class GimpleGen' % name)
    if bad:
        print('FAIL: a computed entry empties the whole table in the compiled compiler:')
        for b in bad:
            print('  ' + b)
        return 1
    print('PASS: %s are all-literal' % ', '.join(sorted(seen)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
