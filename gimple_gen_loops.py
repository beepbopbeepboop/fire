"""For-loop family lowering for the GIMPLE backend.

Function-extraction architecture: former GimpleGen methods as module-level
functions taking `gen` first; delegates remain on the class; cross-module
references are qualified (single-emission closure rule).
"""
from __future__ import annotations

import os
import re

from mojo_compiler import (
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
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    _as_str, _pair_key,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc

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
    for s in node.body:
        gen.gen_stmt(s)
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


def _tuple_elem_value(gen, vtype: str, v: str, idx: int) -> tuple[str, str]:
    """Read element `idx` of a tuple value (vtype, v), returning
    (elem_ctype, value). A tuple literal lowers with vtype 'MojoList *';
    a tuple RETURNED BY A CALL lowers with vtype 'int64_t' (the handle is
    boxed — this codegen's own `-> tuple[str, str]` annotation resolves to
    int64_t via _mojo_type), its real type only recoverable through
    _actual_types. The old consumers only handled the MojoList* case, so
    call-returned tuples were indexed with mojo_list_get_int — reading the
    (ctype, cval) string-pair tuples this codegen returns everywhere as
    decimal pointers. Resolve the actual type first, then pick the
    accessor from the element type, mirroring the MojoList* branch."""
    real = gen._get_actual_type(vtype, v)
    idx64 = gen._new_val('int64_t', f"(int64_t){idx}")
    if real == 'MojoList *':
        elem = gen._elem_of(v)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if vtype == real:
            lp = v
        else:
            # The C storage is int64_t (boxed handle); cast to a real
            # MojoList* temp before the accessor call, or GIMPLE rejects
            # "passing int64_t where MojoList * expected".
            lp = gen._new_val('MojoList *', f"(MojoList *){v}")
        if suf == 'str':
            return 'char *', gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
        if suf == 'double':
            return 'double', gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
        if elem in ('int64_t', 'int', '_Bool'):
            return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        # Pointer elem that isn't char* (e.g. a nested MojoList*): read the
        # opaque int64_t then cast, matching the old 'int'-suffix handling.
        raw = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        return elem, gen._new_val(elem, f"({elem}){raw}")
    # Non-container / untracked: index the boxed pointer as a plain int list
    lp = gen._new_val('MojoList *', f"(MojoList *){v}")
    return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")


def _emit_unsupported_iter(gen, it_type: str, node=None) -> None:
    """Abort at runtime instead of silently running a for-loop body zero
    times — see mojo_unsupported_iter in runtime/mojo_runtime.c.

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


def _try_const_fold_int(gen, expr) -> int | None:
    if isinstance(expr, gimple_ctypes.IntLiteral):
        return expr.value
    return None


def _try_const_fold_str(gen, expr) -> str | None:
    """Evaluate a compile-time-constant string expression (literal,
    concatenation, or repetition of foldable pieces, or a reference to
    an already-folded local — see _const_str_locals, populated as a
    side effect of ordinary AssignStmt/VarDecl lowering in program
    order) without running the program. Needed for re.sub(pattern,
    callback, src) call sites whose pattern isn't a bare string literal
    but is still fully known ahead of time, e.g. mojo_compiler.py's own
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
    runtime/mojo_runtime.c, instead of _gen_for_iter's generic
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
    # _parse_unpack_target in mojo_compiler.py) — the old
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
        for s in node.body:
            gen.gen_stmt(s)
    finally:
        gen.loop_stack.pop()
        gen._loop_depth -= 1
        del gen._regex_match_vars[var]

    if not gen._last_was_terminal:
        gen._emit(f'  goto {bb_post};')
    gen._emit_label(bb_post)
    # pos = (mend > pos) ? mend : pos + 1 — advance past the match, or by
    # one char on a zero-width match, exactly like Python's finditer.
    pos_plus1 = gen._new_val('int64_t', f'{pos_var} + (int64_t)1')
    cmp_t = gen._new_val('_Bool', f'{mend_var} > {pos_var}')
    next_pos = gen._new_val('int64_t', f'{cmp_t} ? {mend_var} : {pos_plus1}')
    gen._emit(f'  {pos_var} = {next_pos};')
    gen._emit(f'  goto {bb_cond};')
    gen._emit_label(bb_after)


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
        if isinstance(var0, str) and var0.startswith('(') and var0.endswith(')'):
            tgt_names = gen._split_top_level_comma(var0[1:-1])
        else:
            tgt_names = [var0]
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
    # _parse_unpack_target in mojo_compiler.py and _gen_for_regex_iter's
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
        and isinstance(it.func.obj, gimple_ctypes.IdentExpr) and it.func.obj.name == 'dataclasses'
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
            and it.name in getattr(gen, '_list_iter_cursor', {})
            and isinstance(var, str) and ',' not in var
            and not getattr(node, 'else_body', None)):
        _gen_for_list_iter_cursor(gen, node, var)
        return

    try:
        it_type, it_val = gen.lower_expr(node.iterable)
    except Exception:
        if is_dataclass_fields_loop:
            gen._dataclass_fields_vars.discard(var)
        raise

    # Check if this is an int64_t-stored pointer (from method call returning pointer)
    it_type = gen._get_actual_type(it_type, it_val)

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
    target_names = (gen._split_top_level_comma(var[1:-1])
                     if isinstance(var, str) and var.startswith('(') and var.endswith(')')
                     else [var])
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
        elif it_type == 'MojoDict *':
            gen._gen_for_dict(var, it_val, node.body, shadow_name=shadow_name)
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
        elif it_type.endswith(' *') or it_type.endswith('*'):
            # User-defined struct: try __iter__ / __has_next__ / __next__ protocol
            base = gimple_exprtypes._struct_name_of(it_type)
            has_next = f"{base}___has_next__"
            nxt      = f"{base}___next__"
            if has_next in gen.func_return_types or nxt in gen.func_return_types:
                gen._gen_for_struct_iter(var, it_type, it_val, node.body, shadow_name=shadow_name)
            else:
                gimple_ctypes._debug_note('for loop dropped (no iterator protocol)', it_type)
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
            # POSITIVE EVIDENCE the boxed handle is a LIST: a tracked element
            # type that is a real (non-boxed) pointer can only have been
            # recorded for a list. Take the list path directly instead of
            # emitting the runtime dict-or-list dispatch below, whose dict
            # arm would bind this same loop variable to a `char *` KEY.
            # `_declare_var` is first-decl-wins, so the two arms otherwise
            # declare one variable with two incompatible types and GCC
            # rejects the dead dict arm outright ("assignment to
            # 'FunctionDef *' from incompatible pointer type 'char *'").
            # The dict arm is provably dead for such a value anyway.
            _boxed_elem = gen._elem_of(it_val)
            if (it_type in ('int', 'int64_t', 'void *') and _boxed_elem
                    and _boxed_elem != 'int64_t' and _boxed_elem.endswith(' *')):
                _lp_known = gen._new_val(
                    'MojoList *', f"(MojoList *){gen._to_int64(it_type, it_val)}")
                gen._elem_types[_lp_known] = _boxed_elem
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
                    and not (var.startswith('(') and var.endswith(')')))
                gen._emit_label(bb_dict)
                dp = gen._new_val('MojoDict *', f"(MojoDict *){it64}")
                if _it_is_items:
                    _pairs = gen._new_val(
                        'MojoList *', f"mojo_dict_items ({dp})")
                    # Value type is genuinely unknown here (the receiver
                    # never typed) — int64_t matches how mojo_dict_items
                    # boxes the value slot.
                    gen._dict_items_val_elems[_pairs] = 'int64_t'
                    gen._gen_for_list(var, _pairs, node.body)
                else:
                    gen._gen_for_dict(var, dp, node.body)
                gen._emit(f"  goto {bb_after};")
                gen._emit_label(bb_list)
                lp = gen._new_val('MojoList *', f"(MojoList *){it64}")
                if _it_is_items:
                    # An already-materialized items list: its elements are
                    # the same [key, value] pairs.
                    gen._dict_items_val_elems[lp] = 'int64_t'
                gen._gen_for_list(var, lp, node.body)
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
    if not (isinstance(target, str) and target.startswith('(') and target.endswith(')')):
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
            ptr = gen._new_val('MojoList *', f"(MojoList *){sv}")
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

    for s in node.body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1

    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _zip_bind_slot(gen, vn: str, list_ptr: str, elem: str, idx_t: str) -> None:
    """Bind one `zip()` loop target `vn` to `list_ptr[idx_t]`, reading with
    the accessor matching THAT sequence's own element type and coercing to
    the target's declared C type.

    Mirrors `_gen_for_list`'s per-slot `_emit_target_assign` (same accessor
    choice, same box/unbox and `_actual_types` recovery conventions) — the
    only difference is that a zip slot reads element `idx_t` of its OWN
    per-slot LIST, where a tuple-unpack slot reads element `i` of one
    shared tuple."""
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
        if elem == 'MojoList *' and list_ptr in gen._nested_elem_types:
            gen._elem_types[vn] = gen._nested_elem_types[list_ptr]


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
    mismatch, a nested tuple slot, a non-list sequence) raises; the caller
    (`_gen_stmt_ForStmt`) rolls back partial output transactionally and
    falls through to the pre-existing generic path unchanged."""
    it = node.iterable
    if it.kwargs:
        raise ValueError("zip() takes no keyword arguments")
    args = list(it.args)
    if len(args) < 2:
        raise ValueError("only the multi-sequence zip() shape is lowered here")
    target = node.target
    if not (isinstance(target, str) and target.startswith('(') and target.endswith(')')):
        raise ValueError("zip() lowering needs a tuple loop target")
    tgt_names = [t.strip() for t in gen._split_top_level_comma(target[1:-1])]
    if len(tgt_names) != len(args):
        raise ValueError("zip() target arity does not match its sequence count")
    for _tn in tgt_names:
        if _tn.startswith('(') and _tn.endswith(')'):
            raise ValueError("nested tuple target in zip() is unsupported here")

    seq_ptrs = []
    seq_elems = []
    for _ai in range(len(args)):
        st, sv = gen.lower_expr(args[_ai])
        st = gen._get_actual_type(st, sv)
        if st != 'MojoList *':
            raise ValueError(f"zip() over {st} is unsupported here")
        ptr = sv
        if ptr in gen.var_types and gen.var_types[ptr] == 'int64_t':
            ptr = gen._new_val('MojoList *', f"(MojoList *){sv}")
        seq_ptrs.append(ptr)
        _e = gen._elem_of(sv)
        seq_elems.append(_e if _e else 'int64_t')

    # Declare each target by its OWN slot's element type BEFORE the loop
    # (mirrors _gen_for_zip_longest / _gen_for_enumerate ordering).
    # `_declare_var` is first-decl-wins, so a later loop reusing the same
    # name inherits these real types instead of an int64_t lock-in.
    for _di in range(len(tgt_names)):
        gen._declare_var(tgt_names[_di], seq_elems[_di])

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
    for s in node.body:
        gen.gen_stmt(s)
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
    gen._declare_var(val_var, 'char')
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
    gen._ptr_helpers_needed.add('char')
    addr = gen._new_val('char *', f"_mojo_at_char ({s_val}, {idx_t})")
    gen._emit(f"  {cval_var} = *{addr};")
    for st in node.body:
        gen.gen_stmt(st)
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
    val_var = gen._new_temp('int64_t') if val_is_tuple else raw_val

    # Ensure underlying list
    if lst_type == 'MojoList *':
        list_ptr = lst_val
        if lst_val in gen.var_types and gen.var_types[lst_val] == 'int64_t':
            list_ptr = gen._new_val('MojoList *', f"(MojoList *){lst_val}")
    else:
        list_ptr = gen._new_val('MojoList *', f"(MojoList *){lst_val}")

    elem = gen._elem_of(list_ptr)
    gen._declare_var(idx_var, 'int64_t')
    if not val_is_tuple:
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
        tuple_ptr = gen._new_val('MojoList *', f"(MojoList *){val_var}")
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

    for s in node.body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1

    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _tuple_unpack_slot_elems(gen, it_val: str, nslots: int) -> list:
    """Per-slot C element types for a tuple-UNPACKING loop target
    (`for k, v in <pairs>:`), from whatever container metadata is
    tracked for the iterable value: dict-items pairs have a char* key
    slot and the dict's own value-type value slot; a heterogeneous
    tuple-literal list carries its per-slot types (_tuple_slot_types);
    anything else falls back to the pair element type / int64_t."""
    is_dict_items = it_val in gen._dict_items_val_elems
    value_elem = gen._dict_items_val_elems.get(it_val) if is_dict_items else None
    slot_types = gen._tuple_slot_types.get(it_val)
    pair_elem = gen._nested_elem_types.get(it_val, 'int64_t')
    elems = []
    # `_as_str` on every appended slot type: the source metadata dicts
    # (_tuple_slot_types / _nested_elem_types / _dict_items_val_elems)
    # can hand back a boxed/garbage value on the self-hosted path, and
    # `_declare_var`'s `mojo_str_cat` then ran `strlen()` on it — a hard
    # segfault on the single-TU `--dump myinterpreter.py`.
    for i in range(nslots):
        if is_dict_items:
            elems.append('char *' if i == 0 else _as_str(value_elem or 'int64_t'))
        elif slot_types is not None and i < len(slot_types):
            elems.append(_as_str(slot_types[i]))
        else:
            elems.append(_as_str(pair_elem))
    return elems


def _gen_for_list(gen, var: str, it_val: str, body: list, shadow_name: str | None = None):
    # Handle tuple unpacking: for (a, b) in list_of_tuples:
    is_tuple = var.startswith('(') and var.endswith(')')
    elem = None if is_tuple else gen._elem_of(it_val)
    if is_tuple:
        # Bracket-aware split (a naive `inner.split(',')` turned a nested
        # target like `(report_type, (old_mode, old_file))` into the bogus
        # name fragments `(old_mode` / `old_file)` — declared verbatim as
        # `int64_t (old_mode;` etc., hard C syntax errors; see
        # Lib/test/support/__init__.py's WindowsCleanup.__exit__).
        inner = var[1:-1].strip()
        var_names = gen._split_top_level_comma(inner)
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
        def _declare_target_name(vn, se):
            if vn.startswith('(') and vn.endswith(')'):
                for _nv in gen._split_top_level_comma(vn[1:-1].strip()):
                    _declare_target_name(_nv, 'int64_t')
            else:
                gen._declare_var(vn, se, force=(vn == shadow_name))
        for _fli in range(len(var_names)):
            _fl_vn = _as_str(var_names[_fli])
            _fl_se = _as_str(slot_elems[_fli]) if _fli < len(slot_elems) else 'int64_t'
            _declare_target_name(_fl_vn, _fl_se)
    else:
        var_names = None
        gen._declare_var(var, _as_str(elem) if elem is not None else elem, force=(var == shadow_name))
    len64 = gen._new_temp('int64_t')
    len_t = gen._new_temp('int64_t')
    idx_t = gen._new_temp('int64_t')
    # Cast it_val back to MojoList* if it's stored as int64_t (from method call)
    list_ptr = it_val
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        list_ptr = gen._new_val('MojoList *', f"(MojoList *){it_val}")
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
        tuple_ptr = gen._new_val('MojoList *', f"(MojoList *){elem64}")
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
                return 'char *', f"mojo_list_get_str ({ptr}, {i})"
            return 'int64_t', f"mojo_list_get_int ({ptr}, {i})"

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
                nested_ptr = gen._new_val('MojoList *', f"(MojoList *){nested_raw}")
                nested_names = gen._split_top_level_comma(vn[1:-1].strip())
                for j, nn in enumerate(nested_names):
                    _emit_target_assign(nested_ptr, nn, j, pair_elem)
                return
            gen._declare_var(vn, slot_elem)
            cvn = gen._cname(vn)
            suf = gimple_ctypes.TypeLattice.list_suffix(slot_elem)
            vt = gen.var_types.get(vn, slot_elem)
            if suf == 'str':
                ts = gen._new_val('char *', f"mojo_list_get_str ({tuple_ptr}, {i})")
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
                raw = gen._new_val('int64_t', f"mojo_list_get_int ({tuple_ptr}, {i})")
                if vt == 'int64_t':
                    gen._emit(f"  {cvn} = {raw};")
                else:
                    gen._safe_coerce_emit('int64_t', vt, raw, cvn)

        for i, vn in enumerate(var_names):
            if vn.startswith('(') and vn.endswith(')'):
                _emit_target_assign(tuple_ptr, vn, i, 'int64_t')
                continue
            _emit_target_assign(tuple_ptr, vn, i, slot_elems[i])
    else:
        cvar = gen._cname(var)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if suf == 'double':
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
    if _is_pair_var:
        gen._dict_item_pair_vars[var] = gen._dict_items_val_elems[it_val]
    gen.loop_stack.append((bb_post, bb_after))
    for s in body:
        gen.gen_stmt(s)
    if _is_pair_var:
        if _had_pair:
            gen._dict_item_pair_vars[var] = _saved_pair
        else:
            gen._dict_item_pair_vars.pop(var, None)
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
    for s in body:
        gen.gen_stmt(s)
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
    error). A striking real consequence: mojo_compiler.py's own
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
    gen._declare_var(var, 'char')
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
    gen._ptr_helpers_needed.add('char')
    addr = gen._new_val('char *', f"_mojo_at_char ({it_val}, {idx_t})")
    gen._emit(f"  {gen._cname(var)} = *{addr};")
    gen.loop_stack.append((bb_post, bb_after))
    for s in body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx_t} + {one}")
    gen._emit(f"  {idx_t} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_for_dict(gen, var: str, it_val: str, body: list, shadow_name: str | None = None):
    """for k in dict — iterates over keys as char *."""
    # Handle tuple target like '(name, alias)' — declare each name separately
    is_tuple = var.startswith('(') and var.endswith(')')
    if is_tuple:
        inner = var[1:-1].strip()
        var_names = gen._split_top_level_comma(inner)
        # Flatten any nested tuple target the same way _gen_for_list does
        # (a naive split turned `(k, (a, b))` into the bogus fragments
        # `(a` / `b)`, declared verbatim — hard C syntax errors).
        def _flatten(vn, acc):
            if vn.startswith('(') and vn.endswith(')'):
                for _nv in gen._split_top_level_comma(vn[1:-1].strip()):
                    _flatten(_nv, acc)
            else:
                acc.append(vn)
        _flat = []
        for vn in var_names:
            _flatten(vn, _flat)
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
            _want = 'char *' if i == 0 else 'int64_t'
            gen._declare_var(vn, _want, force=(vn == shadow_name))
            _slot_ctypes.append(gen.var_types.get(vn, _want))
    else:
        gen._declare_var(var, 'char *', force=(var == shadow_name))
    # If it_val is int64_t (boxed pointer), cast to MojoDict *
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        dict_ptr = gen._new_val('MojoDict *', f"(MojoDict *){it_val}")
        it_val = dict_ptr
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
    key_tmp = gen._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
    # Every write goes through _cname: a loop variable whose Mojo name is a
    # C keyword (`for char in s.codepoints():` — real, in stdlib's
    # _unicode.mojo) is DECLARED as the renamed `_char` by _declare_var,
    # and every read already resolves through _cname, but these writes used
    # the raw name and emitted `char = (char *) _t10;` — a hard "expected
    # expression before 'char'" parse error. Latent until the boxed
    # dict/list runtime dispatch (A5-BUG.md §1) started generating this
    # branch for real; _gen_for_list has always done this correctly.
    if is_tuple:
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
    for s in body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_dict_iter_free ({iter_t});")


def _gen_for_set(gen, var: str, it_val: str, body: list, shadow_name: str | None = None):
    """for x in set — iterates over int64_t values (int set assumed)."""
    gen._declare_var(var, 'int64_t', force=(var == shadow_name))
    # If it_val is int64_t (boxed pointer), cast to MojoSet * (matches dict path)
    if it_val in gen.var_types and gen.var_types[it_val] == 'int64_t':
        set_ptr = gen._new_val('MojoSet *', f"(MojoSet *){it_val}")
        it_val = set_ptr
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
    gen._emit(f"  {gen._cname(var)} = mojo_set_iter_val_int ({iter_t});")
    gen.loop_stack.append((bb_post, bb_after))
    for s in body:
        gen.gen_stmt(s)
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
    for pname, ptype in node.params:
        if pname in _lambda_capture_types:
            gen.var_types[pname] = _lambda_capture_types[pname]
        elif ptype is None and pname in inferred_params:
            gen.var_types[pname] = inferred_params[pname]
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


def _emit_generator_tuple_unpack(gen, var_names: list, slot_types: list, list_ptr: str) -> None:
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
    is_tuple_target = var.startswith('(') and var.endswith(')') and tuple_slot_ctypes is not None
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
        gen._emit_generator_tuple_unpack(var_names, tuple_slot_ctypes, val)
    else:
        gen._emit(f"  {gen._cname(var)} = {val};")
    gen.loop_stack.append((bb_post, bb_after))
    for s in body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    # `_resume` reporting "no value" is ambiguous between genuine
    # exhaustion and an uncaught exception that unwound the whole
    # generator body (Milestone D — see mojo_runtime.h's long comment
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
    mojo_runtime.h). Otherwise falls through to `bb_not_pending`
    (ordinary ends-of-iteration handling, unchanged)."""
    pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
    bb_pending = gen._new_bb()
    gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_not_pending};")
    gen._emit_label(bb_pending)
    gen._emit("  mojo_exc_pending_set (0);")
    if destroy_after:
        gen._emit(f"  {base}_destroy ({gen_val});")
    gen._emit("  mojo_raise ();")


