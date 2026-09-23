"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_methods`.

`import gimple_gen_methods` and `from gimple_gen_methods import ...` keep working.
Prefer `mojo.backend_gimple.emit_methods` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_methods (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_methods import *  # noqa: F401,F403
from mojo.backend_gimple.emit_methods import (
    _BYTES_RETURNING_METHODS, _SELFHOST_SIBLING_MODULE_PREFIXES, _STRUCT_METHODS, _as_str, _auto_invoke_bound_method_value, _coerce_to_bytes,
    _ggf, _gmm_as_str, _gmm_callexpr_node, _gmm_sms_key, _is_selfhost_sibling_alias, _lower_bound_method_call,
    _lower_bound_method_call_value, _lower_bound_method_value, _lower_builtin_bound_method_call, _lower_builtin_method_value, _lower_bytes_method, _lower_dict_method,
    _lower_file_method, _lower_list_method, _lower_maybe_bound_call, _lower_memoryview_method, _lower_method_call, _lower_pointer_method,
    _lower_set_method, _lower_str_method, _lower_struct_instance_method, _lower_struct_method_call, _lower_struct_module_call, _lower_struct_subscript_dunder,
    _repack_method_call_spread_args, _resolve_class_attr_write_target, _selfhost_sibling_member_kind, _sms_key, _struct_buffer_arg, _struct_build_value_list,
    _struct_elem_ctype, _struct_tag_unpack_result, _struct_value_codes
)
