# Regression test for per-module AST lifetime fix
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimple_codegen


def test_ast_released_after_module_emission():
    # After compiling with imports, AST accumulators should be cleared
    src = '''
def add(a, b):
    return a + b

x = add(1, 2)
'''
    code, gen = gimple_codegen._run_pipeline(src, do_imports=True, filename='test_reg.mojo')
    # Accumulators should be cleared to avoid retention
    assert not getattr(gen, '_module_stmts', {}), "module_stmts should be cleared"
    assert not getattr(gen, '_all_transitive_stmts_ordered', []), "transitive stmts should be cleared"
    assert 'x' in code or 'add' in code