def _gen_for_list_iter_cursor(gen, node, var: str) -> None:
    """`for x in it:` over a resumable list-iterator local — see
    `_gen_for_iter`'s call site. Resumes from the shared cursor and leaves
    it exhausted."""
    li = gen._list_iter_cursor[node.iterable.name]
    lst, cur, elem = li['list'], li['cursor'], li['elem']
    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    vct = {'str': 'char *', 'double': 'double'}.get(suf, 'int64_t')
    gen._declare_var(var, vct)
    n = gen._new_temp('int64_t')
    gen._emit(f"  {n} = mojo_list_len ({lst});")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond = gen._new_val('_Bool', f"{cur} < {n}")
    gen._emit(f"  if ({cond}) goto {bb_body}; else goto {bb_after};")
    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    ev = gen._new_val(vct, f"mojo_list_get_{suf} ({lst}, {cur})")
    gen._emit(f"  {gen._cname(var)} = {ev};")
    gen.loop_stack.append((bb_post, bb_after))
    for s in node.body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    nc = gen._new_val('int64_t', f"{cur} + (int64_t)1")
    gen._emit(f"  {cur} = {nc};")
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
    for s in node.body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    nc = gen._new_val('int64_t', f"{ctr} + (int64_t)1")
    gen._emit(f"  {ctr} = {nc};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_check_exc)
    gen._emit_generator_pending_exc_check(gen_val, base, destroy_after, bb_after)
    gen._emit_label(bb_after)
    if destroy_after:
        gen._emit(f"  {base}_destroy ({gen_val});")


def _gen_for_struct_iter(gen, var: str, struct_type: str,
                          obj_val: str, body: list, shadow_name: str | None = None):
    """for x in obj — dispatches via StructName___iter__ / __has_next__ / __next__."""
    base = gimple_exprtypes._struct_name_of(struct_type)

    # Determine iterator type (may be the same struct or a separate iter type)
    iter_fn = f"{base}___iter__"
    if iter_fn in gen.func_return_types:
        iter_type = gen.func_return_types[iter_fn]
        iter_var  = gen._new_temp(iter_type)
        gen._emit(f"  {iter_var} = {iter_fn} ({obj_val});")
        iter_base = gimple_exprtypes._struct_name_of(iter_type)
    else:
        iter_type = struct_type
        iter_var  = obj_val
        iter_base = base

    has_next_fn = f"{iter_base}___has_next__"
    next_fn     = f"{iter_base}___next__"
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
        gimple_ctypes._debug_note('iterator loop emitted with false condition (no __has_next__)', iter_base)
        cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {cond_t} = 0;  /* TODO: no __has_next__ on {iter_base} */")
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
    for s in body:
        gen.gen_stmt(s)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
