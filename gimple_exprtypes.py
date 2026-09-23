"""Compatibility shim - implementation moved to `mojo.middle.exprtypes`.

`import gimple_exprtypes` and `from gimple_exprtypes import ...` keep working.
Prefer `mojo.middle.exprtypes` in new code.
"""

# Re-export implementation from mojo.middle.exprtypes (self-hosted globals() is a weak stub).
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.exprtypes import (
    _BRACKET_HEAD_RE, _CPP_CALLABLE_CTYPE, _CPP_CALLABLE_CTYPE_1ARG, _C_RESERVED_FUNCS, _FORCE_RENAME_RESERVED, _UnsupportedAsyncShape,
    _UnsupportedGeneratorShape, _WALK_AST_MAX_DEPTH, _WALK_FIELD_NAMES_CACHE, _async_gen_quick_eligible, _async_quick_eligible, _await_call_ctype,
    _bracket_param_type_annotations, _c_to_cpp_scalar_type, _generator_quick_eligible, _generator_tuple_yield_slot_ctypes, _generator_yield_ctype, _infer_simple_expr_ctype,
    _is_async_call_to_known_fn, _is_asyncio_sleep_call, _is_asyncio_sock_recv_call, _is_concrete_type_arg, _is_itertools_repeat2_call, _is_known_struct_ptr_ctype,
    _local_literal_ctype, _matching_bracket, _receiver_key, _split_top_level_commas, _struct_name_of, _struct_type_id,
    _trailing_default_at, _used_idents_deep, _used_idents_node, _walk_ast, _walk_ast_into, _walk_own_body,
    _yield_from_delegate_ctype
)
