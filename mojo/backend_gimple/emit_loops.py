# Moved from gimple_gen_loops.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""For-loop family lowering for the GIMPLE backend.

Function-extraction architecture: former GimpleGen methods as module-level
functions taking `gen` first; delegates remain on the class; cross-module
references are qualified (single-emission closure rule).
"""
from __future__ import annotations

import os
import re

from fire_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, NonlocalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    _as_str, _pair_key,
)
import regex_compile
import mlir
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import mojo.middle.itcursor as itc
import gimple_codegen
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc

# Re-export shared helpers from mojo.middle.loops_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.loops_shared import *  # noqa: F401,F403
from mojo.middle.loops_shared import (
    _as_str, _gfl_declare_target_name, _pair_key, _try_const_fold_int, _tuple_elem_value, _tuple_unpack_slot_elems,
    _emit_starred_slot_from_value, _emit_starred_slot_list, starred_slot_index, starred_slot_name,
)
from mojo.backend_gimple.emit_infra import _gmi_slot_kind_long

def _gen_for_range(gen, node: gimple_ctypes.ForStmt):
    args = node.iterable.args
    var  = node.target

    if isinstance(var, str) and var.startswith('('):
        gen._gen_for_iter(node)
        return

    dynamic_step = False
    if len(args) == 1:
        start_expr, stop_expr, step_expr = gimple_ctypes.IntLiteral(0), args[0], gimple_ctypes.IntLiteral(1)
        cond_op = '<'
    elif len(args) == 2:
        start_expr, stop_expr, step_expr = args[0], args[1], gimple_ctypes.IntLiteral(1)
        cond_op = '<'
    elif len(args) == 3:
        start_expr, stop_expr, step_expr = args[0], args[1], args[2]
        if isinstance(step_expr, gimple_ctypes.IntLiteral) and step_expr.value < 0:
            cond_op = '>'
        elif (isinstance(step_expr, gimple_ctypes.UnaryOp) and step_expr.op == '-' and
              isinstance(step_expr.operand, gimple_ctypes.IntLiteral)):
            cond_op = '>'
        elif isinstance(step_expr, gimple_ctypes.IntLiteral):
            cond_op = '<'
        else:
            cond_op = '<'; dynamic_step = True
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        return

    gen._declare_var(var, 'int64_t')
    start_t, start_v = gen.lower_expr(start_expr)
    stop_t, stop_v  = gen.lower_expr(stop_expr)
    step_t, step_v  = gen.lower_expr(step_expr)
    # A DEDICATED internal counter, never the user-visible loop variable
    # `var` itself, drives this loop's own condition/increment — real
    # Mojo/Python's own idiom `for _ in range(...): for _ in range(...):
    # ...` (test_locks.mojo's exact shape, and the far more common
    # "don't care" convention generally) reuses the SAME name `_` at
    # every nesting depth, and `self._declare_var`/`self.var_types` are
    # NAME-keyed -- using `var` itself as BOTH the loop's control state
    # AND the user-visible per-iteration value meant an inner loop
    # sharing the outer loop's variable name silently clobbered the
    # OUTER loop's OWN iteration state (a real, hand-verified bug: `for
    # _ in range(0, 100): for _ in range(0, 100): calls += 1` printed
    # `100`, not `10000` -- the inner loop's `_ = 0` reset, then final
    # `_ = 100`, corrupted the outer loop's condition check on its next
    # test, terminating it after one outer iteration). A fresh internal
    # temp (never reused across nesting depths, `_new_temp` always
    # allocates a new name) decouples loop CONTROL from the user
    # variable entirely -- `var` is simply assigned the counter's
    # current value once per iteration, at the top of the body, for
    # the body's own reads to see, exactly matching real Python/Mojo
    # semantics (reassigning the loop variable inside the body never
    # affects the loop's own iteration count).
    ctr = gen._new_temp('int64_t')
    # Coerce start/stop/step to int64_t — GIMPLE requires same types in binary ops
    gen._safe_coerce_emit(start_t, 'int64_t', start_v, ctr)
    if stop_t != 'int64_t':
        stop_tmp = gen._new_temp('int64_t')
        gen._safe_coerce_emit(stop_t, 'int64_t', stop_v, stop_tmp)
        stop_v = stop_tmp
    if step_t != 'int64_t':
        step_tmp = gen._new_temp('int64_t')
        gen._safe_coerce_emit(step_t, 'int64_t', step_v, step_tmp)
        step_v = step_tmp

    bb_cond  = gen._new_bb()
    bb_body  = gen._new_bb()
    bb_post  = gen._new_bb()
    bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")

    gen._emit_label(bb_cond)
    if dynamic_step:
        t_lt   = gen._new_temp('_Bool')
        t_gt   = gen._new_temp('_Bool')
        t_spos = gen._new_temp('_Bool')
        cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {t_lt}   = {ctr} < {stop_v};")
        gen._emit(f"  {t_gt}   = {ctr} > {stop_v};")
        t_zero = gen._new_val('int64_t', "(int64_t)0")
        gen._emit(f"  {t_spos} = {step_v} > {t_zero};")
        gen._emit(f"  {cond_t} = {t_spos} ? {t_lt} : {t_gt};")
    else:
        cond_t = gen._new_val('_Bool', f"{ctr} {cond_op} {stop_v}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    # If `var` is a heap-boxed mutable capture (a nested closure captures
    # it by reference AND reassigns it), `_write_dest` returns the
    # dereferenced box (`*var`); a direct `var = ctr` would otherwise
    # overwrite the box pointer itself and leave the closure reading a
    # different variable — real bug found via test_locks.mojo's
    # `for _ in range(...)` where `inc()` does `_ = counter.fetch_add(1)`
    # (a nested async closure mutating a same-named outer loop variable).
    if var in gen._boxed_mut_locals:
        _loop_var_ctype = gen._boxed_mut_locals[var]
    else:
        _loop_var_ctype = gen.var_types.get(var, 'int64_t')
    if '*' in _loop_var_ctype:
        # The loop variable is already declared with a POINTER type by an
        # unrelated earlier statement — the `_ = run(...)` / `for _ in
        # range(...)` name-reuse pattern (`_` is the conventional
        # throwaway). The int64_t counter simply cannot be stored there,
        # and under GCC 15's C23 default `-Wint-conversion` is a hard
        # ERROR, so a raw store ("assignment to 'char *' from 'int64_t'")
        # aborts the compile (test_file.mojo's test_file_open_fifo). The
        # value is a genuine discard in this reuse case — skip the store
        # rather than emit a garbage pointer cast.
        pass
    else:
        gen._safe_coerce_emit('int64_t', _loop_var_ctype, ctr, gen._write_dest(var))
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")

    gen._emit_label(bb_post)
    step_t = gen._new_val('int64_t', f"{ctr} + {step_v}")
    gen._emit(f"  {ctr} = {step_t};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _get_actual_type(gen, ctype: str, val: str) -> str:
    """Get actual type, checking _actual_types for int64_t-stored pointers."""
    if ctype == 'int64_t' and val in gen._actual_types:
        return gen._actual_types[val]
    if val in gen.var_types and gen.var_types[val] == 'int64_t' and val in gen._actual_types:
        return gen._actual_types[val]
    return ctype




def _emit_unsupported_iter(gen, it_type: str, node=None) -> None:
    """Abort at runtime instead of silently running a for-loop body zero
    times — see mojo_unsupported_iter in runtime/fire_runtime.c.

    Includes the source file:line of the offending `for` loop (when the
    caller has it) — the runtime warning alone gives no way to tell
    which of the (possibly many) unsupported loops in a build actually
    fired without attaching a debugger, which isn't reliably possible
    in every environment this runs in."""
    loc = ''
    if node is not None and getattr(node, 'line', 0):
        fname = gen._current_filename or '<unknown>'
        loc = f'{fname}:{node.line}: '
    name_lit = gen._intern_string((loc + it_type).replace('"', '\\"'))
    # GIMPLE: a call argument must be a local register value, not a raw
    # global/static string-literal reference — load it into a temp first
    # (same requirement _call_expr/_ensure_local handle elsewhere).
    name_local = gen._new_val('char *', f'{name_lit}')
    gen._emit(f'  mojo_unsupported_iter ({name_local});')




def _try_const_fold_str(gen, expr) -> str | None:
    """Evaluate a compile-time-constant string expression (literal,
    concatenation, or repetition of foldable pieces, or a reference to
    an already-folded local — see _const_str_locals, populated as a
    side effect of ordinary AssignStmt/VarDecl lowering in program
    order) without running the program. Needed for re.sub(pattern,
    callback, src) call sites whose pattern isn't a bare string literal
    but is still fully known ahead of time, e.g. fire_compiler.py's own
    `_dq = '"' * 3; pattern = r'...' + _dq + r'...' + _dq` in
    replace_multiline_strings — that pattern needs this codegen's real
    regex engine (see _gen_for_regex_iter/regex_compile.py), not
    mojo_re_sub_fn's POSIX regcomp/regexec backend, which can't express
    \\s/\\S or non-greedy *? at all and silently no-ops on failure."""
    if isinstance(expr, gimple_ctypes.StringLiteral):
        return expr.value
    if isinstance(expr, gimple_ctypes.IdentExpr):
        return gen._const_str_locals.get(_pair_key(gen.current_func_name, expr.name))
    if isinstance(expr, gimple_ctypes.BinaryOp) and expr.op == '+':
        lv = gen._try_const_fold_str(expr.left)
        rv = gen._try_const_fold_str(expr.right)
        if lv is not None and rv is not None:
            return lv + rv
        return None
    if isinstance(expr, gimple_ctypes.BinaryOp) and expr.op == '*':
        sv = gen._try_const_fold_str(expr.left)
        iv = gen._try_const_fold_int(expr.right)
        if sv is None or iv is None:
            sv2 = gen._try_const_fold_str(expr.right)
            iv2 = gen._try_const_fold_int(expr.left)
            if sv2 is not None and iv2 is not None:
                return sv2 * iv2
            return None
        return sv * iv
    return None


def _re_sub_repl_is_callback(gen, cb_arg) -> bool:
    """True if re.sub()'s second argument is a real callable reference
    (a closure, or a bare top-level function name used as a callback);
    False if it's a plain replacement-STRING expression — the far more
    common `re.sub(pattern, repl_str, src)` form (e.g.
    `re.sub(r'[^A-Za-z0-9_]', '_', s)`, `re.sub(pat, str(concrete), src)`).
    Both real Python re.sub call shapes were previously treated as the
    callback form unconditionally: a plain replacement string got cast
    straight to a function pointer and then *called*, a SIGILL calling
    the string's own bytes as machine code (found via monomorphize.py's
    own `safe_suffix`/`monomorphize_source`). In this restricted codegen
    the only way to reference "a function" is by its bare, undeclared
    name — a closure (tracked in `_closure_envs`) or a plain top-level
    `def` name — so a bare identifier that's already a known local/
    global *variable* can't be one; that's the tell used below."""
    if not isinstance(cb_arg, gimple_ctypes.IdentExpr):
        return False
    if cb_arg.name in gen._closure_envs:
        return True
    if cb_arg.name in gen.var_types or cb_arg.name in gen._global_var_types:
        return False
    return True


def _lower_re_sub_callback(gen, cb_arg) -> tuple[str, str]:
    """Resolve a re.sub(pattern, CALLBACK, src) callback argument to a
    (fn_ptr_temp, env_temp) pair of void* values, shared by both the
    POSIX-backed mojo_re_sub_fn path and the regex-engine-backed
    mojo_regex_sub_fn path (identical callback ABI: char *(*)(void *, char *))."""
    if isinstance(cb_arg, gimple_ctypes.IdentExpr) and cb_arg.name in gen._closure_envs:
        # _closure_envs maps inner_name → env_var (NOT lifted_name)
        # Get the actual lifted function name from _all_closures
        _outer_cls = getattr(gen, '_all_closures', {}).get(gen.current_func_name, {})
        _ci_cb = _outer_cls.get(cb_arg.name)
        lifted_name = _ci_cb.lifted_name if _ci_cb else cb_arg.name
        env_var = gen._closure_envs.get(cb_arg.name, '') or '0'
        # GIMPLE: &func_name is not allowed; the callback param is void*,
        # so we store the env and use a static C non-GIMPLE pointer to
        # the function (valid from file scope) instead.
        fn_ptr_t = gen._new_temp('void *')
        static_name = f"_mojo_cb_{lifted_name}"
        gen._cb_statics[static_name] = lifted_name
        gen._emit(f'  {fn_ptr_t} = {static_name};')
        env_t = gen._new_temp('void *')
        if env_var != '0':
            gen._emit(f'  {env_t} = (void *){env_var};')
        else:
            gen._emit(f'  {env_t} = (void *)0;')
        return fn_ptr_t, env_t
    # Fallback: treat callback as a simple function pointer
    cb_type, cb_val = gen.lower_expr(cb_arg)
    fn_ptr_t = gen._new_val('void *', f'(void *){cb_val}')
    env_t = gen._new_val('void *', '(void *)0')
    return fn_ptr_t, env_t


def _gen_for_regex_iter(gen, node: gimple_ctypes.ForStmt, pattern: str) -> None:
    """`for m in <pattern>.finditer(text): ... m.lastgroup/.group()/.start() ...`
    — lowered to a real scan loop over the small regex engine in
    runtime/fire_runtime.c, instead of _gen_for_iter's generic
    unsupported-iterable fallback. See regex_compile.py and
    BACKLOG-CODEGEN.md §4f. Only .lastgroup/.group()/.start() on the
    loop variable are supported (that's everything py_tokenize's own
    `for m in _TOKEN_RE.finditer(...)` uses); .group(n) with an
    argument, .span(), etc. are not implemented — a not-yet-covered
    accessor on the match var simply won't be recognized by
    _lower_MemberExpr/_lower_method_call's regex-match-var checks and
    falls through to their normal (unrelated) handling, which is safe
    but likely wrong; this lowering does not try to detect that ahead
    of time.
    """
    var = node.target
    # NOTE: `node.target` is ALWAYS a plain Python str (see
    # _parse_unpack_target in fire_compiler.py) — the old
    # `if isinstance(node.target, str) else node.target.name` split
    # existed only because the field is typed `object`/boxed int64_t in
    # struct_field_types, so in the COMPILED binary the isinstance fell
    # to the always-false mojo_isinstance stub and `node.target.name`
    # wrongly dispatched on the raw string bytes (a hard segfault).
    # The parser contract guarantees the string form, so use it directly.
    text_type, text_val = gen.lower_expr(node.iterable.args[0])
    if text_type != 'char *':
        text_val = gen._new_val('char *', f'(char *){gen._ensure_local(text_type, text_val)}')

    if pattern not in gen._regex_progs:
        prog_id = f"re{len(gen._regex_progs)}"
        gen._regex_progs[pattern] = gimple_ctypes.regex_compile.compile_pattern(pattern, prog_id)
    info = gen._regex_progs[pattern]
    ngroups = info['ngroups']

    prog_local = gen._new_val('const ReNode *', info['prog_var'])
    ranges_local = gen._new_val('const ReRange *', info['ranges_var'])
    classinfo_local = gen._new_val('const ReClassInfo *', info['classinfo_var'])
    names_local = gen._new_val('const char * *', info['names_var'])

    text_len = gen._call_expr('int64_t', 'mojo_strlen', [('char *', text_val)])
    pos_var = gen._new_temp('int64_t')
    gen._emit(f'  {pos_var} = (int64_t)0;')
    gsize = gen._new_val('int64_t', f'(int64_t)(sizeof(int64_t) * {ngroups + 1})')
    gstart_vp = gen._new_val('void *', f'malloc ({gsize})')
    gstart_var = gen._new_val('int64_t *', f'(int64_t *){gstart_vp}')
    gend_vp = gen._new_val('void *', f'malloc ({gsize})')
    gend_var = gen._new_val('int64_t *', f'(int64_t *){gend_vp}')
    mstart_var = gen._new_temp('int64_t')
    mend_var = gen._new_temp('int64_t')
    ok_var = gen._new_temp('int')

    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f'  goto {bb_cond};')
    gen._emit_label(bb_cond)
    gen._emit(f'  {ok_var} = mojo_regex_search ({prog_local}, {ranges_local}, {classinfo_local}, '
               f'{info["root"]}, {ngroups}, {text_val}, {text_len}, {pos_var}, '
               f'&{mstart_var}, &{mend_var}, {gstart_var}, {gend_var});')
    gen._emit(f'  if ({ok_var}) goto {bb_body}; else goto {bb_after};')
    gen._emit_label(bb_body, f'count(guessed_local({10 ** (gen._loop_depth + 1)}))')

    gen._declare_var(var, 'int64_t')  # `m` itself is never read directly, only via .lastgroup/.group()/.start()
    gen._regex_match_vars[var] = {
        'names_var': names_local, 'ngroups': ngroups, 'text_val': text_val,
        'mstart_var': mstart_var, 'mend_var': mend_var, 'gstart_var': gstart_var,
    }
    gen._loop_depth += 1
    # `continue`'s target must be bb_post (which does the pos advance),
    # NOT bb_cond directly — mirroring _gen_for_list's own bb_cond/bb_post
    # split. Pointing continue straight at bb_cond (my first attempt)
    # skipped the advance entirely: mojo_regex_search got called again
    # with the exact same pos, matching the exact same token forever —
    # a real infinite loop, hit immediately by py_tokenize's own
    # `if kind in ("WS", "UNK", "XFER"): continue`.
    gen.loop_stack.append((bb_post, bb_after))
    try:
        gen._gen_loop_body(node.body)
    finally:
        gen.loop_stack.pop()
        gen._loop_depth -= 1
        del gen._regex_match_vars[var]

    if not gen._last_was_terminal:
        gen._emit(f'  goto {bb_post};')
    gen._emit_label(bb_post)
    # pos = (mend > pos) ? mend : pos + 1 — advance past the match, or by
    # one char on a zero-width match, exactly like Python's finditer.
    pos_plus1 = gen._inc_val(pos_var)
    cmp_t = gen._new_val('_Bool', f'{mend_var} > {pos_var}')
    next_pos = gen._new_val('int64_t', f'{cmp_t} ? {mend_var} : {pos_plus1}')
    gen._emit(f'  {pos_var} = {next_pos};')
    gen._emit(f'  goto {bb_cond};')
    gen._emit_label(bb_after)


def _regex_prog_for(gen, pattern: str) -> dict:
    """Compile `pattern` into the emitted regex-program tables, reusing the
    one already built for that exact pattern text. Shared by the finditer
    and findall lowerings so `for m in P.finditer(s)` and
    `for w in P.findall(s)` over the same pattern cost one program."""
    if pattern not in gen._regex_progs:
        prog_id = f"re{len(gen._regex_progs)}"
        gen._regex_progs[pattern] = gimple_ctypes.regex_compile.compile_pattern(pattern, prog_id)
    return gen._regex_progs[pattern]


def _emit_regex_scan(gen, pattern: str, text_val: str) -> tuple:
    """Emit the shared `mojo_regex_search` scan loop and yield the pieces a
    consumer needs to act on each match.

    Returns the 10-tuple
    `(info, bb_cond, bb_body, bb_post, bb_after, pos, mstart, mend, gstart,
    gend)`. The loop is left OPEN at `bb_body`: the caller emits whatever it
    does per match, then calls `_close_regex_scan`, which emits the cursor
    advance (`pos = max(mend, pos + 1)`, mirroring real Python's
    finditer/findall zero-width handling) and closes the loop.

    `pos`, `mstart` and `mend` are the three scalar C temps a consumer needs
    by name; `gstart`/`gend` are the `int64_t *` group-offset arrays, and
    `gstart[0]`/`gend[0]` are the WHOLE match — capturing group k (1-based,
    as `re` numbers them) is at index k.

    `continue` inside a consumer body is therefore correct for free — its
    target is `bb_post`, which is where the advance lives."""
    info = _regex_prog_for(gen, pattern)
    ngroups = info['ngroups']
    prog_local = gen._new_val('const ReNode *', info['prog_var'])
    ranges_local = gen._new_val('const ReRange *', info['ranges_var'])
    classinfo_local = gen._new_val('const ReClassInfo *', info['classinfo_var'])

    text_len = gen._call_expr('int64_t', 'mojo_strlen', [('char *', text_val)])
    pos_var = gen._new_temp('int64_t')
    gen._emit(f'  {pos_var} = (int64_t)0;')
    gsize = gen._new_val('int64_t', f'(int64_t)(sizeof(int64_t) * {ngroups + 1})')
    gstart_vp = gen._new_val('void *', f'malloc ({gsize})')
    gstart_var = gen._new_val('int64_t *', f'(int64_t *){gstart_vp}')
    gend_vp = gen._new_val('void *', f'malloc ({gsize})')
    gend_var = gen._new_val('int64_t *', f'(int64_t *){gend_vp}')
    mstart_var = gen._new_temp('int64_t')
    mend_var = gen._new_temp('int64_t')
    ok_var = gen._new_temp('int')

    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f'  goto {bb_cond};')
    gen._emit_label(bb_cond)
    gen._emit(f'  {ok_var} = mojo_regex_search ({prog_local}, {ranges_local}, {classinfo_local}, '
              f'{info["root"]}, {ngroups}, {text_val}, {text_len}, {pos_var}, '
              f'&{mstart_var}, &{mend_var}, {gstart_var}, {gend_var});')
    gen._emit(f'  if ({ok_var}) goto {bb_body}; else goto {bb_after};')
    gen._emit_label(bb_body, f'count(guessed_local({10 ** (gen._loop_depth + 1)}))')
    gen.loop_stack.append((bb_post, bb_after))
    return (info, bb_cond, bb_body, bb_post, bb_after, pos_var,
            mstart_var, mend_var, gstart_var, gend_var)


def _close_regex_scan(gen, pieces) -> None:
    """Close a scan loop opened by `_emit_regex_scan` (see its docstring)."""
    (_info, bb_cond, _bb_body, bb_post, bb_after,
     pos, _mstart, mend, _gstart, _gend) = pieces
    gen.loop_stack.pop()
    if not gen._last_was_terminal:
        gen._emit(f'  goto {bb_post};')
    gen._emit_label(bb_post)
    # pos = (mend > pos) ? mend : pos + 1 — advance past the match, or by
    # one char on a zero-width match, exactly like Python's finditer/findall.
    pos_plus1 = gen._inc_val(pos)
    cmp_t = gen._new_val('_Bool', f'{mend} > {pos}')
    next_pos = gen._new_val('int64_t', f'{cmp_t} ? {mend} : {pos_plus1}')
    gen._emit(f'  {pos} = {next_pos};')
    gen._emit(f'  goto {bb_cond};')
    gen._emit_label(bb_after)


def _gen_for_findall_loop(gen, node: gimple_ctypes.ForStmt) -> None:
    """`for x in <findall>(text): ...` — lower the CALL to a real
    `MojoList *` and iterate that, instead of refusing the loop.

    `findall` had NO lowering of any kind before this, which made it one of
    the named offenders in FORMAL.md §11.2: the call fell through to
    `BUILTIN_VALUE_MAP`'s `void *` identity stub, `_gen_for_iter` received
    an untyped handle, and the loop body ran ZERO times with nothing beyond
    a `mojo_unsupported_iter` naming `void *`. Two of this compiler's own
    loops have that shape (module_loader.py's re-export scan), and the
    dedup pass in emit_infra.py had to be written to avoid the form
    altogether — its own docstring records that `finditer`/`findall` "has no
    lowering for either shape of for-loop ... so a loop here over either
    would silently run zero times once this file compiles itself".

    What is emitted is exactly what `re.findall` computes: a scan over the
    subject with the same engine `finditer` already uses, appending one
    element per match.

      * no capture groups  -> each element is the whole matched text, a
        fresh `char *` from `mojo_regex_substr` (which copies, so the list
        owns its strings and no two elements alias the subject).
      * exactly one group -> each element is that group's text, matching
        real Python, which does NOT wrap a single group in a tuple.
      * two or more       -> each element is a TUPLE of the groups, which
        in this backend is a `MojoList *` marked by `mojo_mark_as_tuple`
        (the representation `_lower_tuple_literal` produces), so a
        consuming `for a, b in ...` unpacks it through the ordinary
        two-slot path.

    The pattern must be known at compile time, because the scan is driven
    by the emitted regex-program tables rather than by a runtime `re`
    object — the same constraint `finditer` already has, and the same one
    that makes an unlowerable pattern a refusal rather than a guess.
    `_try_const_fold_str` supplies it from a literal, a concatenation, a
    repetition, or a reference to an already-folded local.

    FLAGS are refused rather than ignored. `_re_py.MULTILINE` and friends
    change what `^`/`$`/`.` mean, and this backend's engine has no flag
    input; silently dropping one would be precisely the silent wrong answer
    this whole class is about. So both a `flags=` keyword and a third
    POSITIONAL argument are refused — the latter because that is exactly
    how the flags are spelled at the two real call sites
    (module_loader.py passes `_re_py.MULTILINE` third).

    Any shape not provably supported raises, and the caller rolls back and
    leaves the loud refusal in place."""
    it = node.iterable
    if not isinstance(it, gimple_ctypes.CallExpr):
        raise ValueError('findall() call expected')
    if len(it.kwargs or []) > 0:
        raise ValueError('findall() keyword arguments (incl. flags=) are not lowered')
    if len(it.args) != 2:
        raise ValueError(
            f'findall() with {len(it.args)} positional arguments is not lowered '
            f'(a third argument is a flags argument)')
    pattern = gen._try_const_fold_str(it.args[0])
    if pattern is None:
        raise ValueError('findall() pattern is not a compile-time-known string')

    text_type, text_val = gen.lower_expr(it.args[1])
    if text_type != 'char *':
        text_val = gen._new_val(
            'char *', f'(char *){gen._ensure_local(text_type, text_val)}')

    ngroups = _regex_prog_for(gen, pattern)['ngroups']
    res = gen._call_expr('MojoList *', 'mojo_list_new', [])
    pieces = _emit_regex_scan(gen, pattern, text_val)
    (_info, _bb_cond, _bb_body, _bb_post, _bb_after,
     _pos, mstart, mend, gstart, gend) = pieces
    if ngroups == 0:
        _whole = gen._call_expr(
            'char *', 'mojo_regex_substr',
            [('char *', text_val), ('int64_t', mstart), ('int64_t', mend)])
        gen._void_call('mojo_list_append_str', [('MojoList *', res), ('char *', _whole)])
        gen._elem_types[res] = 'char *'
    else:
        # `gstart`/`gend` are `int64_t[ngroups + 1]` as filled by
        # `mojo_regex_search`, and index 0 is the WHOLE match — capturing
        # group k (1-based, as `re` numbers them) is at index k. So group
        # `_gi` (0-based here) is at `_gi + 1`. Read each through
        # `_mojo_at_int64_t` — the shared `p + n` helper every other
        # pointer-arithmetic READ in this backend uses — rather than
        # writing `*p + n` inline, which GIMPLE rejects (and which
        # silently read 0 where it did not, producing empty group strings
        # rather than a compile error).
        gen._ptr_helpers_needed.add('int64_t')
        # TWO OR MORE GROUPS: ONE tuple per match, holding every group as a
        # slot. (Building the tuple inside the per-group loop instead
        # appends N one-slot tuples per match, which a consuming
        # `for a, b in ...` then unpacks as N pairs of (group, null) —
        # twice the iterations and a null second slot.)
        _tup = gen._call_expr('MojoList *', 'mojo_list_new', []) if ngroups >= 2 else None
        for _gi in range(ngroups):
            _gi64 = gen._new_val('int64_t', f'(int64_t){_gi + 1}')
            _gsp = gen._new_val('int64_t *', f'_mojo_at_int64_t ({gstart}, {_gi64})')
            _gep = gen._new_val('int64_t *', f'_mojo_at_int64_t ({gend}, {_gi64})')
            _gsv = gen._new_temp('int64_t')
            _gev = gen._new_temp('int64_t')
            gen._emit(f'  {_gsv} = *{_gsp};')
            gen._emit(f'  {_gev} = *{_gep};')
            # A group that did not participate in this match has gstart
            # -1 (the engine initialises every slot to -1 before
            # matching); real `re.findall` yields an empty string for an
            # unmatched optional group, and `mojo_regex_substr` already
            # clamps a negative length to 0 — but it would read from
            # `text - 1` first, so clamp the offsets here.
            _zero = gen._new_val('int64_t', '(int64_t)0')
            _gsz = gen._new_val('int64_t', f'{_gsv} < {_zero} ? {_zero} : {_gsv}')
            _gez = gen._new_val('int64_t', f'{_gev} < {_zero} ? {_zero} : {_gev}')
            _s = gen._call_expr(
                'char *', 'mojo_regex_substr',
                [('char *', text_val), ('int64_t', _gsz), ('int64_t', _gez)])
            if _tup is None:
                gen._void_call('mojo_list_append_str', [('MojoList *', res), ('char *', _s)])
                gen._elem_types[res] = 'char *'
            else:
                gen._void_call('mojo_list_append_str', [('MojoList *', _tup), ('char *', _s)])
        if _tup is not None:
            # A nested list is appended as its boxed handle — the runtime
            # has no `mojo_list_append(MojoList *, MojoList *)` and every
            # other nested-list append in this backend boxes the pointer
            # the same way.
            _boxed = gen._new_val('int64_t', f'(int64_t)(intptr_t){_tup}')
            gen._void_call('mojo_list_append_int', [('MojoList *', res), ('int64_t', _boxed)])
            # Marked AFTER the group slots are appended, not before: a
            # marked list is refused by every mutating MojoList entry
            # point (mojo_require_mutable_list's own comment), so marking
            # first made `re.findall` with 2+ groups raise out of its own
            # construction. Same ordering rule as _lower_tuple_literal.
            gen._void_call('mojo_mark_as_tuple', [('MojoList *', _tup)])
    _close_regex_scan(gen, pieces)
    if ngroups >= 2:
        gen._elem_types[res] = 'MojoList *'
        gen._tuple_slot_types[res] = ['char *'] * ngroups

    # `re.findall` returns a real list, and the consuming `for` loop must
    # iterate THAT list. Give the result a declared name (with its element
    # metadata carried across) and hand it to `_gen_for_list`, which is
    # the ordinary list-loop path — rather than duplicating the loop
    # emission here.
    _tmp = gen._new_temp('MojoList *')
    gen._safe_coerce_emit('MojoList *', 'MojoList *', res, _tmp)
    if ngroups == 0 or ngroups == 1:
        gen._elem_types[_tmp] = 'char *'
    else:
        gen._elem_types[_tmp] = 'MojoList *'
        gen._tuple_slot_types[_tmp] = ['char *'] * ngroups
    gen._gen_for_list(node.target, _tmp, node.body)


def _int_dict_loop_source(gen, it) -> tuple:
    """`(mode, receiver)` for a `for` iterable that walks a provably
    Dict[Int, V] name (gen._int_keyed_dicts): mode 'keys' for `d` / `d.keys()`
    and 'items' for `d.items()`, receiver being the bare name `d`. `('', None)`
    for everything else, which keeps the string keys the runtime has always
    produced. Decided from the loop statement alone (never from a side table
    keyed by value names) so no other consumer of a dict's keys can be handed
    an integer where it expects a string."""
    if isinstance(it, gimple_ctypes.IdentExpr):
        return ('keys', it) if it.name in gen._int_keyed_dicts else ('', None)
    if (isinstance(it, gimple_ctypes.CallExpr) and not it.args
            and isinstance(it.func, gimple_ctypes.MemberExpr)
            and it.func.member in ('keys', 'items')
            and isinstance(it.func.obj, gimple_ctypes.IdentExpr)
            and it.func.obj.name in gen._int_keyed_dicts):
        return it.func.member, it.func.obj
    return '', None


def _lower_int_dict_items(gen, recv) -> tuple:
    """`d.items()` of an Int-keyed dict `d`: the (key, value) pair list with
    an INTEGER key slot (mojo_dict_items_int), remembered in
    gen._dict_items_int_keys so the pair readers use get_int for slot 0."""
    dt, dv = gen.lower_expr(recv)
    dt = gen._get_actual_type(dt, dv)
    if dv in gen.var_types and gen.var_types[dv] == 'int64_t':
        dv = gen._coerce_to_type('int64_t', 'MojoDict *', dv)
    t = gen._new_val('MojoList *', f"mojo_dict_items_int ({dv})")
    gen._dict_items_val_elems[t] = gen._dict_val_of(_as_str(recv.name))
    gen._dict_items_int_keys.add(t)
    return 'MojoList *', t


def _boxed_list_ptr(gen, lst_type: str, lst_val: str) -> str | None:
    """The `MojoList *` to iterate for a BOXED (int64_t) handle whose element
    type is POSITIVELY known, or None when there is no such evidence.

    This is the one definition of that rule, shared by every lowering that
    otherwise has to emit the runtime dict-or-list dispatch: `_gen_for_iter`
    (a bare `for <t> in <param>:`) and `_gen_for_enumerate`
    (`enumerate(<param>)`). Both need it, they need it for the same reason,
    and two copies of a rule about when a dispatch arm is provably dead is
    how they drift.

    The rule: `gen._elem_types` is only ever recorded for a LIST value — a
    literal, a cross-call parameter contract, a struct field — and a dict's
    keys are always strings, so an entry that is present and is not the
    `int64_t` "nothing known" default is positive evidence that the handle
    is a list AND the element type to read it with. The dict (and set) arm
    is then provably dead, and skipping it is not an optimization: both arms
    bind the SAME loop variable, `_declare_var` is first-decl-wins, so
    emitting the dead arm declares one variable with two incompatible types
    and `gcc -fgimple` rejects the whole function ("assignment to
    'FunctionDef *' from incompatible pointer type 'char *'", or, for a
    `double` element against a `char *` dict key, "pointer value used where a
    floating-point was expected").

    Returns None for the untyped case, and the caller falls back to emitting
    the dispatch exactly as before.
    """
    if lst_type not in ('int', 'int64_t', 'void *'):
        return None
    elem = gen._elem_of(lst_val)
    if not elem or elem == 'int64_t':
        return None
    lp = gen._coerce_to_type('int64_t', 'MojoList *', gen._to_int64(lst_type, lst_val))
    gen._elem_types[lp] = elem
    return lp


def _gen_for_iter(gen, node: gimple_ctypes.ForStmt):
    # `for m in <compile-time-known-pattern>.finditer(text):` — see
    # regex_compile.py / BACKLOG-CODEGEN.md §4f. Checked structurally,
    # BEFORE the generic lower_expr(node.iterable) below (which has no
    # case for .finditer() and would otherwise route to the
    # unsupported-iterable fallback). Wrapped in try/except: this is new,
    # narrowly-tested machinery — any failure to compile the pattern or
    # emit the loop falls back to the pre-existing safe behavior rather
    # than breaking a build that doesn't even care about this loop's
    # correctness (e.g. compiling this file as an IMPORTED module for an
    # unrelated program).
    it = node.iterable
    if (isinstance(it, gimple_ctypes.CallExpr) and isinstance(it.func, gimple_ctypes.MemberExpr)
            and it.func.member == 'finditer' and isinstance(it.func.obj, gimple_ctypes.IdentExpr)
            and it.func.obj.name in gen._regex_patterns and len(it.args) == 1):
        # Transactional: roll back any partially-emitted lines/decls if
        # the attempt fails partway, so the fallback path below starts
        # from clean state instead of leaving stray/inconsistent C.
        body_mark, decls_mark = len(gen.body_lines), len(gen.decls)
        try:
            gen._gen_for_regex_iter(node, gen._regex_patterns[it.func.obj.name])
            return
        except Exception as e:
            del gen.body_lines[body_mark:]
            del gen.decls[decls_mark:]
            gimple_ctypes._debug_note('regex finditer lowering failed, falling back', e)

    # `for x in <known-pattern>.findall(text):` — see
    # _gen_for_findall_loop below. Same transactional shape as the finditer
    # case above: a lowering that cannot prove a shape supported rolls back
    # completely and leaves the pre-existing refusal in place, which is
    # loud, rather than half-emitting a loop that computes something else.
    if (isinstance(it, gimple_ctypes.CallExpr) and isinstance(it.func, gimple_ctypes.MemberExpr)
            and it.func.member == 'findall'):
        body_mark, decls_mark = len(gen.body_lines), len(gen.decls)
        try:
            _gen_for_findall_loop(gen, node)
            return
        except Exception as e:
            del gen.body_lines[body_mark:]
            del gen.decls[decls_mark:]
            gimple_ctypes._debug_note('regex findall lowering failed, falling back', e)

    # `for a, b in materialize[LIST_CONST]():` — `materialize[T,//,value:T]
    # (out result: T)` (std.builtin.value) just hands back its bracket
    # VALUE param unchanged; LIST_CONST here is a `comptime NAME = [T(...),
    # ...]` whose elements are ordinary constructor-call literals (a
    # Tuple(...) call isn't scalar-foldable, so it never reaches
    # self._comptime_vals — see _gen_stmt_ComptimeVarStmt). Rather than try
    # to give `materialize` a real runtime elaboration (it has no concrete
    # struct/function body to instantiate — its ENTIRE job is being a
    # comptime-to-runtime identity), UNROLL the loop over the literal
    # elements directly: each iteration's loop var(s) are assigned straight
    # from that element's own literal sub-expressions, so `number`/
    # `number_as_str` end up correctly typed (Float64/char*) instead of
    # falling through to the boxed dict/list runtime-dispatch fallback,
    # which can only ever produce one ambiguous type for both. Real, in
    # stdlib's own test_atof.mojo (`for number, number_as_str in
    # materialize[numbers_to_test]():`).
    if (isinstance(it, gimple_ctypes.CallExpr) and not it.args
            and isinstance(it.func, gimple_ctypes.SubscriptExpr)
            and isinstance(it.func.obj, gimple_ctypes.IdentExpr) and it.func.obj.name == 'materialize'
            and isinstance(it.func.index, gimple_ctypes.IdentExpr)
            and it.func.index.name in gen._comptime_list_asts):
        list_ast = gen._comptime_list_asts[it.func.index.name]
        var0 = node.target
        if gimple_ctypes.for_target_is_tuple(var0):
            tgt_names = gimple_ctypes.target_slots(var0[1:-1].strip())
        else:
            tgt_names = gimple_ctypes.for_target_names(var0)
        for el in list_ast.elements:
            el_args = el.args if isinstance(el, gimple_ctypes.CallExpr) else [el]
            if len(el_args) < len(tgt_names):
                continue
            for i, vn in enumerate(tgt_names):
                at, av = gen.lower_expr(el_args[i])
                gen._declare_var(vn, at)
                cvn = gen._cname(vn)
                if gen.var_types.get(vn, at) == at:
                    gen._emit(f"  {cvn} = {av};")
                else:
                    gen._safe_coerce_emit(at, gen.var_types[vn], av, cvn)
            for s in node.body:
                gen.gen_stmt(s)
        return

    var = node.target
    # NOTE: `node.target` is ALWAYS a plain Python str (see
    # _parse_unpack_target in fire_compiler.py and _gen_for_regex_iter's
    # identical fix) — the old `if isinstance(node.target, str) else
    # node.target.name` split existed only because the field is typed
    # `object`/boxed int64_t in struct_field_types, so in the COMPILED
    # binary the isinstance fell to the always-false mojo_isinstance stub
    # and `node.target.name` wrongly dispatched on the raw string bytes
    # (a hard segfault). The parser contract guarantees the string form.
    # `for f in dataclasses.fields(x): ... f.name ...` — _lower_method_call
    # (see there) already turns dataclasses.fields(x) into a real
    # MojoList* of field-name strings, so this flows through the normal
    # MojoList* loop below with no special lowering of its own. The only
    # thing that needs tracking here is that `f` in the loop body IS the
    # name itself (a plain char*), not a real dataclasses.Field object —
    # `_lower_MemberExpr`'s `.name` special-case (see there) checks this
    # set to make `f.name` resolve to `f`.
    is_dataclass_fields_loop = (
        isinstance(it, gimple_ctypes.CallExpr) and isinstance(it.func, gimple_ctypes.MemberExpr)
        and gimple_ctypes._is_dataclasses_module_ref(it.func.obj)
        and it.func.member == 'fields')
    if is_dataclass_fields_loop:
        gen._dataclass_fields_vars.add(var)

    # `for x in it:` where `it` is a resumable list-iterator local (bound by
    # `it = iter(<list>)`, tracked in `_list_iter_cursor`) — continue from the
    # shared cursor (which `next(it)` may already have advanced) and leave it
    # exhausted afterward, real Python single-pass iterator semantics. Must
    # run BEFORE the generic lower_expr(node.iterable) below, which would
    # treat `it` as a plain MojoList* and restart the scan from element 0.
    if (isinstance(it, gimple_ctypes.IdentExpr)
            and itc.cursor_for(gen, gen._cname(it.name)) is not None
            and isinstance(var, str) and not gimple_ctypes.for_target_is_tuple(var)
            and not getattr(node, 'else_body', None)):
        _gen_for_iter_cursor(gen, node, var)
        return

    # A loop over a provably Dict[Int, V] name (`for k in d`, `d.keys()`,
    # `d.items()`) gets its keys back as integers; see _int_dict_loop_source.
    _int_mode, _int_recv = _int_dict_loop_source(gen, it)
    try:
        if _int_mode == 'items':
            it_type, it_val = _lower_int_dict_items(gen, _int_recv)
        elif _int_mode:
            it_type, it_val = gen.lower_expr(_int_recv)
        else:
            it_type, it_val = gen.lower_expr(node.iterable)
    except Exception:
        if is_dataclass_fields_loop:
            gen._dataclass_fields_vars.discard(var)
        raise

    # `for x in <fresh container>:` (a display, a comprehension, a slice, a
    # `.split()`/`.keys()` result): nothing else can reference the iterable, so
    # it is freed when the loop statement ends. Claimed HERE, before any code
    # below emits a call on it.
    gen._claim_loop_iterable_temp(_int_recv if _int_mode == 'keys' else node.iterable, it_val, it_type)

    # Check if this is an int64_t-stored pointer (from method call returning pointer)
    it_type = gen._get_actual_type(it_type, it_val)

    # `for c in <bytes-subclass instance>:` iterates its backing MojoBytes
    # payload (each `c` an int 0-255). See COMPILE_FAIL_zipfile___init__.md.
    if gen._bytes_subclass_of(it_type):
        it_val = gen._new_val('MojoBytes *', f"{it_val}->_data")
        it_type = 'MojoBytes *'

    # Self-shadowing loop target: `for tail in tail:` — the loop's OWN
    # target variable has the same name as the list/dict/etc it iterates.
    # Only possible when the iterable is a bare IdentExpr whose lowered
    # value IS the raw variable name with no copy (`_lower_IdentExpr`'s
    # plain-read case: `cname = self._c_names.get(name, name)` — a
    # computed/literal iterable expression can't collide this way).
    # Without special-casing this, two things break together:
    #   1. `_gen_for_list`/etc reuse the SAME C identifier for both the
    #      iterable's own list-pointer value and the loop's per-iteration
    #      element — every `mojo_list_len`/`mojo_list_get_int` call after
    #      the 1st iteration reads back an already-overwritten value.
    #   2. `_declare_var`'s deliberate first-decl-wins guard (protects
    #      the common "same loop-var name reused across separate sibling
    #      loops" case) leaves the loop target's C variable declared
    #      under the ITERABLE's stale type for the rest of the loop body.
    # Fix: snapshot the iterable's value into a fresh, stable temp BEFORE
    # the loop starts (decouples the list-pointer reads from whatever the
    # loop target's C variable gets overwritten with), and force a fresh,
    # non-colliding C declaration for the loop target (see
    # `_declare_var(force=True)`).
    target_names = gimple_ctypes.for_target_names(var)
    shadow_name = None
    if (isinstance(it, gimple_ctypes.IdentExpr) and it.name in target_names
            and it_val == gen._c_names.get(it.name, it.name)):
        shadow_name = it.name
        orig_name = it.name
        # Snapshot using the C name's ACTUAL declared type (which may be
        # 'int64_t' if the container is boxed-pointer-stored — e.g. it
        # came out of a method call earlier), not the semantic `it_type`
        # ('MojoList *' etc). Every `_gen_for_*` below already knows how
        # to cast an int64_t-boxed pointer back to the real container
        # type at the point of use (`if it_val in self.var_types and
        # self.var_types[it_val] == 'int64_t': ... cast ...`); assigning
        # straight into a same-typed temp here keeps that existing
        # boxed-pointer path working unchanged, and avoids emitting an
        # invalid pointer-from-integer assignment with no cast.
        snapshot_ctype = gen.var_types.get(orig_name, it_type)
        it_val = gen._new_val(snapshot_ctype, it_val)
        # Carry over container metadata (element type, boxed-pointer
        # actual type, dict value type, nested-list element type) from
        # the original name to the fresh snapshot temp, so downstream
        # `_elem_of`/`_get_actual_type`/etc lookups (keyed by C
        # value/name) still resolve correctly for the snapshot.
        for _meta in (gen._elem_types, gen._actual_types,
                      gen._dict_val_types, gen._nested_elem_types):
            if orig_name in _meta:
                _meta[it_val] = _meta[orig_name]

    try:
        if it_type == 'MojoList *':
            gen._gen_for_list(var, it_val, node.body, shadow_name=shadow_name)
        elif it_type == 'MojoStr *':
            gen._gen_for_str(var, it_val, node.body, shadow_name=shadow_name)
        elif it_type == 'char *':
            gen._gen_for_cstr(var, it_val, node.body)
        elif it_type == 'MojoBytes *':
            gen._gen_for_bytes(var, it_val, node.body)
        elif it_type == 'MojoMemoryView *':
            gen._gen_for_memoryview(var, it_val, node.body)
        elif it_type == 'MojoDict *':
            gen._gen_for_dict(var, it_val, node.body, shadow_name=shadow_name,
                              int_keys=bool(_int_mode))
        elif it_type == 'MojoSet *':
            gen._gen_for_set(var, it_val, node.body, shadow_name=shadow_name)
        elif it_type == 'MojoGenerator *':
            # Milestone B: `for x in <supported generator call>():` —
            # checked before the generic user-struct __iter__ protocol
            # branch below (which would otherwise treat MojoGenerator*
            # like any other pointer-shaped struct type and look for a
            # nonexistent MojoGenerator___has_next__/__next__).
            api = gen._generator_var_api.get(it_val)
            if api is not None:
                # `async for x in gen():` in an ORDINARY (never-suspended)
                # function -- the one place an async generator can be
                # consumed by a consumer with no yield channel of its own,
                # so it is also the one place `_gen_for_generator_iter`'s
                # resume/value pair below is not automatically right: this
                # coroutine's channel carries a wait-descriptor (is_wd=1)
                # for every parking `await` and a real value (is_wd=0) for
                # every `yield`, and an ordinary C function has no `__c` to
                # forward a descriptor on. Binding it as the loop variable
                # is real silent garbage, not merely a wrong answer to the
                # loop count -- measured, a generator awaiting
                # `asyncio.sleep(0)` printed a heap ADDRESS instead of its
                # yield value. So drive it only when the coroutine is
                # proven never to produce a descriptor, and refuse it
                # otherwise. The analysis is coro.py's
                # `_compute_no_wd_forward` fixpoint, carried on the api as
                # `no_wd_forward`; `_cpp_async_for_stmt` refuses the same
                # consumer shape for the C++ backend on unrelated grounds
                # (`async for` is only legal inside an async body), so
                # this is the stackswitch path's matching honest refusal,
                # not a new restriction.
                #
                # Deliberately NOT gated on `node.is_async`: a plain
                # `for x in gen()` over an async generator is a TypeError in
                # CPython, so there is no correct behaviour to preserve
                # here -- only the silent-garbage one to remove. A clean
                # async generator keeps its existing lowering on that
                # spelling.
                if api.get('is_async_gen') and not api.get('no_wd_forward'):
                    raise RuntimeError(
                        "cannot compile module: `async for` over async "
                        f"generator {api.get('base') or it_val!r} in an "
                        "ordinary function — that generator's body can "
                        "suspend (it has an `await` that may park), so its "
                        "yield channel carries a wait-descriptor the "
                        "enclosing function has no channel of its own to "
                        "forward; drive it from an `async def` body "
                        "(`await asyncio.run(...)`) instead")
                # Only auto-destroy the coroutine when this `for` loop's
                # iterable expression IS the generator construction call
                # itself (`for x in counter(3):`) — that value has no
                # other reference anywhere, so destroying it right after
                # the loop is the only chance to ever free it, exactly
                # matching Milestone B's original (pre-first-class-value)
                # behavior. When the iterable is instead a plain variable
                # reference (`g = counter(3); for x in g:` — the first-
                # class-value case this step adds), the SAME variable may
                # be read again later (another `for`/`next()`, or simply
                # falling out of scope naturally) — auto-destroying here
                # made a second consumption attempt a real use-after-free
                # (confirmed via a real compiled repro: a second `for x in
                # g:` after the first fully drained it crashed with SIGBUS,
                # not merely "0 iterations" like real Python's exhausted-
                # iterator semantics). Skipping the destroy for this shape
                # trades a coroutine-frame leak (no destructor call ever
                # runs for a named generator variable) for correctness —
                # strictly better than a crash, and a known, documented
                # follow-up (proper lifetime/ownership tracking for a
                # first-class MojoGenerator* is future work, not solved
                # here). See bugs/CODEGEN_compiled_generator_not_first_
                # class_value.md.
                destroy_after = isinstance(node.iterable, gimple_ctypes.CallExpr)
                gen._gen_for_generator_iter(var, it_val, api, node.body,
                                              destroy_after=destroy_after)
            else:
                gimple_ctypes._debug_note('for loop over MojoGenerator* with no known API (unreachable in Milestone B scope)', it_val)
                gen._emit_unsupported_iter(it_type, node)
        elif ((it_type.endswith(' *') and it_type != 'void *')
              or it_type.endswith('*')):
            # User-defined struct: try __iter__ / __has_next__ / __next__ protocol
            #
            # `void *` is EXCLUDED, and that exclusion is load-bearing.
            # `'void *'.endswith(' *')` is true, so before it the arm took
            # every untyped pointer-shaped value — including the plain
            # `void *` that `_lower_builtin_reversed`'s unrecognized-type
            # fallthrough (and a comprehension result, and several builtin
            # stubs) produce — and looked for a `void___has_next__` that
            # cannot exist, then REFUSED. That made the boxed runtime
            # dispatch below, whose own `it_type in ('int', 'int64_t',
            # 'void *')` test names `void *` explicitly, unreachable for
            # `void *` — the two arms contradicted each other and the
            # narrower one won. `for x in reversed(seq)` therefore ran zero
            # times with a `mojo_unsupported_iter` naming `void *`, which is
            # the exact silent-no-op this site exists to prevent.
            #
            # A user-defined struct is never spelled `void *` in this
            # codegen (every emitted struct has its own `Foo *` typedef), so
            # excluding it costs the struct-protocol branch nothing.
            base = gimple_exprtypes._struct_name_of(it_type)
            has_next = f"{base}___has_next__"
            nxt      = f"{base}___next__"
            # A builtin-`dict` subclass instance with no iterator-protocol
            # override: `for k in d` iterates the hidden `_data` backing
            # store's keys, exactly like a plain dict. A subclass defining
            # its own `__iter__`/`__next__` keeps the protocol path above.
            if (gen._dict_subclass_of(it_type)
                    and has_next not in gen.func_return_types
                    and nxt not in gen.func_return_types
                    and f"{base}___iter__" not in gen.func_return_types):
                _dsub_dp = gen._new_val('MojoDict *', f"{it_val}->_data")
                gen._gen_for_dict(var, _dsub_dp, node.body, shadow_name=shadow_name)
            elif has_next in gen.func_return_types or nxt in gen.func_return_types:
                gen._gen_for_struct_iter(var, it_type, it_val, node.body,
                                         shadow_name=shadow_name, node=node)
            else:
                gimple_ctypes._debug_note(
                    'for loop dropped (no iterator protocol)',
                    f"{it_type} fn={getattr(gen, 'current_func_name', '?')}")
                gen._emit_unsupported_iter(it_type, node)
        else:
            # A boxed int64_t iterable whose real container type wasn't
            # statically tracked — e.g. `for fname in pat.fields:` in
            # ast_rewriter.py, where `pat` is a boxed pattern Node and
            # `.fields` is a MojoDict* read via the A5 boxed-member
            # dispatch into an int64_t. The old behavior dropped the loop
            # entirely (mojo_unsupported_iter, body runs zero times), so
            # the compiled binary's ast_rewriter silently produced no
            # discriminators and NO file could compile. The runtime
            # registries distinguish a real dict/list, so branch to the
            # right iterator instead.
            #
            # NOTE (known residual): this compiles loop bodies that were
            # previously dropped, exposing the `item.key`/`item.value`
            # pair-accessor gap (counter/interval/_unicode/string_slice
            # stdlib modules regress) — see A5-BUG.md. Keep this patch in
            # the tree as the starting point for resolving the frontier.
            # POSITIVE EVIDENCE the boxed handle is a LIST, and the element
            # type to read it with: skip the runtime dict-or-list dispatch
            # entirely. `_boxed_list_ptr` owns that rule and its rationale;
            # this is one of its two callers.
            #
            # This is what closes the GENERATOR's version of the shape: a
            # generator's params cross as untyped `int64_t` slots, so
            # `def rows(data): for r in data: yield r` called
            # `rows([1.5, 2.5])` had no element type here at all, the dict arm
            # won the shared `r`, and the `double` yield slot could not be fed
            # from a `char *` (a hard `gcc -fgimple` "pointer value used where a
            # floating-point was expected"). The element ctype reaches
            # `_elem_types` via `_mojo_coro_param_elem_kinds` ->
            # `_param_elem_types` -> `gen_func`. See
            # bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md.
            _lp_known = _boxed_list_ptr(gen, it_type, it_val)
            if _lp_known is not None:
                gen._gen_for_list(var, _lp_known, node.body)
            elif it_type in ('int', 'int64_t', 'void *'):
                bb_dict = gen._new_bb(); bb_list = gen._new_bb()
                bb_not_dict = gen._new_bb(); bb_not_list = gen._new_bb()
                bb_after = gen._new_bb()
                it64 = gen._to_int64(it_type, it_val)
                isd = gen._call_expr('int', 'mojo_is_registered_dict', [('int64_t', it64)])
                gen._emit(f"  if ({isd}) goto {bb_dict}; else goto {bb_not_dict};")
                gen._emit_label(bb_not_dict)
                isl = gen._call_expr('int', 'mojo_is_registered_list', [('int64_t', it64)])
                gen._emit(f"  if ({isl}) goto {bb_list}; else goto {bb_not_list};")
                gen._emit_label(bb_not_list)
                gen._emit_unsupported_iter(it_type, node)
                gen._emit(f"  goto {bb_after};")
                # `for item in <x>.items():` — even when `x`'s type is
                # unknown (a boxed int64_t, e.g. Counter.items() returning
                # an un-elaborated generic _DictEntryIter), the SYNTAX
                # says this yields key/value PAIRS, not bare keys. Iterate
                # the dict's items list rather than _gen_for_dict's keys,
                # so a single loop var binds the whole pair and
                # `item.key`/`item.value` resolve (see
                # _dict_item_pair_vars). Without this the dict branch bound
                # `item` to a char* key and `-item.value` hit a GIMPLE
                # "wrong type argument to unary minus" / a build2 ICE —
                # A5-BUG.md §1's residual, which regressed counter/
                # interval/_unicode/string_slice.
                _it_is_items = (
                    isinstance(node.iterable, gimple_ctypes.CallExpr)
                    and isinstance(node.iterable.func, gimple_ctypes.MemberExpr)
                    and node.iterable.func.member == 'items'
                    and not node.iterable.args
                    and not gimple_ctypes.for_target_is_tuple(var))
                gen._emit_label(bb_dict)
                dp = gen._coerce_to_type('int64_t', 'MojoDict *', it64)
                if _it_is_items:
                    _pairs = gen._new_val(
                        'MojoList *', f"mojo_dict_items ({dp})")
                    # Value type is genuinely unknown here (the receiver
                    # never typed) — int64_t matches how mojo_dict_items
                    # boxes the value slot.
                    gen._dict_items_val_elems[_pairs] = 'int64_t'
                    gen._gen_for_list(var, _pairs, node.body, share_var_with_sibling_arm=True)
                else:
                    gen._gen_for_dict(var, dp, node.body)
                gen._emit(f"  goto {bb_after};")
                gen._emit_label(bb_list)
                lp = gen._coerce_to_type('int64_t', 'MojoList *', it64)
                if _it_is_items:
                    # An already-materialized items list: its elements are
                    # the same [key, value] pairs.
                    gen._dict_items_val_elems[lp] = 'int64_t'
                gen._gen_for_list(var, lp, node.body, share_var_with_sibling_arm=True)
                gen._emit(f"  goto {bb_after};")
                gen._emit_label(bb_after)
            else:
                gimple_ctypes._debug_note('for loop dropped (unsupported iterable)', it_type)
                gen._emit_unsupported_iter(it_type, node)
    finally:
        if is_dataclass_fields_loop:
            gen._dataclass_fields_vars.discard(var)


def _gen_for_zip_longest(gen, node):
    """Handle: for (a, b) in itertools.zip_longest(seq_a, seq_b
    [, fillvalue=v]): ...

    Real zip_longest semantics as a plain index loop: iterate
    max(len_a, len_b) times; each tuple-target slot is assigned from its
    OWN sequence's element i (read with that sequence's own tracked
    element-type accessor), or the fill value once the index runs past
    that sequence's length. The default fill is 0 — this scalar C model's
    representation of None — so the common `if x is None:` guards after a
    padded iteration test a genuine 0/NULL, exactly like real Python's
    None sentinel.

    Before this, `itertools.zip_longest(...)` hit _gen_for_iter's generic
    boxed-iterable fallback, where `itertools` is an opaque module global:
    the call itself stubbed to a bare int64_t and the loop targets fell to
    untyped int64_t slots — so `for input, output in
    itertools.zip_longest(inputs, outputs): input.peek = output.peek =
    True` (Tools/cases_generator/analyzer.py's analyze_stack) emitted raw
    struct member writes into a non-struct (hard g++ "request for member
    'peek' in something not a structure" errors), AND first-decl-wins
    locked those names to int64_t for every LATER loop over them too.
    Element types propagate per-slot from each sequence's own
    gen._elem_types entry, so struct-typed sequences (analyzer.py's
    list[StackItem] inputs/outputs) give genuinely struct-typed loop
    variables.

    Any shape this narrow handler can't prove supported (non-2-arity call,
    non-tuple target, non-list sequence, non-literal fillvalue) raises;
    the caller (_gen_stmt_ForStmt) rolls back partial output transactionally
    and falls through to the pre-existing generic path unchanged.
    """
    it = node.iterable
    args = list(it.args)
    fill_node = None
    for kwn, kwv in (it.kwargs or []):
        if kwn == 'fillvalue' and fill_node is None:
            fill_node = kwv
        else:
            raise ValueError(f"unsupported zip_longest argument {kwn}=...")
    if len(args) != 2:
        raise ValueError("only the 2-sequence zip_longest shape is supported")
    target = node.target
    if not gimple_ctypes.for_target_is_tuple(target):
        raise ValueError("zip_longest lowering needs a tuple loop target")
    tgt_names = [t.strip() for t in gen._split_top_level_comma(target[1:-1])]
    if len(tgt_names) != 2:
        raise ValueError("zip_longest lowering needs a 2-slot loop target")
    seqs = []
    for arg in args:
        st, sv = gen.lower_expr(arg)
        st = gen._get_actual_type(st, sv)
        if st != 'MojoList *':
            raise ValueError(f"zip_longest over {st} is unsupported here")
        ptr = sv
        if ptr in gen.var_types and gen.var_types[ptr] == 'int64_t':
            ptr = gen._coerce_to_type('int64_t', 'MojoList *', sv)
        seqs.append((ptr, gen._elem_of(sv)))

    # Per-slot read + fill expressions, all selected through ONE int64_t
    # (or double) select so the fill/element type mismatch never reaches
    # GIMPLE as differing ternary operand types. The final assignment to
    # the declared target coerces back to its real declared ctype (the
    # same box/unbox dance _gen_for_list's tuple branch uses).
    fills = []
    slot_reads = []  # (raw_ctype, expr_with_{i} placeholder fn)
    for ptr, elem in seqs:
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if suf == 'double':
            slot_reads.append(('double', lambda p=ptr: f"mojo_list_get_double ({p}, {gen._ziptmp})"))
            if fill_node is not None:
                ft, fv = gen.lower_expr(fill_node)
                if ft != 'double':
                    raise ValueError("fillvalue must be float-typed to fill a float sequence")
                fills.append(fv)
            else:
                fills.append(None)  # patched below with a 0.0 temp
        elif suf == 'str':
            slot_reads.append(('str', lambda p=ptr: f"mojo_list_get_str ({p}, {gen._ziptmp})"))
            if fill_node is not None:
                ft, fv = gen.lower_expr(fill_node)
                if ft != 'char *' and not isinstance(fill_node, gimple_ctypes.StringLiteral):
                    raise ValueError("fillvalue must be string-typed to fill a string sequence")
                fills.append(f"(int64_t)(char *)({fv})")
            else:
                fills.append('(int64_t)0')
        else:
            slot_reads.append(('int', lambda p=ptr: f"mojo_list_get_int ({p}, {gen._ziptmp})"))
            if fill_node is not None:
                ft, fv = gen.lower_expr(fill_node)
                fills.append(f"(int64_t)({fv})")
            else:
                fills.append('(int64_t)0')

    # Declare each target by its own slot's element type BEFORE the loop
    # (mirrors _gen_for_enumerate's declare-then-assign order; first-decl-
    # wins semantics preserved — later loops over the same names reuse
    # these real types instead of inheriting an int64_t lock-in).
    for vn, (_ptr, elem) in zip(tgt_names, seqs):
        gen._declare_var(vn, elem)

    len_ts = []
    for ptr, _elem in seqs:
        lt = gen._new_temp('int64_t')
        gen._emit(f"  {lt} = mojo_list_len ({ptr});")
        len_ts.append(lt)
    gt_t = gen._new_val('_Bool', f"{len_ts[0]} > {len_ts[1]}")
    n_t = gen._new_val('int64_t', f"{gt_t} ? {len_ts[0]} : {len_ts[1]}")
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {n_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen.loop_stack.append((bb_post, bb_after))
    gen._ziptmp = idx_t
    try:
        for si, vn in enumerate(tgt_names):
            raw_ct, read_fn = slot_reads[si]
            elem = seqs[si][1]
            cvn = gen._cname(vn)
            in_t = gen._new_val('_Bool', f"{idx_t} < {len_ts[si]}")
            raw = gen._new_val(
                'double' if raw_ct == 'double' else ('char *' if raw_ct == 'str' else 'int64_t'),
                read_fn())
            if raw_ct == 'double':
                fill_v = fills[si] if fills[si] is not None else "(double)0"
                sel = gen._new_val('double', f"{in_t} ? {raw} : {fill_v}")
            elif raw_ct == 'str':
                sel = gen._new_val('int64_t', f"{in_t} ? (int64_t){raw} : {fills[si]}")
            else:
                sel = gen._new_val('int64_t', f"{in_t} ? {raw} : {fills[si]}")
            vt = gen.var_types.get(vn, elem)
            if vt == 'double' and raw_ct == 'double':
                gen._emit(f"  {cvn} = {sel};")
            elif vt == 'char *':
                cs = gen._new_val('char *', f"(char *){sel}")
                gen._emit(f"  {cvn} = {cs};")
            elif vt == 'int64_t':
                gen._emit(f"  {cvn} = {sel};")
            else:
                # struct pointer / other declared ctype: unbox via a cast
                # initializer temp, then plain same-type assignment.
                cp = gen._new_val(vt, f"({vt}){sel}")
                gen._emit(f"  {cvn} = {cp};")
    finally:
        del gen._ziptmp

    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1

    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _carry_nested_elem_type(gen, target, it_val, elem) -> None:
    """One level IN: a loop target over a container OF containers must record
    on ITSELF what those inner containers hold, so a loop over the target
    inside the body types its own target from the same table instead of
    falling to the `int64_t` default.

    Without it the second loop reads its elements through
    `mojo_list_get_int` whatever they are, so `for row in rows: for cell in
    row: print(cell)` over `[["a", "b"]]` printed the strings' heap ADDRESSES
    -- exit 0, no diagnostic, and the integer spelling of the same program
    (`[[1, 2], [3, 4]]`) was correct, because `int64_t` happens to be what
    the default already is. `note_list_literal` /
    `_lower_list_literal` already do this carrying for a list LITERAL bound
    to a local (`_nested_elem_types[t] = _inner_ct`); what was missing is the
    same step for a name the ITERATION bound.

    Only `MojoList *` is carried: `_nested_elem_types` records what a list
    holds, and a struct pointer's fields are already reachable through
    `_actual_types`, which the callers set for themselves.

    One implementation, called from both loop paths that need it -- the
    `zip()` slot binding and the ordinary `for x in <list>` -- because they
    are the same step and a partial copy is exactly how the ordinary loop
    came to disagree with `zip()` about the same nested shape."""
    if _as_str(elem) != 'MojoList *':
        return
    _inner = gen._nested_elem_types.get(_as_str(it_val))
    if _inner is not None:
        gen._elem_types[target] = _inner


def _zip_bind_slot(gen, vn: str, list_ptr: str, elem: str, idx_t: str) -> None:
    """Bind one `zip()` loop target `vn` to `list_ptr[idx_t]`, reading with
    the accessor matching THAT sequence's own element type and coercing to
    the target's declared C type.

    Mirrors `_gen_for_list`'s per-slot `_emit_target_assign` (same accessor
    choice, same box/unbox and `_actual_types` recovery conventions) — the
    only difference is that a zip slot reads element `idx_t` of its OWN
    per-slot LIST, where a tuple-unpack slot reads element `i` of one
    shared tuple.

    `vn` may itself be a nested tuple target (`(_p_name, _p_raw_type)`)
    when this slot's own sequence is a list of tuples — the element at
    `idx_t` is then an opaque boxed tuple handle (int64_t on the wire,
    same as any tuple-literal-list element), unpacked the same way
    `_gen_for_list`'s `_emit_target_assign` unpacks a nested slot, just
    reading a fixed sub-index instead of a shared loop index."""
    if vn.startswith('(') and vn.endswith(')'):
        raw = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        nested_ptr = gen._coerce_to_type('int64_t', 'MojoList *', raw)
        nested_elem = gen._nested_elem_types.get(list_ptr, 'int64_t')
        for j, nn in enumerate(gen._split_top_level_comma(vn[1:-1].strip())):
            _zip_bind_slot(gen, nn, nested_ptr, nested_elem, j)
        return
    if starred_slot_index([vn]) >= 0:
        # The starred slot: read this sequence's element with the same
        # accessor rule as any other slot, then box it as the one-element
        # list `*b` means in `for a, *b in zip(...)`.
        _se = elem if elem else 'int64_t'
        _ssuf = gimple_ctypes.TypeLattice.list_suffix(_se)
        if _ssuf == 'str':
            _star_val = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
        elif _ssuf == 'double':
            _star_val = gen._new_val('double', f"mojo_list_get_double ({list_ptr}, {idx_t})")
        else:
            _star_val = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        _emit_starred_slot_from_value(gen, starred_slot_name(vn), _se,
                                      _star_val, _se)
        return
    cvn = gen._cname(vn)
    vt = gen.var_types.get(vn, elem)
    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
    if suf == 'double':
        raw = gen._new_val('double', f"mojo_list_get_double ({list_ptr}, {idx_t})")
        if vt == 'double':
            gen._emit(f"  {cvn} = {raw};")
        else:
            gen._safe_coerce_emit('double', vt, raw, cvn)
        return
    if suf == 'str':
        raw = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
        if vt == 'char *':
            gen._emit(f"  {cvn} = {raw};")
        else:
            ip = gen._new_val('int64_t', f"(int64_t){raw}")
            gen._emit(f"  {cvn} = {ip};")
            # Recover the real string type for later reads (print(),
            # f-strings, call args) — see _gen_for_list's identical note.
            gen._actual_types[vn] = 'char *'
        return
    raw = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
    if vt == 'int64_t':
        gen._emit(f"  {cvn} = {raw};")
    else:
        gen._safe_coerce_emit('int64_t', vt, raw, cvn)
    # A pointer element (struct pointer or nested container) keeps its real
    # type so `.member` / subscript reads inside the body resolve statically
    # instead of falling to the boxed dynamic-dispatch path.
    if elem and elem.endswith(' *'):
        gen._actual_types[vn] = elem
    _carry_nested_elem_type(gen, vn, list_ptr, elem)


def _gen_for_zip(gen, node):
    """`for (a, b[, c, ...]) in zip(seq_a, seq_b[, ...]):` — real zip
    semantics as a plain index loop over `min(len(seq_i))` iterations, each
    tuple-target slot read from its OWN sequence with that sequence's own
    tracked element-type accessor (so a `list[str]` slot binds a real
    `char *`, a `list[Struct *]` slot a real struct pointer, etc).

    Before this, `zip()` had NO for-loop lowering at all. The call fell
    through to `BUILTIN_VALUE_MAP`'s `mojo_zip`, so `_gen_for_iter` saw an
    opaque handle and emitted `mojo_unsupported_iter` — the loop body ran
    ZERO times, silently, with no diagnostic beyond that one note. That
    made SEVEN separate `for m, oid in zip(struct.methods, overload_ids):`
    passes in this compiler's own `gen_module_impl` dead code the moment it
    was self-hosted: Pass 2b-bis's `_struct_method_signatures` (so no
    overload ever resolved), the per-overload `_mangled_signature_ctypes`
    registrations, the comptime bracket-param scan, and `_scan_for_closures`
    over struct methods. Compiled mojoc therefore emitted no method
    signatures, no per-overload forward declarations, and auto-stubbed
    every struct-method call it lowered (`#define _MOJO_STUB_Counter_inc` /
    `int64_t Counter_inc (...);` in place of the real symbol).

    Any shape this handler can't prove supported (keyword arguments, fewer
    than two sequences, a non-tuple loop target, a target/sequence arity
    mismatch) raises; the caller (`_gen_stmt_ForStmt`) rolls back partial
    output transactionally and falls through to the pre-existing generic
    path unchanged. A nested tuple slot (one sequence a list of tuples) IS
    supported — see `_zip_bind_slot` — and so is a non-statically-typed
    sequence argument (dict/set/opaque boxed value), via
    `_materialize_as_list`."""
    it = node.iterable
    # `len(...) > 0`, NOT a bare `if it.kwargs:` — an EMPTY kwargs list is a
    # non-null MojoList* and therefore TRUTHY under the self-hosted backend's
    # pointer-nullity `if`, so this rejected EVERY `zip(a, b)` with no
    # keywords, fell back to the generic `mojo_unsupported_iter` path, and
    # ran the loop ZERO times. Real, reproducible: fire_compiler.py's own
    # `for op, operand in zip(node.ops, node.operands[1:]):` silently
    # dropped the rest of `emit`'s strings from the native output.
    if len(it.kwargs or []) > 0:
        raise ValueError("zip() takes no keyword arguments")
    args = list(it.args)
    if len(args) < 2:
        raise ValueError("only the multi-sequence zip() shape is lowered here")
    # `_as_str(node.target)`, NOT `isinstance(target, str) and target.startswith(...)`:
    # a tuple loop target (`for op, operand in ...`) is a `char *`-typed
    # ForStmt field on the self-hosted path, and `isinstance(<char *>, str)`
    # is the constant-FALSE static guard, so the condition was always true
    # and `_gen_for_zip` rejected EVERY tuple-target zip — falling back to
    # `mojo_unsupported_iter` and running the loop ZERO times (real:
    # fire_compiler.py's own `for op, operand in zip(node.ops,
    # node.operands[1:]):`, silently dropping the rest of `emit`).
    target = _as_str(node.target)
    if not gimple_ctypes.for_target_is_tuple(target):
        raise ValueError("zip() lowering needs a tuple loop target")
    tgt_names = [t.strip() for t in gen._split_top_level_comma(target[1:-1])]
    if len(tgt_names) != len(args):
        raise ValueError("zip() target arity does not match its sequence count")
    seq_ptrs = []
    seq_elems = []
    for _ai in range(len(args)):
        st, sv = gen.lower_expr(args[_ai])
        st = gen._get_actual_type(st, sv)
        # A zip() argument need not be a statically-known MojoList* — a
        # dict-subscript/`.get()` result (e.g. `zip(d.get('parameters') or
        # [], d['c_parameters'])`, the exact shape self-hosting this
        # compiler hit in gimple_module_gen.py) types as an opaque boxed
        # value. `_materialize_as_list` is the shared DESIGN.html R1/R5
        # chokepoint for "give me a MojoList* view of any iterable" used
        # by all()/any()/enumerate()/*.join()/the generic for-loop path —
        # use it here too instead of rejecting anything not already a
        # bare MojoList*.
        ptr = gen._materialize_as_list(st, sv)
        seq_ptrs.append(ptr)
        _e = gen._elem_of(ptr)
        seq_elems.append(_e if _e else 'int64_t')

    # Declare each target by its OWN slot's element type BEFORE the loop
    # (mirrors _gen_for_zip_longest / _gen_for_enumerate ordering).
    # `_declare_var` is first-decl-wins, so a later loop reusing the same
    # name inherits these real types instead of an int64_t lock-in.
    #
    # A slot's target can itself be a nested tuple (e.g. self-hosting this
    # very compiler hit `for (_p_name, _p_raw_type), _c_param in zip(...)`
    # in gimple_module_gen.py — a real, legal shape: one sequence is a
    # list of tuples). Declare the nested names with that sequence's OWN
    # nested element type (same `_nested_elem_types` lookup `_gen_for_list`
    # uses for its `pair_elem`), recursing for arbitrarily deep nesting.
    def _declare_zip_slot(vn: str, seq_ptr: str, elem: str) -> None:
        if vn.startswith('(') and vn.endswith(')'):
            nested_elem = gen._nested_elem_types.get(seq_ptr, 'int64_t')
            for nn in gen._split_top_level_comma(vn[1:-1].strip()):
                _declare_zip_slot(nn, seq_ptr, nested_elem)
            return
        if starred_slot_index([vn]) >= 0:
            # `for a, *b in zip(xs, ys)` binds `b` to a ONE-ELEMENT LIST
            # holding this slot's own element — zip yields one tuple per
            # iteration, so the remainder after `a` is exactly this slot.
            # Declared as the list it is; `_zip_bind_slot` below fills it.
            gen._declare_var(starred_slot_name(vn), 'MojoList *')
            return
        gen._declare_var(vn, elem)

    for _di in range(len(tgt_names)):
        _declare_zip_slot(tgt_names[_di], seq_ptrs[_di], seq_elems[_di])

    # Trip count is min(len(seq_i)) — real zip stops at the SHORTEST
    # sequence (that is the whole semantic difference from zip_longest,
    # which pads to the longest with a fill value).
    len_ts = []
    for _li in range(len(seq_ptrs)):
        _lt = gen._new_temp('int64_t')
        gen._emit(f"  {_lt} = mojo_list_len ({seq_ptrs[_li]});")
        len_ts.append(_lt)
    n_t = len_ts[0]
    for _mi in range(1, len(len_ts)):
        _shorter = gen._new_val('_Bool', f"{len_ts[_mi]} < {n_t}")
        n_t = gen._new_val('int64_t', f"{_shorter} ? {len_ts[_mi]} : {n_t}")

    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {n_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen.loop_stack.append((bb_post, bb_after))
    for _bi in range(len(tgt_names)):
        _zip_bind_slot(gen, tgt_names[_bi], seq_ptrs[_bi], seq_elems[_bi], idx_t)
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1

    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    nxt = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {nxt};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_enumerate_str(gen, node, s_val: str, start_val: str | None) -> None:
    """`for i, c in enumerate(s)` where `s` is a plain `char *` string —
    iterate characters via mojo_strlen/_mojo_at_char (mirrors _gen_for_cstr),
    NOT the list accessors _gen_for_enumerate otherwise uses (which
    reinterpret the char* as a MojoList* and segfault). Value slot is `char`."""
    target = node.target
    if isinstance(target, str) and target.startswith('(') and target.endswith(')'):
        parts = [p.strip() for p in gen._split_top_level_comma(target[1:-1])]
    elif isinstance(target, str):
        parts = [target, '_enum_val']
    else:
        gen._emit("  /* TODO: enumerate(str) non-string target */")
        return
    idx_var = parts[0] if len(parts) >= 1 else '_enum_i'
    val_var = parts[1] if len(parts) >= 2 else '_enum_val'

    gen._declare_var(idx_var, 'int64_t')
    # Same rule as _gen_for_cstr (see its comment): iterating a str yields
    # 1-char STRINGS, so the value slot is `char *` too. It was `char`,
    # which made `for i, c in enumerate(s)` hand out character codes.
    if starred_slot_index([val_var]) >= 0:
        # `for i, *rest in enumerate(s)`: the character's remainder is a
        # ONE-ELEMENT LIST (see `_gen_for_enumerate`'s identical arm).
        star_src = val_var
        gen._declare_var(starred_slot_name(val_var), 'MojoList *')
        val_var = gen._new_temp('char *')
    else:
        star_src = ''
        gen._declare_var(val_var, 'char *')
    cidx_var = gen._cname(idx_var)
    cval_var = gen._cname(val_var)

    len_t = gen._new_val('int64_t', f"mojo_strlen ({s_val})")
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen.loop_stack.append((bb_post, bb_after))
    if start_val is not None:
        disp_idx = gen._new_val('int64_t', f"{idx_t} + {start_val}")
        gen._emit(f"  {cidx_var} = {disp_idx};")
    else:
        gen._emit(f"  {cidx_var} = {idx_t};")
    # `mojo_char_at_str(s, i)` rather than a `char`-taking helper: gimple
    # rejects a `char` argument outright, so `mojo_char_to_str(s[i])` is not
    # available — see _gen_for_cstr for the whole of it. It shares
    # mojo_char_to_str's immortal table, where the `mojo_cstr_slice` this
    # replaced allocated one string per character and freed none of them. The
    # `_mojo_at_char` helper this used to ask for is not requested any more:
    # nothing here needs a pointer INTO the string, and asking for it emitted
    # a `static` definition no call site used.
    gen._emit(f"  {cval_var} = mojo_char_at_str ({s_val}, {idx_t});")
    if star_src:
        # Iterating a `str` yields 1-char STRINGS, so the starred list's
        # element type is `char *` (see the declaration above). Mirrors
        # `_gen_for_cstr`'s identical arm.
        _emit_starred_slot_from_value(gen, starred_slot_name(star_src),
                                      'char *', cval_var, 'char *')
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    nxt = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {nxt};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_enumerate(gen, node):
    """Handle: for (idx, val) in enumerate(lst[, start]): ..."""
    lst_arg = node.iterable.args[0]
    lst_type, lst_val = gen.lower_expr(lst_arg)
    lst_type = gen._get_actual_type(lst_type, lst_val)

    # `enumerate(lst, start)` — the optional 2nd arg was previously
    # silently dropped entirely (no arity check anywhere in this
    # function), so `for i, x in enumerate(items, 5):` compiled clean
    # but silently produced 0-based indices instead of 5-based ones —
    # a silent wrong-value bug, not a compile error (the compile-error
    # shape of this same gap showed up separately in the
    # comprehension-embedded `for` clause form; see
    # `_lower_comprehension`'s `is_enumerate` handling and
    # bugs/CODEGEN_generator_function_Lib_gettext.md root cause #2).
    # `idx_t` below stays the 0-based list-access index (used for
    # every `mojo_list_get_*` call); only the user-visible `cidx_var`
    # gets the start offset added.
    start_val = None
    if len(node.iterable.args) >= 2:
        _, start_raw = gen.lower_expr(node.iterable.args[1])
        start_val = gen._new_val('int64_t', f"(int64_t){start_raw}")

    if lst_type == 'MojoGenerator *':
        api = gen._generator_var_api.get(lst_val)
        if api is not None:
            _gen_for_enumerate_generator(
                gen, node, lst_val, api, start_val,
                destroy_after=isinstance(lst_arg, gimple_ctypes.CallExpr))
            return
        gimple_ctypes._debug_note(
            'enumerate() over MojoGenerator* with no known api', lst_val)

    if lst_type == 'char *':
        _gen_for_enumerate_str(gen, node, lst_val, start_val)
        return

    target = node.target
    if isinstance(target, str) and target.startswith('(') and target.endswith(')'):
        # Use bracket-aware split to handle nested tuples like (i, (a, b, c))
        parts = gen._split_top_level_comma(target[1:-1])
    elif isinstance(target, str):
        parts = [target, '_enum_val']
    else:
        gen._emit(f"  /* TODO: enumerate non-string target */")
        return

    idx_var = parts[0] if len(parts) >= 1 else '_enum_i'
    raw_val = parts[1] if len(parts) >= 2 else '_enum_val'

    # If the value part is itself a tuple like (a, b, c), use a temp for the element
    val_is_tuple = (isinstance(raw_val, str) and
                    raw_val.startswith('(') and raw_val.endswith(')'))
    # ...or a STARRED slot (`for i, *rest in enumerate(xs)`), which binds
    # the yielded pair's second half as a ONE-ELEMENT LIST. enumerate's pair
    # is synthesized slot by slot rather than sliced out of a row, so this is
    # the `_emit_starred_slot_from_value` shape, not `_emit_starred_slot_list`
    # — and without it the star reached the C declarator as
    # `int64_t *rest;` with a store through it, so `rest` read as 0.
    val_is_star = (isinstance(raw_val, str) and raw_val.strip().startswith('*')
                   and not val_is_tuple)
    if val_is_tuple:
        val_var = gen._new_temp('int64_t')
    elif val_is_star:
        # The temp that receives the value is minted BELOW, once the
        # sequence's element type is known — its C type has to match that
        # element, not be guessed here (`char *` for an int list is exactly
        # the "makes pointer from integer" this avoids).
        val_var = None
    else:
        val_var = raw_val

    # Ensure underlying list
    if lst_type == 'MojoList *':
        list_ptr = lst_val
        if lst_val in gen.var_types and gen.var_types[lst_val] == 'int64_t':
            list_ptr = gen._coerce_to_type('int64_t', 'MojoList *', lst_val)
    else:
        # Same positive-list-evidence shortcut as `_gen_for_iter`, same
        # helper, same reason (`_boxed_list_ptr`): without it
        # `enumerate(<list param>)` materialized the param through the
        # dict/set/list dispatch into a FRESH temp that carries no element
        # type, so `for i, v in enumerate(xs)` read every value with
        # `mojo_list_get_int` and printed a list of floats as their raw
        # IEEE-754 bit patterns -- even though the identical program with a
        # bare `for v in xs:` was correct. See
        # bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md.
        _lp_known = _boxed_list_ptr(gen, lst_type, lst_val)
        if _lp_known is not None:
            list_ptr = _lp_known
        else:
            # DESIGN.html R1/R5: dict/set materialization (`enumerate(d)`/
            # `enumerate(s)` — real Python semantics: a dict's KEYS, a set's
            # elements, not a reinterpret of the header) shares
            # _materialize_as_list with all()/any()/str.join()/bytes.join()/
            # shlex.join(); a genuinely-unknown boxed handle is now also
            # runtime-guarded (mojo_is_registered_dict/_set) there instead of
            # blindly assuming list.
            list_ptr = gen._materialize_as_list(lst_type, lst_val)

    elem = gen._elem_of(list_ptr)
    gen._declare_var(idx_var, 'int64_t')
    star_elem = None
    if val_is_star:
        # The starred slot is a LIST of what follows the index, not the
        # index's own slot type — declared by the emission below, which also
        # records its element type so `print(rest)` prints `[7]` and not a
        # pointer.
        gen._declare_var(starred_slot_name(raw_val), 'MojoList *')
        star_elem = elem if elem else 'int64_t'
        val_var = gen._new_temp({
            'str': 'char *', 'double': 'double'}.get(
                gimple_ctypes.TypeLattice.list_suffix(star_elem), 'int64_t'))
    elif not val_is_tuple:
        gen._declare_var(val_var, elem if elem else 'int64_t')
    # Writes go through _cname (a target named after a C keyword is
    # DECLARED renamed — see _gen_for_dict's identical note). `val_var` is
    # a fresh temp in the tuple case, so _cname is a no-op there.
    cidx_var = gen._cname(idx_var)
    cval_var = gen._cname(val_var)

    len64 = gen._new_temp('int64_t')
    len_t = gen._new_temp('int64_t')
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {len64} = mojo_list_len ({list_ptr});")
    gen._emit(f"  {len_t} = {len64};")
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen.loop_stack.append((bb_post, bb_after))

    if start_val is not None:
        disp_idx = gen._new_val('int64_t', f"{idx_t} + {start_val}")
        gen._emit(f"  {cidx_var} = {disp_idx};")
    else:
        gen._emit(f"  {cidx_var} = {idx_t};")

    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    if val_is_tuple:
        # Get element as opaque int64_t for tuple unpacking below
        elem64 = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        gen._emit(f"  {cval_var} = {elem64};")
        # Emit tuple unpacking: (a, b, c) = val_var — read each slot with
        # the accessor matching how the tuple was stored (get_str for
        # string tuples, get_int for boxed values), like _gen_for_list's
        # tuple branch; the old code read everything via get_int, so a
        # string tuple's char* slots became decimal pointers.
        inner = raw_val[1:-1].strip()
        tuple_vars = gen._split_top_level_comma(inner)
        tuple_ptr = gen._coerce_to_type('int64_t', 'MojoList *', val_var)
        pair_elem = gen._nested_elem_types.get(list_ptr, 'int64_t')
        suf_inner = gimple_ctypes.TypeLattice.list_suffix(pair_elem)
        for vi, vname in enumerate(tuple_vars):
            if vname == '_':
                continue
            cv = gen._cname(vname)
            gen._declare_var(vname, pair_elem)
            if suf_inner == 'str':
                ts = gen._new_val('char *', f"mojo_list_get_str ({tuple_ptr}, {vi})")
                if gen.var_types.get(vname, pair_elem) == 'char *':
                    gen._emit(f"  {cv} = {ts};")
                else:
                    ip = gen._new_val('int64_t', f"(int64_t){ts}")
                    gen._emit(f"  {cv} = {ip};")
                    gen._actual_types[vname] = 'char *'
            else:
                ti = gen._new_val('int64_t', f"mojo_list_get_int ({tuple_ptr}, {vi})")
                if gen.var_types.get(vname, pair_elem) == 'int64_t':
                    gen._emit(f"  {cv} = {ti};")
                else:
                    gen._safe_coerce_emit('int64_t', gen.var_types.get(vname, pair_elem), ti, cv)
    elif val_is_star:
        # `rest = [<element>]` — the pair's second half, as a one-element
        # list. The element is read with the same per-element accessor rule
        # as every other slot here, then boxed by the shared helper (the
        # receiving temp's C type already matches `star_elem`, minted above).
        _se_suf = gimple_ctypes.TypeLattice.list_suffix(star_elem)
        if _se_suf == 'str':
            _sv = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
        elif _se_suf == 'double':
            _sv = gen._new_val('double', f"mojo_list_get_double ({list_ptr}, {idx_t})")
        else:
            _sv = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        gen._emit(f"  {cval_var} = {_sv};")
        _emit_starred_slot_from_value(gen, starred_slot_name(raw_val),
                                      star_elem, cval_var, star_elem)
    elif suf == 'double':
        gen._emit(f"  {cval_var} = mojo_list_get_double ({list_ptr}, {idx_t});")
    elif suf == 'str':
        temp_str = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
        if gen._type_of(val_var) == 'char *':
            gen._emit(f"  {cval_var} = {temp_str};")
        else:
            int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
            gen._emit(f"  {cval_var} = {int_ptr};")
    else:
        elem64 = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        vt = gen._type_of(val_var)
        if vt and vt != 'int64_t':
            gen._safe_coerce_emit('int64_t', vt, elem64, cval_var)
        else:
            gen._emit(f"  {cval_var} = {elem64};")

    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1

    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)






def _gfd_flatten_target(gen, vn: str, acc: list) -> None:
    """Hoisted out of `_gen_for_dict` (recursive nested closure) — see
    `_gfl_declare_target_name`. `acc` (list) threaded and annotated."""
    if vn.startswith('(') and vn.endswith(')'):
        for _nv in gen._split_top_level_comma(vn[1:-1].strip()):
            _gfd_flatten_target(gen, _nv, acc)
    else:
        acc.append(vn)


def _gen_for_list(gen, var: str, it_val: str, body: list, shadow_name: str | None = None,
                   share_var_with_sibling_arm: bool = False):
    # Handle tuple unpacking: for (a, b) in list_of_tuples — and the 1-tuple
    # `for (a,) in ...`, which unpacks too. `for_target_is_tuple` is what says
    # so: a parenthesised single NAME (`for (a) in ...`) binds the whole item
    # and must NOT be unpacked, and the two spellings differ by exactly one
    # comma that the parser now keeps (fire_compiler.py's "Unpacking-target
    # representation"). Reading the parens alone treated both as unpack, so
    # `for (a,) in [(1,)]` printed `1` where CPython prints `(1,)`.
    is_tuple = gimple_ctypes.for_target_is_tuple(var)
    elem = None if is_tuple else gen._elem_of(it_val)
    if is_tuple:
        # Bracket-aware split (a naive `inner.split(',')` turned a nested
        # target like `(report_type, (old_mode, old_file))` into the bogus
        # name fragments `(old_mode` / `old_file)` — declared verbatim as
        # `int64_t (old_mode;` etc., hard C syntax errors; see
        # Lib/test/support/__init__.py's WindowsCleanup.__exit__).
        inner = var[1:-1].strip()
        var_names = gen._split_top_level_comma(inner)
        # A `*`-starred slot (`for first, *rest in ...`) binds the REMAINDER
        # as a LIST and shifts every slot after it, so it has to be found
        # BEFORE the declarations below decide what each slot is. See
        # `starred_slot_index` for why it is a position and not a name scan.
        star_idx = starred_slot_index(var_names)
        n_after = 0 if star_idx < 0 else len(var_names) - star_idx - 1
        # Declare each FLAT slot by its real per-slot element type, not a
        # blanket int64_t: _declare_var is deliberately first-decl-wins,
        # so pre-declaring int64_t here permanently locked every unpacked
        # target to int64_t before the per-slot analysis below (dict-
        # items key slot -> char*, etc.) ever ran — the body then saw
        # only a boxed pointer plus an _actual_types hint that not every
        # consumer consults (real: Apple/__main__.py's
        # `for slice_name, slice_parts in HOSTS[platform].items():`,
        # whose `CROSS_BUILD_DIR / slice_name` needs the key slot's real
        # char* at the `/` lowering). A nested parenthesized target is
        # not itself a variable — recurse so only its INNER names get
        # declared, as boxed int64_t (the body's nested-unpack recursion
        # assigns them from opaque boxed pairs, matching the pre-typed-
        # slots behavior for that shape).
        slot_elems = _tuple_unpack_slot_elems(gen, it_val, len(var_names))
        for _fli in range(len(var_names)):
            _fl_vn = _as_str(var_names[_fli])
            _fl_se = _as_str(slot_elems[_fli]) if _fli < len(slot_elems) else 'int64_t'
            if _fli == star_idx:
                # The starred slot holds a LIST OF the remaining elements,
                # so that is what it is declared as — and its element type
                # is recorded, because `print(rest)` must print `[2, 3]`
                # and not the pointer.
                _gfl_declare_target_name(gen, shadow_name,
                                         starred_slot_name(_fl_vn), 'MojoList *')
                if _fl_se and _fl_se != 'int64_t':
                    gen._elem_types[starred_slot_name(_fl_vn)] = _fl_se
                continue
            _gfl_declare_target_name(gen, shadow_name, _fl_vn, _fl_se)
    else:
        var_names = None
        _fl_ctype = _as_str(elem) if elem is not None else elem
        # Same rebind hazard `_gen_for_set` documents and fixes: a loop
        # TARGET is not a read of an existing name, so `_declare_var`'s
        # first-decl-wins default is wrong here -- `for x in [1, 2]:`
        # followed by `for x in ['p', 'q']:` REBINDS x, and int/str element
        # domains coerce to genuinely different C types. Where the set path
        # hits a `gcc -fgimple` type-mismatch error (loud), a list of ints
        # then a list of strs shares the SAME int64_t-shaped C declaration
        # (a `char *` slot just gets stored through as if it were an
        # int64_t, since a str list element is read via a different
        # accessor than an int one) and compiles clean but prints pointer
        # decimals for the second loop -- a SILENT wrong value, exit 0.
        #
        # EXCEPT when `share_var_with_sibling_arm` is set: the caller is one
        # runtime-dispatched ARM of a SINGLE source-level `for` loop over a
        # statically-unknown dict-or-list value (`_gen_for_iter`'s
        # mojo_is_registered_dict/_list dual dispatch, only one arm ever
        # actually runs) -- not two separate loops rebinding the same name.
        # That call site's own comment is explicit that BOTH arms MUST
        # declare the identical variable so the dead arm's declaration is
        # accepted rather than rejected as a conflicting type; retyping
        # here would rename the list arm's `x` to a fresh shadow variable
        # while the REST of the (already-lowered-once) loop body keeps
        # referencing the original bare name, silently reading garbage
        # (measured: `add(x, 10)` inside such a loop body kept reading the
        # pre-rename `x`, never the shadow copy -- a hard `gcc -fgimple`
        # "makes integer from pointer without a cast" once the arms'
        # element types actually differed, str key vs int64 element).
        _fl_retype = (not share_var_with_sibling_arm
                      and gen.var_types.get(var) not in (None, _fl_ctype))
        gen._declare_var(var, _fl_ctype, force=(var == shadow_name) or _fl_retype)
        # ...unless the iterated list records its OWN per-slot kinds, in which
        # case the target is the BOXED word `mojo_list_get_boxed` produces and
        # must be declared int64_t. A heterogeneous list's tracked element
        # type is its PROMOTED one — 'double' for `[1, 2.5]` — so declaring
        # that here is exactly what made `for y in [1, 2.5]` store a box (or
        # a small int) into a `double` variable and print 4311182544.0. The
        # variable is only *stored* as an int64_t here; the body's use of it
        # resolves the box (gen._boxed_vals).
        if (not share_var_with_sibling_arm
                and (it_val in getattr(gen, '_maybe_kinds_vals', ())
                     or _as_str(it_val) in getattr(gen, '_maybe_kinds_vals', ()))
                and gen.var_types.get(var) != 'int64_t'):
            gen._declare_var(var, 'int64_t', force=True)
        # AFTER every declaration above (each of which can re-type `var`) and
        # BEFORE the body is generated below, so a loop over `var` INSIDE the
        # body sees the inner element type. The doc's placement note.
        _carry_nested_elem_type(gen, var, it_val, _fl_ctype)
    len64 = gen._new_temp('int64_t')
    len_t = gen._new_temp('int64_t')
    idx_t = gen._new_temp('int64_t')
    # Cast it_val back to MojoList* if it's stored as int64_t (from method call)
    list_ptr = it_val
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        list_ptr = gen._coerce_to_type('int64_t', 'MojoList *', it_val)
    gen._emit(f"  {len64} = mojo_list_len ({list_ptr});")
    gen._emit(f"  {len_t} = {len64};")
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    if is_tuple:
        elem64 = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
        tuple_ptr = gen._coerce_to_type('int64_t', 'MojoList *', elem64)
        # Pick the accessor PER ELEMENT. The old branch read every slot
        # via mojo_list_get_str, which is right only for all-string pairs
        # — a dict.items() pair is [char* key, BOXED value] (the runtime
        # stores the value via append_int), so the boxed value slot read
        # as a string printed the char* pointer as a decimal address (the
        # self-hosted string pool emitted `static char * 35681302256`),
        # and the char* key was lost to a plain int64_t (print() used
        # %ld). dict-items keys are always strings; the value slot's type
        # comes from the dict's value type. Homogeneous tuple-literal
        # lists store every slot by the tuple's own element type
        # (_nested_elem_types). pair_elem is kept for the nested-target
        # recursion below; FLAT slot types come from slot_elems, resolved
        # once at the top of this function (same dict-items /
        # _tuple_slot_types / _nested_elem_types inputs — one computation
        # shared with the declarations there).
        pair_elem = gen._nested_elem_types.get(it_val, 'int64_t')

        def _emit_slot_read(ptr, i, slot_elem):
            suf_i = gimple_ctypes.TypeLattice.list_suffix(slot_elem)
            if suf_i == 'str':
                return 'char *', f"mojo_list_get_str ({_as_str(ptr)}, {i})"
            return 'int64_t', f"mojo_list_get_int ({_as_str(ptr)}, {i})"

        def _emit_target_assign(ptr, vn, i, slot_elem):
            """Assign slot `i` of the tuple at `ptr` to target name `vn` —
            which may itself be a parenthesized nested tuple target
            (`(old_mode, old_file)`), in which case the slot is read as an
            opaque boxed pair and recursively unpacked (one extra level is
            the realistic real-world shape; deeper nesting recurses
            identically)."""
            if vn.startswith('(') and vn.endswith(')'):
                rt, rv = _emit_slot_read(ptr, i, 'int64_t')
                nested_raw = gen._new_val(rt, rv)
                nested_ptr = gen._coerce_to_type(rt, 'MojoList *', nested_raw)
                nested_names = gen._split_top_level_comma(vn[1:-1].strip())
                for j, nn in enumerate(nested_names):
                    _emit_target_assign(nested_ptr, nn, j, pair_elem)
                return
            gen._declare_var(vn, slot_elem)
            cvn = gen._cname(vn)
            suf = gimple_ctypes.TypeLattice.list_suffix(slot_elem)
            vt = gen.var_types.get(vn, slot_elem)
            if suf == 'str':
                # `ptr` (this function's own PARAMETER), NOT the enclosing
                # `tuple_ptr` local: `_emit_target_assign` is a nested
                # closure, and the self-hosted backend's capture of
                # `tuple_ptr` came back NULL, so the slot read emitted
                # `mojo_list_get_str (0, 0)` instead of the real tuple
                # pointer — a real stage1-vs-stage2 `make bootstrap`
                # divergence (`bootstrap-validate.mojo`'s
                # `for path, base in sources:`).
                ts = gen._new_val('char *', f"mojo_list_get_str ({_as_str(ptr)}, {i})")
                if vt == 'char *':
                    gen._emit(f"  {cvn} = {ts};")
                else:
                    ip = gen._new_val('int64_t', f"(int64_t){ts}")
                    gen._emit(f"  {cvn} = {ip};")
                    # Recover the real string type on later reads (print(),
                    # f-strings, method args) — otherwise the char* boxed
                    # into the int64_t loop var reads as %ld (decimal addr).
                    gen._actual_types[vn] = 'char *'
            else:
                raw = gen._new_val('int64_t', f"mojo_list_get_int ({_as_str(ptr)}, {i})")
                if vt == 'int64_t':
                    gen._emit(f"  {cvn} = {raw};")
                else:
                    gen._safe_coerce_emit('int64_t', vt, raw, cvn)

        # A starred slot's own bounds, and the slots after it, depend on the
        # item's RUNTIME length (`a, *mid, z` over a 4-item row gives
        # `mid == [2, 3]`), so with a star in the target the length is read
        # once and the trailing slots are counted from its end. No star: the
        # indices stay the literal slot numbers they always were, so a
        # starless target's generated C is unchanged.
        item_len = None
        if star_idx >= 0:
            item_len = gen._new_val(
                'int64_t', f"mojo_list_len ({_as_str(tuple_ptr)})")

        for i, vn in enumerate(var_names):
            if i == star_idx:
                # `rest` gets everything from the star's position up to the
                # slot before the first slot after it — `mojo_list_len` minus
                # the number of trailing slots.
                stop = item_len
                if n_after:
                    _n = gen._new_val('int64_t', f"{n_after}LL")
                    stop = gen._new_val('int64_t', f"{item_len} - {_n}")
                _emit_starred_slot_list(gen, tuple_ptr,
                                        starred_slot_name(_as_str(vn)),
                                        f"{i}LL", stop, slot_elems[i])
                continue
            slot_i = i
            if star_idx >= 0 and i > star_idx:
                _base = gen._new_val('int64_t', f"{item_len} - {n_after}LL")
                _off = gen._new_val('int64_t', f"{i - star_idx - 1}LL")
                slot_i = gen._new_val('int64_t', f"{_base} + {_off}")
            if vn.startswith('(') and vn.endswith(')'):
                _emit_target_assign(tuple_ptr, vn, slot_i, 'int64_t')
                continue
            _emit_target_assign(tuple_ptr, vn, slot_i, slot_elems[i])
    else:
        cvar = gen._cname(var)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        # A list that records its OWN per-slot kinds (a `struct.unpack` of a
        # format that mixes int and float, a heterogeneous list literal) is
        # read through the runtime, which boxes a float slot so the loop
        # variable can BE a float instead of its raw IEEE-754 bits —
        # `for x in struct.unpack('<if', buf): print(x)` printed
        # 4607182418800017408 for 1.0, and `for y in [1, 2.5]` printed 1.0
        # for the int. Checked BEFORE the uniform-suffix branches on purpose:
        # a heterogeneous list's tracked element type is the promoted one
        # ('double' for `[1, 2.5]`), which is exactly the answer that is
        # wrong for its other slots. A list with no kinds of its own takes
        # the identical accessor it always did and yields the identical
        # word, so this costs only a set membership test at compile time.
        _mkv = (it_val in getattr(gen, '_maybe_kinds_vals', ())
                or list_ptr in getattr(gen, '_maybe_kinds_vals', ()))
        if _mkv:
            elem64 = gen._new_val('int64_t',
                                  f"mojo_list_get_boxed ({list_ptr}, {idx_t})")
            # The loop TARGET is a new name, not a read of an existing one,
            # so it is the cname that the print/str resolution is keyed on
            # (gen._boxed_vals).
            gen._boxed_vals.add(cvar)
            gen._emit(f"  {cvar} = (int64_t) {elem64};")
        elif suf == 'double':
            gen._emit(f"  {cvar} = mojo_list_get_double ({list_ptr}, {idx_t});")
        elif suf == 'str':
            # mojo_list_get_str returns char*, but var might be int64_t
            # Use a temp to handle the conversion
            temp_str = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
            # If var is int64_t, cast the char* to it; otherwise assign directly
            if gen._type_of(var) == 'char *':
                gen._emit(f"  {cvar} = {temp_str};")
            else:
                # Cast char* to int64_t (opaque pointer storage)
                int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
                gen._emit(f"  {cvar} = {int_ptr};")
        else:
            elem64 = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
            var_type = gen._type_of(var)
            if var_type != 'int64_t':
                gen._safe_coerce_emit('int64_t', var_type, elem64, cvar)
            else:
                # The loop var is (or was first declared as) a plain int64_t
                # box even when the list's tracked element type is a struct
                # pointer (e.g. `s` first used as an int64_t elsewhere, then
                # `for s in self._imported_typedef_structs` — _declare_var is
                # first-decl-wins). Casting to `(elem)` here — a struct
                # pointer — into an int64_t-typed var is a hard "makes
                # integer from pointer" error. Keep it boxed: the member
                # access on it goes through the runtime tag dispatch.
                gen._emit(f"  {cvar} = (int64_t) {elem64};")
    # `for item in <d.items()>:` binds ONE var to the whole [key, value]
    # pair — record it (with the dict's value type) so `item.key` /
    # `item.value` in the body read the right slot with the right
    # accessor instead of falling to the generic dynamic getattr. Scoped
    # to this loop body only, and restored after, so a same-named var in
    # an enclosing/sibling scope is unaffected.
    # No try/finally: a raise abandons the whole compile and this
    # GimpleGen instance (see gen_func's identical reasoning), and
    # try/except in a self-hosted method has broken this codegen's own
    # return-type inference before.
    _is_pair_var = (not is_tuple) and (it_val in gen._dict_items_val_elems)
    _had_pair = _is_pair_var and var in gen._dict_item_pair_vars
    _saved_pair = gen._dict_item_pair_vars.get(var, '')
    # The pair IS a 2-element `MojoList` — slot 0 the key (always a string;
    # `mojo_dict_items` appends it with append_str) and slot 1 the dict's own
    # value type — and the variable carried no evidence of that, so
    # `print(v)` / `str(v)` / an f-string reached the scalar `mojo_str_from_int`
    # path with a `MojoList *` in hand and printed the pair's HEAP ADDRESS: a
    # different decimal every run, which is also exactly what breaks
    # bootstrap's stage2-vs-stage3 byte-identity check. Recording the two slot
    # ctypes is the same evidence a tuple literal records, and it is what
    # routes the value to the kinds-aware `mojo_repr_list_kinds`. See
    # bugs/CODEGEN_dict_items_pair_valued_loop_var_prints_as_pointer.md.
    _pcv = gen._cname(var) if _is_pair_var else ''
    _saved_pc = ((gen._elem_types.get(_pcv),
                  gen._struct_slot_kinds.get(_pcv),
                  gen._actual_types.get(_pcv))
                 if _is_pair_var else None)
    # The pair IS a 2-element `MojoList` — slot 0 the key, slot 1 the dict's
    # own value type — and the variable carried no evidence of that, so
    # `print(v)` / `str(v)` / an f-string reached the scalar `mojo_str_from_int`
    # path with a `MojoList *` in hand and printed the pair's HEAP ADDRESS: a
    # different decimal every run, which is also exactly what breaks
    # bootstrap's stage2-vs-stage3 byte-identity check. Recording the two slot
    # ctypes is the same evidence a tuple literal records, and it is what
    # routes the value to the kinds-aware `mojo_repr_list_kinds`. See
    # bugs/CODEGEN_dict_items_pair_valued_loop_var_prints_as_pointer.md.
    #
    # STR-KEYED dicts only. An Int-keyed dict's pair slot 0 is an integer word,
    # so both slots come out `'int'` and `_struct_slot_kind_bytes` declines a
    # UNIFORM kind row by design (a uniform `struct.unpack` format is already
    # exact under its uniform helper; a pair is not, and that uniform case is
    # a separate piece of missing evidence — the same one `v.value` on a
    # container-valued dict needs).
    _pair_str_keyed = _is_pair_var and it_val not in gen._dict_items_int_keys
    if _is_pair_var:
        gen._dict_item_pair_vars[var] = gen._dict_items_val_elems[it_val]
    if _pair_str_keyed:
        gen._elem_types[_pcv] = 'MojoList *'
        gen._struct_slot_kinds[_pcv] = ['str', _gmi_slot_kind_long(
            gen._dict_items_val_elems[it_val])]
        # The loop variable is declared `int64_t` and holds the pair's handle,
        # so `print`'s boxed-int64 arm has to be told what the box holds —
        # `_get_actual_type` reads this table and it is what turns that arm
        # into the list-repr route.
        gen._actual_types[_pcv] = 'MojoList *'
    # `item.key` reads slot 0 as an integer when the pairs came from an
    # Int-keyed dict; scoped to the body like the pair var itself.
    _int_pair = _is_pair_var and it_val in gen._dict_items_int_keys
    _had_int_pair = var in gen._dict_item_int_key_vars
    if _int_pair:
        gen._dict_item_int_key_vars.add(var)
    else:
        gen._dict_item_int_key_vars.discard(var)
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    if _is_pair_var:
        if _had_pair:
            gen._dict_item_pair_vars[var] = _saved_pair
        else:
            gen._dict_item_pair_vars.pop(var, None)
    if _pair_str_keyed:
        # Same scoping discipline as the pair-var registration above: these
        # three describe THIS loop's target, and a same-named variable in an
        # enclosing or sibling scope is a different value.
        for _tbl, _k, _v in ((gen._elem_types, _pcv, _saved_pc[0]),
                             (gen._struct_slot_kinds, _pcv, _saved_pc[1]),
                             (gen._actual_types, _pcv, _saved_pc[2])):
            if _v is None:
                _tbl.pop(_k, None)
            else:
                _tbl[_k] = _v
    if _had_int_pair:
        gen._dict_item_int_key_vars.add(var)
    else:
        gen._dict_item_int_key_vars.discard(var)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_str(gen, var: str, it_val: str, body: list, shadow_name: str | None = None):
    gen._declare_var(var, 'char', force=(var == shadow_name))
    len64 = gen._new_temp('int64_t')
    len_t = gen._new_temp('int64_t')
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {len64} = mojo_str_len ({it_val});")
    gen._emit(f"  {len_t} = {len64};")
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen._emit(f"  {gen._cname(var)} = mojo_str_char_at ({it_val}, {idx_t});")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_bytes(gen, var: str, it_val: str, body: list):
    """`for x in b:` where `b` is a `MojoBytes *` — x is an int 0-255.
    Mirrors _gen_for_cstr's index-loop shape over mojo_bytes_len/_get."""
    gen._declare_var(var, 'int64_t')
    len_t = gen._new_val('int64_t', f"mojo_bytes_len ({it_val})")
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    byte_t = gen._new_val('int64_t', f"mojo_bytes_get ({it_val}, {idx_t})")
    gen._emit(f"  {gen._cname(var)} = {byte_t};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_memoryview(gen, var: str, it_val: str, body: list):
    """`for x in mv:` — x is an int (1-D byte view). Same index-loop shape
    as _gen_for_bytes over mojo_memoryview_len/_get."""
    gen._declare_var(var, 'int64_t')
    len_t = gen._new_val('int64_t', f"mojo_memoryview_len ({it_val})")
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    byte_t = gen._new_val('int64_t', f"mojo_memoryview_get ({it_val}, {idx_t})")
    gen._emit(f"  {gen._cname(var)} = {byte_t};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_cstr(gen, var: str, it_val: str, body: list):
    """`for c in s:` where `s` is a plain `char *` (this codegen's usual
    representation for an ordinary Python str local — MojoStr* is a
    separate, less common wrapped-string type _gen_for_str already
    handles). Was COMPLETELY UNSUPPORTED: no `it_type == 'char *'`
    branch existed anywhere in _gen_for_iter's dispatch, so any such
    loop silently fell through to the generic "unsupported iterable"
    fallback (mojo_unsupported_iter — the body runs ZERO times, no
    error). A striking real consequence: fire_compiler.py's own
    `_process_nested_tstrings` computes `needs_brace_aware_scan =
    any(c in ('t','T','f','F') for c in prefix)` — a generator
    expression over exactly this shape — which therefore ALWAYS
    evaluated empty/False once self-hosted, so every self-hosted-
    compiled f/t-string permanently took the "ordinary string" plain-
    scan fallback instead of the intended brace-aware placeholder
    path. That fallback still extracts the right CONTENT (found while
    chasing make bootstrap's verify byte-identity failures: the
    f-string prefix-doubling bug turned out to be `del`'s own
    unimplemented-DelStmt gap, unrelated to this one) but skips the
    placeholder substitution entirely, so every token's `col` after an
    f/t-string in a self-hosted-compiled dump was computed against the
    literal's real (longer) length instead of the short placeholder's,
    permanently diverging from the interpreted stage1 dump's columns.
    Mirrors _gen_for_str's identical index-loop shape, just over
    mojo_strlen/_mojo_at_char instead of mojo_str_len/mojo_str_char_at.
    """
    # The target is a ONE-CHARACTER STRING, not a character code. Python
    # iterates a str into strs, so `for c in s` binds `c` to `'a'`, and
    # every real use of it treats it as one: `c in "aeiou"`, `c == " "`,
    # `d[c] = i`, `"".join(...)`, `c.upper()`. Declaring the target `char`
    # and assigning the raw code made all of those compare/print a NUMBER
    # — `set("hello world")` came back as [32, 100, 101, ...] and a
    # `sorted(set(text))` vocab keyed by integer codes stopped matching the
    # strings a later `text` iteration produced, so `c not in stoi` raised
    # KeyError for characters that were demonstrably in the vocab.
    # `mojo_char_to_str` is the existing 1-char-C-string helper; using it
    # also fixes the f-string-prefix case this loop was added for
    # (`any(c in ('t','T','f','F') for c in prefix)`), which compares the
    # target against 1-char STRING literals and so could never match a
    # code.
    gen._declare_var(var, 'char *')
    len_t = gen._new_val('int64_t', f"mojo_strlen ({it_val})")
    idx_t = gen._new_temp('int64_t')
    gen._emit(f"  {idx_t} = (int64_t)0;")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx_t} < {len_t}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    # `mojo_char_at_str(s, i)` rather than
    # `mojo_char_to_str(*_mojo_at_char(s, i))`: gimple REFUSES a `char`-typed
    # argument ("invalid argument to gimple call" / "non-trivial conversion in
    # 'integer_cst'") because a char is promoted to int64_t and the conversion
    # is not trivial to it, so the two-step spelling is not available at all.
    # `mojo_cstr_slice(s, i, i+1)` was the workaround that did lower — and it
    # allocated a 1-char string per character that nobody freed, which was the
    # whole of the char-scan residual (1226 bytes a pass, measured).
    # The helper takes a pointer and an index instead, so it lowers cleanly AND
    # lands in the immortal table `mojo_char_to_str` already keeps. As above,
    # no `_mojo_at_char` is requested: the helper is not called from here.
    gen._emit(f"  {gen._cname(var)} = mojo_char_at_str ({it_val}, {idx_t});")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_dict(gen, var: str, it_val: str, body: list, shadow_name: str | None = None,
                  int_keys: bool = False):
    """for k in dict — iterates over keys as char *."""
    # Handle tuple target like '(name, alias)' — declare each name
    # separately. `for_target_is_tuple`, so the 1-tuple `for (k,) in d.items()`
    # unpacks and the parenthesised single name `for (k) in d` does not; see
    # _gen_for_list's note.
    is_tuple = gimple_ctypes.for_target_is_tuple(var)
    if is_tuple:
        inner = var[1:-1].strip()
        var_names = gen._split_top_level_comma(inner)
        # `for k, *rest in <dict>` unpacks the KEY STRING — Python says
        # `for a, *b in {"xy": 1}` gives `a == 'x'`, `b == ['y']` — and the
        # slots of a dict loop here are not slots of a shared row at all
        # (slot 0 is the key; every later slot is the literal 0, this
        # lowering's stand-in for a pair's value). There is no row to slice a
        # remainder out of, so this REFUSES at runtime through the standard
        # mechanism (`_emit_unsupported_iter`: loud, and not a silently
        # dropped body) rather than emitting the store through a pointer
        # named `*rest` — which is a write through an UNINITIALISED pointer,
        # i.e. a wild store that happens to be mapped.
        #
        # A refusal and not a lowering, because the two engines disagree on
        # this shape already and only one of them can be moved here: the
        # interpreter binds the WHOLE key (`for k, *vs in d` prints
        # `abc []` where CPython prints `a ['b', 'c']` — see
        # bugs/RUNTIME_starred_for_target_over_a_dict_key_is_not_unpacked.md),
        # so implementing CPython's reading here would make the compiled path
        # disagree with the interpreter it falls back to, which is the one
        # comparison this project can actually check.
        if starred_slot_index(var_names) >= 0:
            _emit_unsupported_iter(gen, 'dict')
            return
        # Flatten any nested tuple target the same way _gen_for_list does
        # (a naive split turned `(k, (a, b))` into the bogus fragments
        # `(a` / `b)`, declared verbatim — hard C syntax errors).
        _flat = []
        for vn in var_names:
            _gfd_flatten_target(gen, vn, _flat)
        var_names = _flat
        # First var is the KEY (char*); the rest are value slots, always
        # 0/NULL in this runtime's dict-key iteration. Declare the value
        # slots int64_t (not char*) so a sibling list-iteration branch over
        # the same variable (e.g. the runtime-dispatch `for name, func in
        # self.funcs:` where funcs is really a list of (name, fnptr)
        # tuples) isn't first-decl-wins'd into char* — that made a
        # function-pointer slot read as a string and `func(...)` compile to
        # a bogus direct call.
        # Record the C type each slot ACTUALLY ended up declared as.
        # `_declare_var` is first-decl-wins, so a slot may keep a type an
        # earlier declaration chose rather than the one requested here —
        # and the assignment code below used to re-derive the type with
        # `gen.var_types.get(vn, 'char *')`, whose *default* contradicts
        # the `int64_t` requested for every non-key slot. When the name was
        # missing from `var_types` that default won and emitted
        # `vtype = (char *)0;` into an `int64_t vtype;` declaration — a
        # hard -Wint-conversion error (real: gimple_gen_funcs.py's
        # `for vname, vtype in ci.captures:`).
        _slot_ctypes = []
        for i, vn in enumerate(var_names):
            _want = ('int64_t' if int_keys else 'char *') if i == 0 else 'int64_t'
            _retype = (int_keys and i == 0 and gen.var_types.get(vn, _want) != _want) \
                or (not int_keys and i == 0 and vn in gen._int_key_loop_vars)
            gen._declare_var(vn, _want, force=(vn == shadow_name) or _retype)
            if i == 0:
                if int_keys:
                    gen._int_key_loop_vars.add(vn)
                else:
                    gen._int_key_loop_vars.discard(vn)
            _slot_ctypes.append(gen.var_types.get(vn, _want))
    elif int_keys:
        # The key is an integer: retype a name an earlier loop declared as a
        # string rather than let first-decl-wins keep the pointer type.
        gen._declare_var(var, 'int64_t', force=(var == shadow_name)
                         or gen.var_types.get(var, 'int64_t') != 'int64_t')
        gen._int_key_loop_vars.add(var)
    else:
        # ...and the reverse: a name an Int-keyed loop declared int64_t must
        # become a string again, not box the string pointer into an integer.
        gen._declare_var(var, 'char *', force=(var == shadow_name)
                         or var in gen._int_key_loop_vars)
        gen._int_key_loop_vars.discard(var)
    # If it_val is int64_t (boxed pointer), cast to MojoDict *
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        it_val = gen._coerce_to_type('int64_t', 'MojoDict *', it_val)
    iter_t = gen._new_temp('MojoDictIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_dict_iter_new ({it_val});")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    if int_keys:
        ikey_tmp = gen._new_val('int64_t', f"mojo_dict_iter_key_int ({iter_t})")
        if is_tuple:
            gen._emit(f"  {gen._cname(var_names[0])} = {ikey_tmp};")
            for _vi in range(1, len(var_names)):
                _vt = _slot_ctypes[_vi]
                if _vt in ('int64_t', 'int', 'int32_t'):
                    gen._emit(f"  {gen._cname(var_names[_vi])} = (int64_t)0;")
                elif _vt.endswith(' *'):
                    gen._emit(f"  {gen._cname(var_names[_vi])} = ({_vt})0;")
                else:
                    gen._emit(f"  {gen._cname(var_names[_vi])} = (char *)0;")
        else:
            gen._emit(f"  {gen._cname(var)} = {ikey_tmp};")
        key_tmp = None
    else:
        key_tmp = gen._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
    # Every write goes through _cname: a loop variable whose Mojo name is a
    # C keyword (`for char in s.codepoints():` — real, in stdlib's
    # _unicode.mojo) is DECLARED as the renamed `_char` by _declare_var,
    # and every read already resolves through _cname, but these writes used
    # the raw name and emitted `char = (char *) _t10;` — a hard "expected
    # expression before 'char'" parse error. Latent until the boxed
    # dict/list runtime dispatch (A5-BUG.md §1) started generating this
    # branch for real; _gen_for_list has always done this correctly.
    if int_keys:
        pass    # the integer key was stored above
    elif is_tuple:
        # Assign key to first name, NULL (zero) to remaining names
        vn0 = var_names[0]
        cvn0 = gen._cname(vn0)
        # `_slot_ctypes`, not a fresh `var_types.get(..., 'char *')`: the
        # store must use the type the slot was actually DECLARED with (see
        # where _slot_ctypes is built).
        vt0 = _slot_ctypes[0]
        if vt0 in ('int64_t', 'int', 'int32_t'):
            vp = gen._new_val('void *', f'(void *){key_tmp}')
            box = gen._new_val('int64_t', f'(int64_t){vp}')
            gen._emit(f"  {cvn0} = {box};")
        else:
            gen._emit(f"  {cvn0} = (char *) {key_tmp};")
        for _vi in range(1, len(var_names)):
            vn = var_names[_vi]
            cvn = gen._cname(vn)
            vt = _slot_ctypes[_vi]
            if vt in ('int64_t', 'int', 'int32_t'):
                gen._emit(f"  {cvn} = (int64_t)0;")
            elif vt.endswith(' *'):
                gen._emit(f"  {cvn} = ({vt})0;")
            else:
                gen._emit(f"  {cvn} = (char *)0;")
    else:
        cvar = gen._cname(var)
        vt = gen.var_types.get(var, 'char *')
        if vt in ('int64_t', 'int', 'int32_t'):
            vp = gen._new_val('void *', f'(void *){key_tmp}')
            box = gen._new_val('int64_t', f'(int64_t){vp}')
            gen._emit(f"  {cvar} = {box};")
        else:
            gen._emit(f"  {cvar} = (char *) {key_tmp};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_dict_iter_free ({iter_t});")


def _gen_for_set(gen, var: str, it_val: str, body: list, shadow_name: str | None = None):
    """for x in set — iterates over the set's ELEMENT values.

    The element C type comes from the set's recorded element type, because
    the three domains really are stored differently: int slots hold a bare
    int64_t, str slots a `char *` (tag 1), and bytes slots a
    NUL-terminated content copy (tag 2) that only `mojo_set_val_bytes`
    turns back into a real MojoBytes value. Reading every domain through
    `mojo_set_iter_val_int` gives pointer bits for the two pointer
    domains, which is what a set of strings/bytes used to iterate as."""
    _se = gen._elem_of(it_val) or 'int64_t'
    if _se == 'MojoBytes *':
        _loop_ctype, _read = 'MojoBytes *', 'mojo_set_val_bytes'
    elif _se == 'char *':
        _loop_ctype, _read = 'char *', 'mojo_set_iter_val_str'
    else:
        _loop_ctype, _read = 'int64_t', 'mojo_set_iter_val_int'
    # `_declare_var` is first-decl-wins (load-bearing for every OTHER
    # caller: later reads of a name must keep coercing to the type it was
    # first given), but a loop target is not a read of an existing name —
    # `for x in <A>` followed by `for x in <B>` REBINDS x, and if A and B
    # have different element domains the second loop wrote a char* into
    # the first loop's MojoBytes * target: gcc -fgimple rejects that as
    # `assignment to 'MojoBytes *' from incompatible pointer type 'char *'`
    # and the whole program fails to compile. It is not a bytes/set
    # peculiarity — `for x in {1,2}` then `for x in {'p','q'}` fails the
    # same way — it is the loop TARGET's type being pinned per function.
    # force=True mints a fresh C name and repoints `_c_names[var]` at it,
    # which is also the correct Python reading: after the second loop, x
    # holds the second loop's last element.
    _retype = gen.var_types.get(var) not in (None, _loop_ctype)
    gen._declare_var(var, _loop_ctype, force=(var == shadow_name) or _retype)
    # If it_val is int64_t (boxed pointer), cast to MojoSet * (matches dict path)
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        it_val = gen._coerce_to_type('int64_t', 'MojoSet *', it_val)
    iter_t = gen._new_temp('MojoSetIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_set_iter_new ({it_val});")

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    if _read == 'mojo_set_val_bytes':
        _slot = gen._new_temp('int64_t')
        gen._emit(f"  {_slot} = mojo_set_iter_pos ({iter_t});")
        gen._emit(f"  {gen._cname(var)} = mojo_set_val_bytes ({it_val}, {_slot});")
    else:
        gen._emit(f"  {gen._cname(var)} = {_read} ({iter_t});")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_set_iter_free ({iter_t});")


def _gen_lifted_closure(gen, ci, outer_name: str = None) -> str:
    # `ci` deliberately UNANNOTATED: a `gimple_solvers.ClosureInfo`
    # qualified annotation doesn't resolve for the self-hosted backend
    # (it stayed `int64_t`, so every `ci.env_struct` / `ci.captures` /
    # `ci.inner_def` read went through boxed dynamic getattr and the
    # capture env was silently dropped). Left bare, usage-based inference
    # types it `ClosureInfo *` exactly as it already does for
    # `_lower_outer_closure_call` / `_emit_closure_recursive`.
    """Generate a top-level C function for a nested (closure) function."""
    gen._reset_func(ci.inner_def.body, ci.inner_def.params)
    # Set module context for global field access -- same fix, same reason
    # as _gen_struct_method's identical line just above: a lifted closure
    # is emitted BEFORE its owning gen_func/_gen_struct_method call sets
    # this (see the `_emit_closure_recursive(...)` loops in gen_module,
    # which always run ahead of the owning function's own gen_func/
    # _gen_struct_method call), so a closure that is the very FIRST thing
    # processed for a fresh per-module GimpleGen instance would otherwise
    # see the "" __init__ default (read as "root" downstream) instead of
    # this module's real name.
    gen._current_module_ctx = gen.module_name if len(gen.module_name) > 0 else "root"
    # Per-lexical-scope import tracking: a lifted closure body is its own
    # lexical scope (its own local `from X import ...` statements shadow
    # the enclosing function's / module's same-named bindings).
    _closure_scope = gen._push_import_scope()
    gen._collect_body_import_bindings(ci.inner_def.body, _closure_scope)
    gen.current_func_name = ci.lifted_name
    gen._captures  = dict(ci.captures)
    gen._env_param = '_env' if ci.env_struct else ''
    gen._gimple_mut_ptr = {}  # mut-captured name -> preloaded local pointer temp (set below)
    gen._inner_func_name = ci.inner_def.name  # original name for recursive call detection

    # Expose sibling closures (other nested `def`s in the same enclosing
    # scope) so a call from THIS closure's body to one of them resolves to
    # the real lifted C name instead of falling through to a bare,
    # never-declared call. `_lower_call`'s existing `_lambda_outer_closures`
    # lookup (previously populated only for lifted lambdas calling an outer
    # function's other nested defs) already handles exactly this shape —
    # reused here rather than adding a parallel mechanism. Real bug found
    # via gimple_codegen.py's own `_register_imported_structs`, whose nested
    # `_collect` calls its sibling `_base`: the call site emitted a bare
    # `_base (...)` with no declaration anywhere, an undefined symbol at
    # link time (this method's own body only gets compiled at all once the
    # 552-line-stub / local-global-collision bug above was fixed, since
    # only then does the self-hosted closure reach this far).
    if outer_name:
        gen._lambda_outer_closures = dict(gen._all_closures.get(outer_name, {}))

    node = ci.inner_def
    # Infer parameter types from usage before seeding var_types
    inferred_params = gen._infer_param_types(node)
    # A lambda's own default-value params (`lambda e, self=self: ...`,
    # the standard tkinter-callback idiom for binding an outer-scope
    # value without relying on closures) are lifted as ordinary formal
    # params of a *synthetic* FunctionDef with no type annotations
    # (_lower_LambdaExpr strips defaults before calling here) — so for
    # a lambda specifically (env_struct=='': _lower_LambdaExpr never
    # sets one) `ci.captures` holds the REAL ctype _lower_LambdaExpr
    # already resolved for each such param from the ENCLOSING
    # function's live var_types (e.g. `self` -> `TkTestRunner *`),
    # which is far more reliable than usage-based inference on the
    # synthetic, out-of-context body below. Prefer it over
    # `inferred_params`/`_resolve_type(None)` so the forward
    # declaration _lower_LambdaExpr emits (built from that SAME
    # ci.captures-sourced param_ctypes list) matches this function's
    # real definition -- previously it didn't (ci.captures was
    # unconditionally passed as `[]`, discarding the correctly-typed
    # list _lower_LambdaExpr had just computed), a forward-decl-vs-
    # definition ctype mismatch ("conflicting types") once two such
    # lambdas existed in the same translation unit (real repro: Tools/
    # unittestgui/unittestgui.py's `errorListbox.bind("<Double-1>",
    # lambda e, self=self: self.showSelectedError())`). Scoped to
    # `not ci.env_struct` so a real (env-struct-based) nested closure's
    # OWN declared params, which can legitimately share a name with an
    # outer captured variable via shadowing, are unaffected -- those
    # still resolve their param type the normal way below.
    _lambda_capture_types = dict(ci.captures) if not ci.env_struct else {}
    # The call site's own answer for this function's parameters (a lambda
    # handed to `map`/`filter`/`sorted(key=)`, whose element type the call
    # site resolved and bound to the lambda's param names). A FALLBACK, not
    # an override: the body's usage evidence above is the primary answer and
    # this only fills in for a parameter it says nothing about, which is the
    # case that used to default to `int64_t` and turn a real string argument
    # into a decimal address (`sorted(names, key=lambda s: k3(s))` — see
    # `ci.call_site_param_types`'s own comment).
    _call_site_types = dict(ci.call_site_param_types) if not ci.env_struct else {}
    for pname, ptype in node.params:
        if pname in _lambda_capture_types:
            gen.var_types[pname] = _lambda_capture_types[pname]
        elif ptype is None and pname in inferred_params:
            gen.var_types[pname] = inferred_params[pname]
        elif ptype is None and pname in _call_site_types:
            gen.var_types[pname] = _call_site_types[pname]
        else:
            gen.var_types[pname] = gen._resolve_type(ptype)

    # Seed captured variables into var_types so that calls to captured
    # function-pointer parameters (e.g. cmp_fn captured from outer scope)
    # are recognised by the indirect-call guard in _lower_call.  The
    # actual value is read via _env->name in _lower_IdentExpr, but the
    # type must be visible here so the call-site path is taken.
    for cap_name, cap_type in ci.captures:
        if cap_name not in gen.var_types:
            gen.var_types[cap_name] = cap_type

    # re.sub callbacks: force match param to char * and return type to char *
    if ci.is_re_sub_callback and node.params:
        match_param = node.params[0][0]
        gen.var_types[match_param] = 'char *'

    if node.return_type is not None:
        ret_type = gen._resolve_type(node.return_type)
    else:
        ret_type = gen._infer_return_type(node.body)
    if ci.is_re_sub_callback:
        ret_type = 'char *'
    gen.func_ret_type = ret_type

    # Build parameter list (env pointer first, then actual params)
    param_strs = []
    if ci.env_struct:
        param_strs.append(f"{ci.env_struct} * _env")
    ci.inferred_params = {}
    seen_varargs = False
    for i, (pname, ptype) in enumerate(node.params):
        # Strip Mojo parameter modifiers (inout, borrowed, etc.)
        bare = gimple_ctypes._strip_mojo_param_modifiers(pname.lstrip('*'))
        if pname.startswith('**'):
            # **kwargs -> a real MojoDict* param (forwarding pattern)
            ctype = 'MojoDict *'
            gen.var_types[bare] = ctype
            ci.inferred_params[pname] = ctype
            param_strs.append(f"{ctype} {bare}")
            continue
        if pname.startswith('*'):
            # *args -> one MojoList* param; callers pack the loose args into it
            if seen_varargs:
                continue
            seen_varargs = True
            ctype = 'MojoList *'
            gen.var_types[bare] = ctype
            ci.inferred_params[pname] = ctype
            param_strs.append(f"{ctype} {bare}")
            continue
        if ci.is_re_sub_callback and i == 0:
            # First (match) param is always char * for re.sub callbacks
            ctype = 'char *'
        elif pname in _lambda_capture_types:
            # Same ci.captures-sourced type used to seed var_types
            # above (and to build the forward declaration in
            # _lower_LambdaExpr) — this second, independent ctype
            # computation for the REAL definition's param_strs must
            # agree with it too, or the forward decl and definition
            # mismatch exactly like the bug this whole capture-priority
            # mechanism exists to fix (see the comment above the
            # `_lambda_capture_types` assignment).
            ctype = _lambda_capture_types[pname]
        elif ptype is None and pname in inferred_params:
            ctype = inferred_params[pname]
        elif ptype is None and pname in _call_site_types:
            # Same fallback as the var_types seeding above, and it must be
            # the same answer: this loop is what DECLARES the parameter, so
            # a disagreement with the body would be a definition whose own
            # `var_types` seed contradicts its signature.
            ctype = _call_site_types[pname]
        else:
            ctype = gen._param_ctype(pname, ptype, node)
        gen.var_types[pname] = ctype
        ci.inferred_params[pname] = ctype   # cache for forward decl in Phase 2b
        # Rename C keywords / struct-typedef-colliding names used as
        # parameter names (e.g. 'default', 'asm', or a struct-name shadow
        # like `A` — see `_param_safe_name`'s own docstring).
        safe_bare = gen._param_safe_name(bare)
        if safe_bare != bare:
            gen._c_names[bare] = safe_bare
            gen.var_types[bare] = ctype
        param_strs.append(f"{ctype} {safe_bare}")
    ci.inferred_ret = ret_type               # cache for forward decl in Phase 2b
    # Update func_return_types so callers generated after this closure see the right type
    gen.func_return_types[ci.lifted_name] = ret_type
    # Register param types so _emit_call can coerce/pack arguments at closure call
    # sites. Keep the usage-inferred type for normal params; for *args use the '...'
    # packing sentinel (or a concrete MojoList* when **kwargs is also present), and
    # **kwargs -> MojoDict*, matching the emitted params above.
    closure_param_ctypes = []
    if ci.env_struct:
        closure_param_ctypes.append(f"{ci.env_struct} *")
    _has_kw = any(pn.startswith('**') for pn, _ in node.params)
    for pname, _ in node.params:
        if pname.startswith('**'):
            closure_param_ctypes.append('MojoDict *')
        elif pname.startswith('*'):
            closure_param_ctypes.append('MojoList *' if _has_kw else '...')
            if not _has_kw:
                break
        else:
            closure_param_ctypes.append(ci.inferred_params.get(pname, 'int64_t'))
    gen.func_param_types[ci.lifted_name] = closure_param_ctypes
    params_str = ', '.join(param_strs) if param_strs else 'void'

    # A doubly-nested closure's by-reference captures live in ITS OWN parent —
    # this lifted function — so the boxing setup `gen_func` does for a
    # top-level function has to be done here too, keyed by `ci.lifted_name`
    # (which is exactly how `discover_closures` keys this function's own
    # nested defs). Without it a `{mut x}` capture two levels down declared
    # `x` as an ordinary scalar, and the env-fill then assigned that scalar to
    # an `int64_t *` field: "non-trivial conversion in 'var_decl'"
    # (benchmarks/memory/bench_heap_parallel's `call_fn` -> `task_body`
    # -> `{mut checksum}`). Same three calls, same order, as `gen_func`:
    # seed the boxed-pointer declarations, seed the address-taken locals, then
    # allocate each box once in the prologue.
    gen._seed_mut_captured_local_types(ci.lifted_name)
    gen._seed_addressed_locals(node.body)
    gen._emit_mut_local_box_allocs()

    gen._emit_label("bb_2")
    # `{mut}`-capture-spec names (ClosureInfo.mut_names): the env
    # struct field is a POINTER (see the struct-typedef emission's own
    # `field_ctype` widening). GIMPLE forbids dereferencing a compound
    # expression like `_env->name` directly (the same "component_ref
    # can't be used directly" restriction the by-value path already
    # works around by loading into a temp first) -- load the pointer
    # into a plain local ONCE here, then every read/write in the body
    # (`_lower_IdentExpr`/`_write_dest`) dereferences that simple local
    # instead, which GIMPLE does allow (mirrors the existing `*{temp}`
    # pattern used throughout this file, e.g. UnsafePointer derefs).
    for _mn in sorted(ci.mut_names):
        if _mn in gen._captures:
            _ptr_ctype = f"{gen._captures[_mn]} *"
            _ptr_var = f"_mutptr_{_mn}"
            gen._declare_var(_ptr_var, _ptr_ctype)
            gen._emit(f"  {_ptr_var} = {gen._env_param}->{gimple_ctypes._c_field_name(_mn)};")
            gen._gimple_mut_ptr[_mn] = _ptr_var
    for stmt in node.body:
        gen.gen_stmt(stmt)

    # See _reset_func's own comment on `_func_used_setjmp` /
    # _gen_struct_method's identical handling just above -- a lifted
    # closure whose OWN body emitted a real setjmp must not be tagged
    # `__GIMPLE` either, for the same reason.
    _sig_kw = '' if gen._func_used_setjmp else '__GIMPLE '
    lines = [
        f"{ret_type} {_sig_kw}{ci.lifted_name} ({params_str})",
        "{",
        *gen.decls,
        *gen.body_lines,
        "}",
    ]
    gen._captures  = {}
    gen._env_param = ''
    gen._gimple_mut_ptr = {}
    gen._lambda_outer_closures = {}
    gen._pop_import_scope()
    return '\n'.join(lines)


def _emit_generator_tuple_unpack(gen, var_names: list, slot_types: list, list_ptr: str,
                                 nested_flags: list | None = None) -> None:
    """Unpacks a boxed-tuple `MojoList *` (produced by a tuple-yielding
    compiled generator's `_cpp_yield_tuple` boxing — see that method's
    docstring for the producer side) into `var_names`, one runtime
    accessor call per slot, using the generator's own statically-
    unified per-slot type list (`slot_types`, from
    `_generator_api[...]['tuple_slot_ctypes']` —
    see `_generator_tuple_yield_slot_ctypes`). Shared by every
    compiled-generator tuple-target `for` consumer
    (`_gen_for_generator_iter`/`_compr_generator_loop`) so the two
    can't silently diverge on how a boxed tuple is read back apart.

    Mirrors `_gen_for_list`'s existing `for (a, b) in <list-of-
    tuples>:` per-slot accessor dispatch (int/double/str, chosen via
    TypeLattice.list_suffix) — kept as its OWN narrow helper rather
    than merged into that method's inline tuple-unpack block, since
    `_gen_for_list`'s is_tuple branch carries additional
    dict.items()-specific "slot 0 is always the string key" logic
    that has no equivalent here: a compiled generator's tuple yield
    has no such convention, every slot's type comes straight from
    `slot_types`."""
    for i, vn in enumerate(var_names):
        slot_elem = slot_types[i] if i < len(slot_types) else 'int64_t'
        # A slot that is a nested tuple: read the boxed pointer and mark the
        # local as a TAGGED nested tuple, so a later `a, b = <vn>` unpack
        # reads its elements via `mojo_tagged_*` (see the tagged-unpack path
        # in stmts_shared._assign_target / emit_stmts' tuple-target branch),
        # not as a plain list of int64 slots.
        if nested_flags and i < len(nested_flags) and nested_flags[i]:
            gen._declare_var(vn, 'MojoList *')
            cvn = gen._cname(vn)
            pv = gen._coerce_to_type(
                'int64_t', 'MojoList *',
                gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {i})"))
            gen._emit(f"  {cvn} = {pv};")
            if not hasattr(gen, '_tagged_gen_tuple_locals'):
                gen._tagged_gen_tuple_locals = set()
            gen._tagged_gen_tuple_locals.add(vn)
            continue
        gen._declare_var(vn, slot_elem)
        cvn = gen._cname(vn)
        suf = gimple_ctypes.TypeLattice.list_suffix(slot_elem)
        vt = gen.var_types.get(vn, slot_elem)
        if suf == 'str':
            ts = gen._new_val('char *', f"mojo_list_get_str ({list_ptr}, {i})")
            if vt == 'char *':
                gen._emit(f"  {cvn} = {ts};")
            else:
                ip = gen._new_val('int64_t', f"(int64_t){ts}")
                gen._emit(f"  {cvn} = {ip};")
                # Recover the real string type on later reads (print(),
                # f-strings, method args) — mirrors _gen_for_list's
                # identical fixup for the same "boxed into an int64_t
                # var" situation.
                gen._actual_types[vn] = 'char *'
        elif suf == 'double':
            dv = gen._new_val('double', f"mojo_list_get_double ({list_ptr}, {i})")
            if vt == 'double':
                gen._emit(f"  {cvn} = {dv};")
            else:
                gen._safe_coerce_emit('double', vt, dv, cvn)
        else:
            raw = gen._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {i})")
            if vt == 'int64_t':
                gen._emit(f"  {cvn} = {raw};")
            else:
                gen._safe_coerce_emit('int64_t', vt, raw, cvn)


def _gen_for_generator_iter(gen, var: str, gen_val: str, api: dict, body: list,
                            destroy_after: bool = True):
    """for x in <supported generator call>(): ... — <base>_resume()/
    <base>_value() deliberately mirror _gen_for_struct_iter's existing
    __has_next__/__next__ convention immediately below (resume both
    advances the coroutine to its next co_yield/completion AND reports
    whether one was produced; value reads the most recently produced
    one without advancing) — the established "returns 2 things" scheme
    this codegen already uses for iteration, reused rather than
    invented fresh for generators.

    `destroy_after`: whether to call <base>_destroy() once the loop is
    fully drained — True for the original Milestone B shape (the
    iterable expression IS the generator construction call, so this
    loop is the value's only reference and its only chance to be
    freed), False when the caller (_gen_for_iter) determined the
    generator instead came from a plain variable that may still be
    read again afterward — destroying it unconditionally there is a
    real use-after-free the first time that variable is consumed a
    second time. See the call site in _gen_for_iter for the full
    rationale."""
    base, vct = api['base'], api['value_ctype']
    # `for a, b in <tuple-yielding generator>():` — `var` arrives as
    # the literal string "(a, b)" (see _gen_for_list's identical
    # tuple-target string convention; ForStmt.target is always a plain
    # str). Only unpack per-slot when this generator's own
    # registration proved it's REALLY a tuple-yielder (`tuple_slot_
    # ctypes` non-None, from `_generator_tuple_yield_slot_ctypes`) —
    # a plain (non-tuple) generator that happens to be consumed with a
    # tuple-looking target is a pre-existing, unrelated mismatch this
    # fix doesn't attempt to handle (falls through to the ordinary
    # single-name declare below, unchanged prior behavior).
    tuple_slot_ctypes = api.get('tuple_slot_ctypes')
    tuple_slot_nested = api.get('tuple_slot_nested')
    is_tuple_target = (gimple_ctypes.for_target_is_tuple(var)
                       and tuple_slot_ctypes is not None)
    if is_tuple_target:
        var_names = gen._split_top_level_comma(var[1:-1])
    else:
        var_names = None
        gen._declare_var(var, vct)

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    bb_check_exc = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")

    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{base}_resume ({gen_val})")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_check_exc};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    val = gen._new_val(vct, f"{base}_value ({gen_val})")
    if is_tuple_target:
        gen._emit_generator_tuple_unpack(var_names, tuple_slot_ctypes, val, tuple_slot_nested)
    else:
        gen._emit(f"  {gen._cname(var)} = {val};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    # `_resume` reporting "no value" is ambiguous between genuine
    # exhaustion and an uncaught exception that unwound the whole
    # generator body (Milestone D — see fire_runtime.h's long comment
    # on _mojo_exc_pending). Disambiguate before treating this as an
    # ordinary end-of-loop.
    gen._emit_label(bb_check_exc)
    gen._emit_generator_pending_exc_check(gen_val, base, destroy_after, bb_after)
    gen._emit_label(bb_after)
    if destroy_after:
        gen._emit(f"  {base}_destroy ({gen_val});")


def _emit_generator_pending_exc_check(gen, gen_val: str, base: str,
                                       destroy_after: bool, bb_not_pending: str):
    """Shared by every ordinary (never-suspended) GIMPLE consumer of a
    compiled generator's `_resume` (this method, next()'s lowering, and
    indirectly _cpp_yield_from's own analogous C++-side check) —
    Milestone D. Called right after `_resume` reports false: if the
    false was actually a propagated exception (mojo_exc_pending_get()),
    clear the flag and call mojo_raise() for real — safe here because
    this call site is ordinary GIMPLE C code that was never itself
    suspended, so the longjmp only crosses live, ordinary C frames (see
    fire_runtime.h). Otherwise falls through to `bb_not_pending`
    (ordinary ends-of-iteration handling, unchanged)."""
    pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
    bb_pending = gen._new_bb()
    gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_not_pending};")
    gen._emit_label(bb_pending)
    gen._emit("  mojo_exc_pending_set (0);")
    if destroy_after:
        gen._emit(f"  {base}_destroy ({gen_val});")
    gen._emit("  mojo_raise ();")


def _gen_for_iter_cursor(gen, node, var: str) -> None:
    """`for x in it:` over a resumable iterator local — see
    `_gen_for_iter`'s call site. Resumes from the shared cursor and leaves
    it exhausted.

    The cursor advance belongs at the TOP of the body, immediately after
    the read, not in `bb_post` after it. That is the Python invariant:
    by the time the loop body runs, the iterator is already one past the
    element just yielded, so a `next(it)` inside the body reads the
    FOLLOWING one. With the advance in `bb_post`, `cur` still pointed AT
    the element the loop had just handed to `var` while the body ran, and
    `next(it)` read exactly that one again — so `walk([1,2,3,4])` below
    printed `[1, 1, 3, 3]` (two elements consumed, each reported twice,
    and half the iterations lost) where CPython prints `[1, 2, 3, 4]`.

    This is the same shape CPython's
    `Tools/cases_generator/analyzer.py::check_escaping_calls` uses:

        tkn_iter = iter(stmt.contents)
        for tkn in tkn_iter:
            ...
                next(tkn_iter)

    `bb_post` stays on `loop_stack` so `break`/`continue` still land
    somewhere correct; it is now just the jump back to `bb_cond`. A
    `continue` is still right, precisely because the advance has already
    happened by the time the body is reached.
    """
    rec = itc.cursor_for(gen, gen._cname(node.iterable.name))
    cur = rec['cursor']
    vct = itc.element_ctype(rec)
    gen._declare_var(var, vct)
    n = gen._new_val('int64_t', rec['full'])
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond = gen._new_val('_Bool', f"{cur} < {n}")
    gen._emit(f"  if ({cond}) goto {bb_body}; else goto {bb_after};")
    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    # The cursor invariant is Python's: `cur` is the index of the next
    # UNCONSUMED element, and the advance happens as the element is read —
    # not after the body. `next(it)` inside the body (the
    # `Tools/cases_generator/analyzer.py::check_escaping_calls` shape) reads
    # at `cur`, so a post-body advance would make it re-read the element the
    # loop had just yielded: two elements consumed, each reported twice.
    _evct, ev = itc.read_at(gen, rec, cur)
    gen._emit(f"  {gen._cname(var)} = {ev};")
    nc = gen._inc_val(cur)
    gen._emit(f"  {cur} = {nc};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    # `bb_post` stays in the loop_stack above so a `continue` still lands
    # somewhere correct; with the advance already done it is just the jump
    # back to the condition.
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_enumerate_generator(gen, node, gen_val: str, api: dict,
                                  start_val: str | None, destroy_after: bool) -> None:
    """`for i, v in enumerate(<generator>[, start]):` — drive the generator
    with the established `_resume`/`_value` "returns 2 things" convention
    (mirrors `_gen_for_generator_iter`), threading a plain int64_t counter
    for the index. Previously `_gen_for_enumerate` cast whatever the
    iterable lowered to straight to `MojoList *` and read `mojo_list_len`/
    `mojo_list_get_int` off a `MojoGenerator *` handle — uninitialized-
    memory reads as loop bounds/values (garbage output, or an infinite
    loop when the garbage looked like an always-true condition)."""
    base, vct = api['base'], api['value_ctype']
    target = node.target
    if isinstance(target, str) and target.startswith('(') and target.endswith(')'):
        parts = gen._split_top_level_comma(target[1:-1])
    else:
        parts = [target, '_enum_val']
    idx_var = parts[0] if parts else '_enum_i'
    val_var = parts[1] if len(parts) >= 2 else '_enum_val'
    gen._declare_var(idx_var, 'int64_t')
    gen._declare_var(val_var, vct)
    cidx = gen._cname(idx_var); cval = gen._cname(val_var)
    ctr = gen._new_temp('int64_t')
    gen._emit(f"  {ctr} = {start_val};" if start_val is not None
              else f"  {ctr} = (int64_t)0;")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb(); bb_check_exc = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond = gen._new_val('_Bool', f"{base}_resume ({gen_val})")
    gen._emit(f"  if ({cond}) goto {bb_body}; else goto {bb_check_exc};")
    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    val = gen._new_val(vct, f"{base}_value ({gen_val})")
    gen._emit(f"  {cidx} = {ctr};")
    gen._emit(f"  {cval} = {val};")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    nc = gen._inc_val(ctr)
    gen._emit(f"  {ctr} = {nc};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_check_exc)
    gen._emit_generator_pending_exc_check(gen_val, base, destroy_after, bb_after)
    gen._emit_label(bb_after)
    if destroy_after:
        gen._emit(f"  {base}_destroy ({gen_val});")


def _gen_for_struct_iter(gen, var: str, struct_type: str,
                          obj_val: str, body: list, shadow_name: str | None = None,
                          node=None):
    """for x in obj — dispatches via StructName___iter__ / __has_next__ / __next__.

    A struct that implements PYTHON's `__next__` and not Mojo's `__has_next__`
    cannot drive this loop, and the refusal is now the same loud one every
    other unsupported iterable gets rather than a silently false loop
    condition — see the `else` below."""
    base = gimple_exprtypes._struct_name_of(struct_type)

    # Determine iterator type (may be the same struct or a separate iter type).
    # Every symbol here goes through `gen._struct_method_csym`, the tree's ONE
    # composer for a struct method's C name — NOT an f-string spelling
    # `{Struct}___{method}__` written out again. The hand-written form omits
    # the home-module qualifier, so a struct reached via `from mod import
    # Struct` emitted a call to the BARE name: gcc's implicit-declaration
    # fallback made it an `int` and the `for`/`next` lowering then read
    # `It___iter__(It *)` as `int`, so `iter_var` was a garbage pointer —
    # "implicit declaration of function 'It___iter__'; did you mean
    # 'itmod_It___iter__'?" plus "assignment to 'It *' from 'int' makes
    # pointer from integer without a cast", with no correct answer anywhere
    # in the output.
    iter_fn = gen._struct_method_csym(base, '__iter__', '')
    # `__iter__` is the ONE method here that may be dispatched through its bare
    # name, because the `else` branch below (keep the receiver's own type) is
    # its correct answer when it is absent. But a struct that OVERLOADS
    # `__iter__` defines neither `_0120be` nor `_0120be_2` under the bare name,
    # so taking this branch would emit a call to a symbol nothing defines —
    # measured, `test/itertools/test_repeat.mojo` linked with `Undefined
    # symbols: __RepeatIterator_11_ElementType_5_Int64___iter__`, called from
    # both of its `for` loops. Every iterator in `std/iter` overloads `__iter__`
    # on `var self` and on `ref self`, so this is the whole family, and the
    # `else` branch is right for all of them: `__iter__` returns
    # `Self.IteratorOwnedType`, and `comptime IteratorOwnedType: Iterator =
    # Self`.
    if (iter_fn in gen.func_return_types
            and (base, '__iter__') not in gen._ambiguous_struct_methods):
        iter_type = gen.func_return_types[iter_fn]
        iter_var  = gen._new_temp(iter_type)
        gen._emit(f"  {iter_var} = {iter_fn} ({obj_val});")
        iter_base = gimple_exprtypes._struct_name_of(iter_type)
    else:
        iter_type = struct_type
        iter_var  = obj_val
        iter_base = base

    has_next_fn = gen._struct_method_csym(iter_base, '__has_next__', '')
    next_fn     = gen._struct_method_csym(iter_base, '__next__', '')
    elem_type   = gen.func_return_types.get(next_fn, 'int64_t')
    gen._declare_var(var, elem_type, force=(var == shadow_name))

    bb_cond  = gen._new_bb(); bb_body  = gen._new_bb()
    bb_post  = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")

    gen._emit_label(bb_cond)
    if has_next_fn in gen.func_return_types:
        hn_t   = gen._new_temp('int')
        cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {hn_t} = {has_next_fn} ({iter_var});")
        gen._emit(f"  {cond_t} = {hn_t} != 0;")
    else:
        # Python spells exhaustion by RAISING StopIteration out of `__next__`,
        # and this loop has no way to see a raise: `raise StopIteration` inside
        # the method lowers to `mojo_exc_type_set (...)` + `mojo_raise ()`
        # (measured, `Counter___next__` in the generated C), which unwinds
        # past the loop with nothing left to test. So a struct with `__next__`
        # and no `__has_next__` has no expressible loop condition.
        #
        # It USED to emit `cond = 0` with a `/* TODO */` marker, which is the
        # same zero-iteration behaviour the runtime diagnostic is built to
        # describe — `mojo_unsupported_iter`'s own message ends "the loop body
        # runs zero times" — except SILENTLY. So the program exits 0 having
        # done nothing and nothing says which of its loops was dropped:
        #
        #     class Counter: __iter__ / __next__ but no __has_next__
        #     for x in c: print(x)          # prints nothing, exit 0
        #
        # Calling the shared refusal is strictly that plus a greppable
        # diagnostic naming the type and the loop's file:line, which is the
        # whole reason `_emit_unsupported_iter` exists. It is the same call
        # `_gen_for_iter`'s dispatch makes for a type with NEITHER method, so
        # "this iterator protocol has no lowering" stops being a property of
        # which half of the protocol the type happens to implement.
        gimple_ctypes._debug_note('iterator loop has no __has_next__ (Python-style __next__ exhaustion is a raise)', iter_base)
        gen._emit_unsupported_iter(f'{iter_base} (no __has_next__)', node)
        cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {cond_t} = 0;")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    if next_fn in gen.func_return_types:
        nxt = gen._new_val(elem_type, f"{next_fn} ({iter_var})")
        gen._emit(f"  {gen._cname(var)} = {nxt};")
    else:
        gimple_ctypes._debug_note('iterator loop body has no __next__', iter_base)
        gen._emit(f"  /* TODO: no __next__ on {iter_base} */")
    gen.loop_stack.append((bb_post, bb_after))
    gen._gen_loop_body(body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
