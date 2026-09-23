"""Compatibility shim - implementation moved to `mojo.backend_gimple.cpp_core`.

`import gimple_cpp_core` and `from gimple_cpp_core import ...` keep working.
Prefer `mojo.backend_gimple.cpp_core` in new code.
"""

# Re-export implementation from mojo.backend_gimple.cpp_core (self-hosted globals() is a weak stub).
from mojo.backend_gimple.cpp_core import *  # noqa: F401,F403
from mojo.backend_gimple.cpp_core import (
    _as_str, _cfcs_scan, _cfcs_shape_of, _cls_refs_supported, _cpp_apply_fstring_spec, _cpp_as,
    _cpp_async_for_stmt, _cpp_body_str_evidence, _cpp_boxed_list_literal_expr, _cpp_build_container_from_iterable, _cpp_container_literal_init, _cpp_emit_generator_start_expr,
    _cpp_expr, _cpp_expr_static_ctype, _cpp_fn_container_shape, _cpp_for_generator_delegate, _cpp_for_stmt, _cpp_hoist_walrus_decls,
    _cpp_in_link, _cpp_list_literal_arg_expr, _cpp_next_on_generator_expr, _cpp_pad_struct_method_call_args, _cpp_percent_format, _cpp_raise_stmt,
    _cpp_receiver_ctype, _cpp_rename_ident, _cpp_rename_ident_container, _cpp_reset_unit_state, _cpp_resolve_generator_call_api, _cpp_sanitize_module_qualifier,
    _cpp_short_circuit_bool, _cpp_stmt, _cpp_string_literal_expr, _cpp_trusted_fn_return_types, _cpp_try_kwargs_forward_call, _cpp_try_stmt,
    _cpp_with_stmt, _cpp_yield_from, _cpp_yield_tuple
)
