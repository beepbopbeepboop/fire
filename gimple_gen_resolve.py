"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_resolve`.

`import gimple_gen_resolve` and `from gimple_gen_resolve import ...` keep working.
Prefer `mojo.backend_gimple.emit_resolve` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_resolve (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_resolve import *  # noqa: F401,F403
from mojo.backend_gimple.emit_resolve import (
    _as_assignstmt_node, _as_multiassignstmt_node, _as_ptr, _as_str, _as_vardecl_node, _call_expr,
    _cast_for_list, _cname, _collect_calls, _compile_imported_module, _compr_cstr_loop, _compr_enumerate_loop,
    _compr_str_loop, _dtrace, _elaborate_generic_call, _elaborate_generic_struct_call, _emit_generic_instantiation, _emit_label,
    _ensure_generic_struct, _eval_const_compare_op, _format_percent_spec, _gen_compr_append, _intern_string, _literal_elements_include_none,
    _locally_bound_names, _module_candidate_paths, _new_temp, _new_val, _param_safe_name, _register_closure_struct_inits,
    _register_link_imports, _register_reflected_struct, _repr_value, _safe_coerce_emit, _sce_simple_emit, _sms_key,
    _split_expr_format, _static_generic_return_ctype, _strided_data_ptr, _stub_result, _submodule_source_path, _void_call
)
