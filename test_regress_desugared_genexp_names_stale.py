"""Regression for bug:CODEGEN_desugared_genexp_names_stale_import.

Before fix: fire_compiler.desugar_genexps rebound DESUGARED_GENEXP_NAMES,
so gimple_codegen's by-value import kept reading []. After fix: both see
same object.
"""
import fire_compiler as fc
import gimple_codegen as gc
from fire_compiler import Parser, py_tokenize

def test_desugared_genexp_names_shared_after_desugar():
    src = 'def f(n: int):\n    return sum(i for i in range(n))\n'
    stmts = Parser(py_tokenize(src)).parse_module()
    fc.desugar_genexps(stmts)
    # The list must be shared; gc's import must see the names.
    assert fc.DESUGARED_GENEXP_NAMES == gc.DESUGARED_GENEXP_NAMES, (
        f"stale import: fc={fc.DESUGARED_GENEXP_NAMES}, gc={gc.DESUGARED_GENEXP_NAMES}")
    assert len(fc.DESUGARED_GENEXP_NAMES) >= 1, "expected at least one hoisted genexp"
    assert fc.DESUGARED_GENEXP_NAMES is gc.DESUGARED_GENEXP_NAMES, (
        "lists should be the same object (in-place update)")

if __name__ == '__main__':
    test_desugared_genexp_names_shared_after_desugar()
    print("PASS")
