"""Regression pin: a parameter that carries the code generator is annotated.

The self-hosted compile lowers `p.field` on an UNANNOTATED parameter to a dynamic
getattr on a boxed word. `closures.discover_closures`'s nested
`_scan_for_closures(ctx, ...)` took the generator as a bare `ctx`, so
`ctx.var_types` raised `AttributeError: var_types` in the self-hosted compiler
on its first compile with a call. Parameters named `ctx` (the middle tier's name
for the generator) must carry `GimpleGen`.
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    bad = []
    for path in sorted(glob.glob(os.path.join(HERE, 'mojo', '*', '*.py'))):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for a in node.args.args:
                    if a.arg == 'ctx' and a.annotation is None:
                        bad.append('%s:%d %s(ctx)' % (os.path.relpath(path, HERE),
                                                      node.lineno, node.name))
    if bad:
        print('FAIL: unannotated generator parameter: ' + ', '.join(bad))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
