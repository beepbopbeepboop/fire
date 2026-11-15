#!/usr/bin/env python3
"""Regression: `bool(A or B)` where A and B are containers of DIFFERENT kinds
(a list on one side, a dict on the other: the compiler's own
`bool(getattr(f, 'comptime_params', None) or getattr(f, 'comptime_param_annotations',
None))`) lowers as `bool(A) or bool(B)` instead of joining the operands into one
container type and refusing the cast (`cannot coerce MojoDict * to MojoList *`),
which blocked compiling gimple_codegen.py for the self-host. Pure codegen."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_stdlib_dylib import compile_module_to_c  # noqa: E402

SRC = '''from fire_compiler import FunctionDef


def generic_names(stmts):
    out = []
    for st in (stmts or []):
        if isinstance(st, FunctionDef):
            is_generic = bool(getattr(st, 'comptime_params', None) or
                              getattr(st, 'comptime_param_annotations', None))
            if is_generic:
                out.append(st.name)
    return out
'''



def test_bool_of_or_over_a_list_and_a_dict_compiles():
    c = compile_module_to_c(SRC, os.path.join(HERE, '.tmp', 'bool_or_mixed.py'),
                            'bool_or_mixed', linkable=False)
    assert 'generic_names' in c


if __name__ == '__main__':
    test_bool_of_or_over_a_list_and_a_dict_compiles()
    print('ok test_bool_of_or_over_a_list_and_a_dict_compiles')
    print('all tests passed')
