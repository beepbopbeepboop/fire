"""Compatibility shim - implementation moved to `mojo.middle.types`.

`import gimple_ctypes` and `from gimple_ctypes import ...` keep working.
Prefer `mojo.middle.types` in new code.
"""

# Re-export implementation from mojo.middle.types (self-hosted globals() is a weak stub).
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.types import (
    _BIN_OPS, _CMP_OPS, _COMMON_METHOD_NAMES, _CONTAINER_KIND_TYPES, _CPP_CALLABLE_CTYPE, _CPP_CALLABLE_CTYPE_1ARG,
    _CPP_KEYWORD_FIELDS, _CPP_OPAQUE_PTR_STRUCTS, _C_ID_MAP, _C_KEYWORDS, _C_MACRO_NAMES, _C_PARAM_EXTRA_KEYWORDS,
    _C_RESERVED_FUNCS, _EMPTY_CONTAINER_CTOR, _EXPR_DISPATCH, _FIXED_ARRAY_ANN_RE, _FIXED_RUNTIME_STRUCT_NAMES, _FLOAT_TYPES,
    _FNPTR_CTYPE_RE, _FORCE_RENAME_RESERVED, _GD_BIN_OPS, _GD_CMP_OPS, _GD_FLOAT, _GD_SIGNED,
    _GD_UNSIGNED, _IDENT_CHARS, _LIST_RETURNING_METHODS, _PSEUDO_DUNDER_ATTRS, _PTR_OUT_PARAM_SCALAR_ELEMS, _RUNTIME_FUNCS,
    _SCALAR_CTORS, _SCALAR_INT_TYPES, _STMT_DISPATCH, _STR_RETURNING_METHODS, _STR_WRAPPER_CTORS, _TYPE_FLOAT,
    _TYPE_MAP, _TYPE_SIGNED, _TYPE_UNSIGNED, _as_boollit_node, _as_int, _as_intlit_node,
    _as_str, _c_escape, _c_field_name, _c_id, _c_var_decl, _class_attr_ctype,
    _compute_exc_descendants, _debug_note, _declared_vars_body, _elem_type, _extract_init_expr, _fi_alias,
    _fi_name, _fromimport_names, _import_local_names, _import_targets, _join_import_member, _method_overload_id,
    _module_init_name, _module_toplevel_name, _mojo_type, _overload_hash_registry, _param_names_stripped, _param_sig_str,
    _params_have_vararg, _printf_fmt, _replace_first_ident, _result_type, _safe_field, _safe_name,
    _split_top_level_commas, _str_literal_value_is_fstring, _strip_mojo_param_modifiers, _stub_guard_name, _type_walk_cache, _unpack_target_leaf_names,
    _used_idents_node, _walk_type_expr
)
