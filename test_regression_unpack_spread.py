"""Pinning regression for bug-CodeGEN_star_kwargs_unpack_call_argument_refused.
The _cpp_try_unpack_call lowering in cpp_core.py must emit container-copy
C++ for pure * / ** spreads through a declared variadic-family local;
without it the corpus falls through to the generic UnaryOp case (double
dereference) or raises an honest refusal incorrectly.
The doc was deleted 2026-10-26, so this test verifies the fix is still in place.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Verify the helper exists and can lower the narrow one-line repro.
from mojo.backend_gimple import cpp_core
import mojo.middle.types as gimple_ctypes

class FakeCall:
    pass

class FakeGen:
    _cpp_declared = {
        'f': gimple_ctypes._CPP_CALLABLE_CTYPE_STAR_KW,
        'nums': 'MojoList *',  # declared local for the unpack source
    }
    _cpp_kw_param_renames = {}
    def _cpp_expr(self, node):
        return node.name if hasattr(node, 'name') else str(node)

e = FakeCall()
e.func = gimple_ctypes.IdentExpr(name='f')
e.args = [gimple_ctypes.UnaryOp(op='*', operand=gimple_ctypes.IdentExpr(name='nums'))]
e.kwargs = {}
e.kw = {}

gen = FakeGen()
# The helper must not return None (must lower) for the provable shape.
result = cpp_core._cpp_try_unpack_call(gen, e)
assert result is not None, "_cpp_try_unpack_call refused a provable spread"
assert "mojo_list_copy" in result, f"expected container-copy lowering, got {result}"
print("PINNING TEST PASS: unpack spread lowered correctly ->", result)