"""Pinning regression for bug-CODEGEN_star_kwargs_call_through_a_polymorphic_parameter_callee.
The _cpp_try_unpack_call lowering in cpp_core.py must accept a parameter-callee
(a callable-valued parameter, not a declared local) and emit the same
container-copy lowering for pure * / ** spreads; without the parameter-callee
extension the spread through the parameter is refused.
The doc was deleted with this fix (2026-10-28).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from mojo.backend_gimple import cpp_core
import mojo.middle.types as gimple_ctypes

class FakeCall:
    pass

class FakeGen:
    _cpp_declared = {}  # callee is NOT a declared local -> must use param axis
    func_param_types = {'f': gimple_ctypes._CPP_CALLABLE_CTYPE_STAR_KW}
    _cpp_kw_param_renames = {}
    def _cpp_expr(self, node):
        return node.name if hasattr(node, 'name') else str(node)

# Parameter-callee spread: f(*nums) through callable-valued param f.
e = FakeCall()
e.func = gimple_ctypes.IdentExpr(name='f')
e.args = [gimple_ctypes.UnaryOp(op='*', operand=gimple_ctypes.IdentExpr(name='nums'))]
e.kwargs = {}
e.kw = {}

gen = FakeGen()
# Need the source container declared so the copy is allowed.
gen._cpp_declared = {'nums': 'MojoList *'}

result = cpp_core._cpp_try_unpack_call(gen, e)
assert result is not None, "_cpp_try_unpack_call refused a parameter-callee spread"
assert "mojo_list_copy" in result, f"expected container-copy lowering, got {result}"
print("PINNING TEST PASS: param-callee spread lowered correctly ->", result)
