"""Compatibility shim - implementation moved to `mojo.backend_gimple.cpp_async`.

`import gimple_cpp_async` and `from gimple_cpp_async import ...` keep working.
Prefer `mojo.backend_gimple.cpp_async` in new code.
"""

# Re-export implementation from mojo.backend_gimple.cpp_async (self-hosted globals() is a weak stub).
from mojo.backend_gimple.cpp_async import *  # noqa: F401,F403
from mojo.backend_gimple.cpp_async import (
    _HELPER_FREE_BUILTINS, _HELPER_SCALAR_CTYPES, _compile_nested_async_functions, _compute_nested_closure_captures, _cpp_compile_nested_sync_helpers, _cpp_declared_type,
    _cpp_dict_key_expr, _cpp_except_handler_body, _cpp_fresh_name, _cpp_is_callable_value_expr, _cpp_iterable_is_delegatable_generator_call, _cpp_known_ptr_struct,
    _cpp_match_stmt, _cpp_stmt_with_break_flag, _cpp_struct_ptr_local, _cpp_with_guard_type_name, _enclosing_scope_with_locals, _gen_cpp_async_generator_unit,
    _gen_cpp_async_unit, _gen_cpp_generator_unit, _hbn_add_target, _helper_bound_names, _inline_single_use_task_composition, _mutated_free_names,
    _normalize_await_kwargs, _resolve_and_start_task, _resolve_kwargs_for_known_async_call
)
