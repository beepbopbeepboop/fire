"""Compatibility shim — implementation moved to `mojo.middle.coro`.

`import gimple_gen_coro` and `from gimple_gen_coro import ...` keep working.
Prefer `mojo.middle.coro` in new code.
"""

# Re-export implementation from mojo.middle.coro (self-hosted globals() is a weak stub).
from mojo.middle.coro import *  # noqa: F401,F403
from mojo.middle.coro import (
    _ASYNC_METHOD_NAMES, _AW_COUNTER, _BOX_GET, _BOX_NEW, _BOX_SET, _BOX_SHIMS,
    _CALLSITE_PARAM_KINDS, _CVAR, _C_TRAMPOLINE_TMPL, _ENV, _FLOAT_ANNS, _FUNC_RET_KIND,
    _INT_ANNS, _KIND_CTYPE, _KIND_TO_SLOT_CTYPE, _LAST_YIELD_TMPL, _LOCK_CTORS, _MODE,
    _NATIVE_FUTURE_CLASSES, _NUMERIC_CTORS, _OLD_MODE, _PARAM_NAMES, _SCALARISH, _STMT_TYPES,
    _STRING_ANNS, _STRUCT_NAMES, _TASK_VARS, _ann_kind, _append_box_args, _append_cap_args,
    _apply_nested_async_capture, _argkind, _async_awaits_ok, _async_for_drive_stmts, _async_for_ok, _async_method_setup,
    _await_drive_stmts, _await_held_handle, _await_stmt_ok, _await_target_name, _c_ident, _call,
    _called_from_nested_async, _cap_rewrite_expr, _cap_rewrite_stmts, _capsrc_name, _capture_scan_body, _collect_nested_ordinary_funcs,
    _deep_copy_stmt, _detect_native_future_classes, _eligible, _eligible_async, _eligible_async_common, _eligible_async_gen,
    _exc_arg_to_shim_args, _exc_type_tag, _find_calls_to, _fn_body_calls, _fn_refs_captures, _forward_plain,
    _forward_tagged, _generator_tuple_slots, _generator_value_kind, _hidden_box_name, _hoist_nested_async, _is_async_method_call,
    _is_asyncio_run_call, _is_asyncio_sleep_call, _is_asyncio_sock_recv_call, _is_bare_self_call, _is_create_task_call, _is_future_wait_call,
    _is_lock_with, _is_not_self_done, _is_standard_await_generator, _is_struct_param, _is_task_wait_call, _lambdas_ok,
    _literal_kind, _lock_with_body_suspends, _lock_withs_ok, _looks_like_exc_class, _looks_like_stmt_list, _lower_one,
    _lower_one_async, _lower_one_async_gen, _mojo_to_c_type, _nested_async_capture_plan, _outer_all_locals, _outer_boxable_locals,
    _own_property_names, _property_call_ok, _resolve_call_args, _rewrite_async_expr, _rewrite_async_gen_stmts, _rewrite_async_stmts,
    _rewrite_asyncio_run, _rewrite_asyncio_run_stmts, _rewrite_expr, _rewrite_native_future_refs, _rewrite_stmts, _scan_callsite_param_kinds,
    _scan_task_vars, _seed_prop_names, _static_env, _strict_init_kind, _thread_box_through_siblings, _unwrap_transfer,
    _walk, _yf_counter, _yield_from_ok, _yield_kind, _yield_shim, _zlib
)
