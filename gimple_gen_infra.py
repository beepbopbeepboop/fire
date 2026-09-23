"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_infra`.

`import gimple_gen_infra` and `from gimple_gen_infra import ...` keep working.
Prefer `mojo.backend_gimple.emit_infra` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_infra (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_infra import *  # noqa: F401,F403
from mojo.backend_gimple.emit_infra import (
    _FC_SEP, _OWNED_DESTROY_RUNTIME_FN, _OWNED_FREE_RUNTIME_FN, _OWNED_PUSH_RUNTIME_FN, _OWNED_STACK_KIND, _OWNED_STACK_PUSH_RUNTIME_FN,
    _POINTER_CTOR_NAMES, _addressable_to_target, _apply_fstring_spec, _as_ident_node, _as_int, _as_member_node,
    _as_set, _as_str, _block_terminates, _char_to_cstr, _closure_info_for_ident, _coerce_to_type,
    _collect_return_types, _compile_link_inline_cpp_unit, _compr_dict_loop, _compr_generator_loop, _compr_list_loop, _compr_range_loop,
    _compr_set_loop, _compute_owned_free_candidates, _declare_var, _declared_int_ctype, _dedup_variadic_externs, _dict_val_of,
    _elaborate_overload_call, _elem_of, _emit, _emit_call, _emit_imported_global_accessors, _emit_mut_local_box_allocs,
    _emit_owned_local_frees, _emit_stdlib_import_externs, _empty_ctor_ctype, _ensure_local, _eval_const_bool, _eval_const_int,
    _exc_type_id, _fstring_sub_exprs, _function_has_reachable_fallthrough, _gen_print, _infer_param_types, _infer_return_type,
    _is_exc_class_name, _is_free_eligible_function, _is_known_field, _known_field_elem_type, _known_field_nested_elem_type, _known_field_type,
    _list_repr_fn, _materialize_as_list, _maybe_lower_mlir_op, _new_bb, _new_jbp_temp, _owned_destroy_runtime_fn,
    _owned_free_runtime_fn, _owned_push_runtime_fn, _pair_key, _prepass_list_elem, _ptr_slot_in_range, _quick_container_elem,
    _record_sys_path_inserts, _reset_func, _resolve_member_expr_type, _resolve_type, _scalar_arg_is_addressable_local, _scan_container_elems,
    _seed_addressed_locals, _seed_mut_captured_local_types, _split_top_level_comma, _sprintf_one, _stringify_value, _subst_in_value,
    _to_int64, _try_lower_slice_region_eq, _type_of, _write_dest
)
