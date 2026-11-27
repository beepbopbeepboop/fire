"""Regression pin: the tagged-select helpers answer "does not apply" with a value, not `None`.

`_tagged_cmp_select` returns a pair and `_tagged_arith_select` a string. On the
self-hosted path a `None` from a pair-returning function is a garbage pair that
`is not None` accepts, so `_lower_binary_tail` returned `('', '')` for every
arithmetic operator and `a + 1` lowered to no operation (`_t1 = ;`,
`return _t1`). Found with lldb on the built self-hosted binary: after
`_tagged_cmp_select` returned, the tail went straight to the return coercion.
The helpers now return `('', '')` / `''` and the callers test the first
element, which both paths read the same way.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'mojo', 'backend_gimple', 'emit_exprs.py')


def main() -> int:
    tree = ast.parse(open(SRC).read())
    bad = []
    seen = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ('_tagged_cmp_select', '_tagged_arith_select'):
            seen.add(fn.name)
            if fn.returns is None:
                bad.append(f'{fn.name}: no return annotation')
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and (
                        node.value is None
                        or (isinstance(node.value, ast.Constant) and node.value.value is None)):
                    bad.append(f'{fn.name}:{node.lineno}: returns None')
    for name in ('_tagged_cmp_select', '_tagged_arith_select'):
        if name not in seen:
            bad.append(f'{name}: not found')
    text = open(SRC).read()
    for needle in ('_tsel is not None', '_tcmp is not None'):
        if needle in text:
            bad.append(f'a caller still tests `{needle}`')
    if bad:
        print('FAIL')
        for b in bad:
            print('  ' + b)
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
