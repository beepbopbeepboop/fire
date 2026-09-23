"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_calls`.

`import gimple_gen_calls` and `from gimple_gen_calls import ...` keep working.
Prefer `mojo.backend_gimple.emit_calls` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_calls (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_calls import *  # noqa: F401,F403
from mojo.backend_gimple.emit_calls import (
    _array_field_elem_ptr, _as_str, _build_call_args_for_candidate, _bytes_subclass_of, _default_expr_to_pair, _dict_subclass_defines,
    _dict_subclass_of, _emit_asyncio_run_drive, _emit_generator_start_call, _emit_struct_subscript_write, _ensure_libc_self_extern, _expand_sole_spread_into_fixed_slots,
    _future_done_callback_kind_tag, _ggc_as_str, _ident_call_name, _isinstance_one_type, _isinstance_type_name, _lower_LambdaExpr,
    _lower_async_closure_construct, _lower_builtin_all_any, _lower_builtin_dict, _lower_builtin_dir, _lower_builtin_import, _lower_builtin_isinstance,
    _lower_builtin_len, _lower_builtin_list, _lower_builtin_open, _lower_builtin_reversed, _lower_builtin_set, _lower_builtin_sorted,
    _lower_builtin_zip_n, _lower_call, _lower_closure_call, _lower_ctor_from_iterable, _lower_fnptr_call, _lower_fnptr_call_value,
    _lower_future_done_callback, _lower_generator_next, _lower_imported_struct_ctor, _lower_named_call, _lower_next_list_iter, _lower_next_over_comprehension,
    _lower_opaque_ctor, _lower_outer_closure_call, _lower_pointer_alloc, _lower_pointer_ctor, _lower_recursive_self_call, _lower_scalar_ctor,
    _lower_self_ctor, _lower_slice, _lower_slice_bounds, _lower_struct_constructor, _lower_subscript, _lower_varargs_pack,
    _pack_kwargs_dict, _pack_vararg_trailing_params, _resolve_overload, _sms_key, _struct_data_field, _struct_defines_method
)
