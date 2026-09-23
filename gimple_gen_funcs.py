"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_funcs`.

`import gimple_gen_funcs` and `from gimple_gen_funcs import ...` keep working.
Prefer `mojo.backend_gimple.emit_funcs` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_funcs (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_funcs import *  # noqa: F401,F403
from mojo.backend_gimple.emit_funcs import (
    _SELFHOST_ANN_CTM, _SELFHOST_EXTRA_FIELD_CACHE, _abs_module, _as_dict, _as_funcdef_node, _as_str,
    _as_structdef_node, _collect_body_import_bindings, _dvt_consider, _dvt_val_cts, _effective_param_types, _find_generic_source,
    _find_imported_struct, _find_struct_home_module, _fixed_param_ctypes, _from_import_name_is_submodule, _func_csym, _func_mangleable,
    _func_qualifier, _gen_stmt_ComptimeForStmt, _gen_stmt_ComptimeIfStmt, _gen_stmt_ComptimeVarStmt, _gen_stmt_FromImportStmt, _gen_stmt_FunctionDef,
    _gen_stmt_GlobalStmt, _gen_stmt_ImportStmt, _gen_struct_method, _gen_toplevel, _imported_def_pts, _imported_field_ctype,
    _local_def_pts, _local_sibling_module_exports, _locally_binds_name, _materialize_imported_struct, _note_own_func_home, _note_vararg_trailing_param_types,
    _overload_suffix, _pair_key, _param_ctype, _param_struct_name, _parsed_import, _pop_import_scope,
    _push_import_scope, _register_imported_generic_structs, _register_imported_generics, _register_imported_structs, _resolve_import_module_qualifier, _resolve_reexported_closure_func,
    _resolve_sibling_param_ctype, _resolve_test_relative_module, _ris_base, _ris_collect, _scan_from_imports_flat, _selfhost_ann_ctype,
    _selfhost_extracted_fn_index, _selfhost_gen_self_param_ctype, _selfhost_gimplegen_dict_val_types, _selfhost_gimplegen_field_types, _selfhost_gimplegen_frozen_sigs, _selfhost_literal_ctype,
    _selfhost_merge_field, _selfhost_scan_gimplegen_extra_fields, _selfhost_walk_stmts_for_assign_targets, _selfhost_walk_stmts_for_self_assigns, _sgfs_fn_delegate_target, _sgfs_inferred,
    _sgfs_param_ct, _sgfs_resolve_ann, _sgfs_ret_ct, _signature_ctypes, _struct_method_csym, _struct_method_csym_static,
    _struct_method_overload_ids, _struct_method_qualifier
)
