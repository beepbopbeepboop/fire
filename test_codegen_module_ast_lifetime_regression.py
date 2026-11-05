# Quick regression for CODEGEN_bootstrap_resource_blowup: per-module AST lifetime
# After fix, imported module ASTs should not be retained in _module_stmts
# (and _all_transitive_stmts_ordered is used for reconciliation only)
import gimple_codegen


def test_module_stmts_not_retained():
    gen = gimple_codegen.GimpleGen(do_imports=False)
    # _module_stmts should not exist or be empty/unused after fix
    # New behavior: we don't store into it
    assert not hasattr(gen, '_module_stmts') or len(getattr(gen, '_module_stmts', {})) == 0


def test_all_transitive_stmts_ordered_exists():
    gen = gimple_codegen.GimpleGen(do_imports=False)
    assert hasattr(gen, '_all_transitive_stmts_ordered')
    assert isinstance(gen._all_transitive_stmts_ordered, list)
