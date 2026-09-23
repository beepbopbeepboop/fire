"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_stmts`.

`import gimple_gen_stmts` and `from gimple_gen_stmts import ...` keep working.
Prefer `mojo.backend_gimple.emit_stmts` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_stmts (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_stmts import *  # noqa: F401,F403
from mojo.backend_gimple.emit_stmts import (
    _annotation_dict_nested_val_type, _annotation_dict_val_type, _apply_isinstance_narrowings, _as_str, _assign_target, _collect_isinstance_narrowings,
    _emit_dynattr_setattr_dispatch, _emit_except_handler, _emit_try_loop_exit_exc_pops, _ensure_bool_cond, _gen_stmt_AssertStmt, _gen_stmt_AssignStmt,
    _gen_stmt_AugAssignStmt, _gen_stmt_BreakStmt, _gen_stmt_ContinueStmt, _gen_stmt_DelStmt, _gen_stmt_ExprStmt, _gen_stmt_ForStmt,
    _gen_stmt_IfStmt, _gen_stmt_MatchStmt, _gen_stmt_MultiAssignStmt, _gen_stmt_PassStmt, _gen_stmt_RaiseStmt, _gen_stmt_ReturnStmt,
    _gen_stmt_TryStmt, _gen_stmt_VarDecl, _gen_stmt_WhileStmt, _gen_stmt_WithStmt, _handler_bind_name, _handler_exc_all_names,
    _handler_exc_name, _is_except_as_member_target, _is_genexp, _isinstance_narrow_struct, _iter_ast, _loop_break_bb,
    _loop_continue_bb, _maybe_narrow_genexp_local, _narrow_key_for_expr, _pair_key, _restore_isinstance_narrowings, _seed_genexp_list_narrowing,
    _track_pointer_actual_type, _try_bind_list_iter, _with_emit_exits, _with_item_alias_name
)
