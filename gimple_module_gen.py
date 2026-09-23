"""Compatibility shim - implementation moved to `mojo.backend_gimple.module_gen`.

`import gimple_module_gen` and `from gimple_module_gen import ...` keep working.
Prefer `mojo.backend_gimple.module_gen` in new code.
"""

# Re-export implementation from mojo.backend_gimple.module_gen (self-hosted globals() is a weak stub).
from mojo.backend_gimple.module_gen import *  # noqa: F401,F403
from mojo.backend_gimple.module_gen import (
    _CPP_KEYWORD_FIELDS, _C_KEYWORDS, _C_PARAM_EXTRA_KEYWORDS, _C_RESERVED_FUNCS, _DISPATCH_TABLE_NAMES, _EXPR_DISPATCH,
    _FIXED_ARRAY_ANN_RE, _LIST_RETURNING_METHODS, _PSEUDO_DUNDER_ATTRS, _RUNTIME_FUNCS, _SELFHOST_DIR, _SELFHOST_MODGLOBAL_CACHE,
    _STMT_DISPATCH, _STR_RETURNING_METHODS, _TYPE_MAP, _UNKNOWN_FIELD_CTYPE, _UnsupportedGeneratorShape, _as_boollit_node,
    _as_dict, _as_funcdef_node, _as_int, _as_intlit_node, _as_str, _as_structdef_node,
    _async_gen_quick_eligible, _async_quick_eligible, _bracket_param_type_annotations, _bytes_subclass_new_payload_name, _c_escape, _c_field_name,
    _c_id, _class_attr_ctype, _collect_import_modules, _collect_import_modules_rec, _compute_exc_descendants, _debug_note,
    _declared_vars_body, _emit_reflection_dispatch, _extract_init_expr, _free_func_param_ctypes, _generator_quick_eligible, _ggf_dup,
    _gmi_all_stmts_nonfunc, _gmi_as_str, _gmi_collect_global_stmts, _gmi_collect_return_values, _gmi_collect_self_assigns, _gmi_collect_self_reads,
    _gmi_emit_closure_recursive, _gmi_expr_provably_str, _gmi_find_comptime_one, _gmi_global_init_code, _gmi_has_unresolved_base, _gmi_phase17_collect_appends,
    _gmi_prefold_toplevel_comptime, _gmi_scan_cpp_nested_imports, _gmi_scan_func_body_for_self_attr, _gmi_scan_import_modules, _gmi_scan_try_imports, _gmi_self_member,
    _homogeneous_tuple_ann_elem, _import_targets, _is_dispatch_name, _is_selfhost_source_dir, _merge_struct_inheritance, _module_init_name,
    _module_toplevel_name, _mojo_type, _pair_key, _ptr_slot_in_range, _register_sym, _render_struct_typedef_body,
    _safe_field, _safe_name, _seed_selfhost_module_globals, _seed_selfhost_return_elem_types, _seed_selfhost_struct_dict_field_types, _selfhost_fn_reassigns_method,
    _selfhost_homogeneous_tuple_ret_funcs, _selfhost_modglobal_is_pathcall, _selfhost_module_scalar_globals, _selfhost_struct_dict_field_val_types, _sms_key, _struct_type_id,
    _stub_guard_name, _used_idents_deep, _used_idents_node, _walk_ast
)
