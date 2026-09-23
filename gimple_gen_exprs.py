"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_exprs`.

`import gimple_gen_exprs` and `from gimple_gen_exprs import ...` keep working.
Prefer `mojo.backend_gimple.emit_exprs` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_exprs (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_exprs import *  # noqa: F401,F403
from mojo.backend_gimple.emit_exprs import (
    _as_str, _boxed_propagate_container_elems, _emit_dict_pair_store, _homogeneous_literal_inner_elem, _lb_as_set, _lower_BoolLiteral,
    _lower_EllipsisLiteral, _lower_FloatLiteral, _lower_IdentExpr, _lower_IntLiteral, _lower_MemberExpr, _lower_StringLiteral,
    _lower_TernaryExpr, _lower_TstringLiteral, _lower_UnaryOp, _lower_WalrusExpr, _lower_binary, _lower_binary_set_op,
    _lower_binary_tail, _lower_bytes_percent_format, _lower_compare_chain, _lower_comprehension, _lower_dict_literal, _lower_external_call,
    _lower_floordiv, _lower_in_dispatch, _lower_in_impl, _lower_in_impl_values, _lower_in_range, _lower_list_literal,
    _lower_matmul, _lower_mlir_mem, _lower_mlir_struct, _lower_percent, _lower_percent_dict, _lower_percent_format,
    _lower_pow, _lower_set_literal, _lower_strided, _lower_tuple_literal, _sms_key
)
