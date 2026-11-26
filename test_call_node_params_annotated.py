"""Regression pin: lowering helpers that take a call node annotate it.

An unannotated `node` parameter that is only read as `node.args` is typed by
field-usage evidence: the single struct that has an `args` field. The compiler's
own AST nodes are excluded from that match (they are "preloaded layouts" outside
the module being compiled), so the lone survivor was `mojo.ir.instr.Ex`, and 15
helpers of the self-hosted compiler read `node->args` at an `Ex` offset from a
CallExpr: a type tag came back as the list (`mojo_list_get_int_checked`
crashed on 0x7c8777e5, the IdentExpr type id) in
`_expand_sole_spread_into_fixed_slots` on the first call it lowered.
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = {'_expand_sole_spread_into_fixed_slots', '_lower_class_attr_builtin',
         '_lower_generator_send', '_lower_generator_throw',
         '_lower_inlined_lambda_call', '_lower_strided', 'lower_typing_cast_call',
         '_lower_re_dynamic_call', '_lower_re_module_call', '_lower_struct_attr_call',
         '_struct_bind_args', '_struct_bind_or_raise', '_append_box_arg',
         '_resolve_call_args', '_literal_args'}


def main() -> int:
    bad = []
    seen = set()
    for path in sorted(glob.glob(os.path.join(HERE, 'mojo', '*', '*.py'))
                       + [os.path.join(HERE, 'gimple_codegen.py')]):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in NAMES:
                for a in node.args.args:
                    if a.arg in ('node', 'call'):
                        seen.add(node.name)
                        if a.annotation is None:
                            bad.append('%s:%d %s' % (os.path.relpath(path, HERE),
                                                     node.lineno, node.name))
    if NAMES - seen - {'_struct_bind_args'}:
        print('FAIL: expected helpers not found: %s' % sorted(NAMES - seen))
        return 1
    if bad:
        print('FAIL: unannotated call-node parameter: ' + ', '.join(bad))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
