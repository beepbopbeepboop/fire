"""gimple_gen_coro.py -- Layer 1 of the A3 stack-switch coroutine codegen
(doc/COROUTINE.html §5.4).

An AST pre-pass, run in gimple_codegen._run_pipeline right after
ast_rewriter.rewrite, gated by MOJO_CORO=stackswitch. For each eligible
top-level generator FunctionDef `g` it:

  * replaces `g` in the module statement list with `__mgco_<g>_body`, a
    plain (non-generator) FunctionDef whose body is g's body with only
    these rewrites -- so the ORDINARY broad codegen lowers it, which is
    the whole point:
        yield e            -> __mojo_coro_yield_i(__c, e)      (expr; value = send)
        return e           -> __mojo_gen_set_return(__c, e); return
        return             -> return
        <param p_i>        -> `var p_i = __mojo_gen_arg(__c, i)` prologue
  * records metadata so register() can populate gen._generator_api[g] and
    emit the 4 tiny C trampolines (<base>_start/_resume/_value/_destroy)
    that the ordinary for/next/yield-from consumers already know how to
    call.

Anything not eligible is left untouched and falls through to the existing
gimple_cpp_* C++20-coroutine path -- incremental cutover.
"""
from __future__ import annotations

import os

import mojo_compiler as N

_ENV = 'MOJO_CORO'
_MODE = 'stackswitch'

ARG_SHIM     = '__mojo_gen_arg'
SETRET_SHIM  = '__mojo_gen_set_return'
_KIND_CTYPE  = {'i': 'int64_t', 'p': 'char *', 'd': 'double', 'tuple': 'MojoList *'}


def _yield_shim(kind: str) -> str:
    # int/pointer both go through the int64_t yield -- _emit_call coerces a
    # char*/pointer arg to int64_t via the registered param types. Only a
    # genuine double needs the bitcast variant.
    return '__mojo_coro_yield_d' if kind == 'd' else '__mojo_coro_yield_i'


def enabled() -> bool:
    return os.environ.get(_ENV) == _MODE


# ── eligibility ─────────────────────────────────────────────────────────

def _walk(node):
    """Yield node and every AST descendant (attributes + list attributes)."""
    yield node
    d = getattr(node, '__dict__', None)
    if not d:
        return
    for v in d.values():
        if isinstance(v, list):
            for x in v:
                if hasattr(x, '__dict__'):
                    yield from _walk(x)
        elif hasattr(v, '__dict__'):
            yield from _walk(v)


_SCALARISH = {'Int', 'Int64', 'Int32', 'Bool', 'String', 'StringLiteral', '', None}


def _yield_kind(expr) -> str | None:
    """Best-effort C kind of a yielded value: 'i' int/bool/pointer (the
    yield call always coerces to int64_t, so 'i' vs 'p' only affects the
    <base>_value RETURN type), 'p' string pointer, 'd' float, 'tuple' a
    tuple literal (not handled yet). None == can't tell (treated as 'i')."""
    if expr is None:
        return 'i'
    if isinstance(expr, N.TupleExpr):
        return 'tuple'
    if isinstance(expr, (N.StringLiteral, N.TstringLiteral)):
        return 'p'
    if isinstance(expr, N.FloatLiteral):
        return 'd'
    if isinstance(expr, (N.IntLiteral, N.BoolLiteral)):
        return 'i'
    if isinstance(expr, N.BinaryOp):
        lk, rk = _yield_kind(expr.left), _yield_kind(expr.right)
        if 'p' in (lk, rk):
            return 'p'
        if 'd' in (lk, rk):
            return 'd'
        return 'i'
    return None


_KIND_TO_SLOT_CTYPE = {'i': 'int64_t', 'p': 'char *', 'd': 'double', None: 'int64_t'}


def _generator_tuple_slots(fn: N.FunctionDef):
    """If every `yield` in `fn` yields a tuple LITERAL of the same arity,
    return the per-slot C type list; else None. Used only when
    _generator_value_kind says 'tuple'."""
    shapes = []
    for n in _walk(fn):
        if isinstance(n, N.YieldExpr):
            if not isinstance(n.value, N.TupleExpr):
                return None
            shapes.append(tuple(_yield_kind(e) for e in n.value.elements))
    if not shapes:
        return None
    ar = len(shapes[0])
    if any(len(s) != ar for s in shapes):
        return None
    slots = []
    for i in range(ar):
        kinds = {s[i] for s in shapes}
        kinds.discard(None)
        if len(kinds) > 1:
            return None            # inconsistent slot type across yields
        k = next(iter(kinds)) if kinds else None
        if k == 'tuple':
            return None            # nested tuple in a slot -- not v0
        slots.append(_KIND_TO_SLOT_CTYPE[k])
    return slots


def _generator_value_kind(fn: N.FunctionDef) -> tuple[str | None, str]:
    kinds = set()
    has_tuple = has_nontuple = False
    for n in _walk(fn):
        if isinstance(n, N.YieldExpr):
            k = _yield_kind(n.value)
            kinds.add(k)
            if k == 'tuple':
                has_tuple = True
            else:
                has_nontuple = True
        elif isinstance(n, N.YieldFromExpr):
            kinds.add(None)
            has_nontuple = True
    if has_tuple and has_nontuple:
        return None, 'mixed tuple / non-tuple yields (v0)'
    if has_tuple:
        return ('tuple', '') if _generator_tuple_slots(fn) is not None \
            else (None, 'tuple yield with inconsistent shape (v0)')
    if 'd' in kinds and (kinds - {'d', None}):
        return None, f'mixed float / non-float yields (v0)'
    if 'd' in kinds:
        return 'd', ''
    if 'p' in kinds:
        return 'p', ''
    return 'i', ''


def _yield_from_ok(fn: N.FunctionDef) -> bool:
    """True iff every YieldFromExpr in the body sits directly as an
    ExprStmt's value (bare `yield from it`) -- the only shape v0 desugars.
    `x = yield from it` (return-value capture) is not handled yet."""
    total = sum(1 for n in _walk(fn) if isinstance(n, N.YieldFromExpr))
    bare = sum(1 for n in _walk(fn)
               if isinstance(n, N.ExprStmt) and isinstance(n.value, N.YieldFromExpr))
    return total == bare


def _eligible(fn: N.FunctionDef, struct_name: str | None = None) -> tuple[bool, str]:
    if fn.is_async:
        return False, 'async'
    if getattr(fn, 'comptime_params', None):
        return False, 'comptime params'
    if getattr(fn, 'decorators', None):
        return False, 'decorated'
    if not _yield_from_ok(fn):
        return False, 'yield from with return-value capture (v0)'
    params = fn.params
    if struct_name is not None:
        if not params or params[0][0] != 'self':
            return False, 'generator method without a plain `self` first param (v0)'
        params = params[1:]   # self is typed by the codegen from the annotation
    # v0: remaining params must be simple positional scalars (or none)
    for pname, pann in params:
        if pann not in _SCALARISH:
            return False, f'param {pname!r} type {pann!r} (v0 scalar-only)'
    if getattr(fn, 'kwonly', None):
        return False, 'kwonly params (v0)'
    kind, why = _generator_value_kind(fn)
    if kind is None:
        return False, why
    return True, ''


# ── async def / await ───────────────────────────────────────────────────
# `async def f(): ... await <inner> ...` lowers exactly like a generator
# (same __mgco_<f>_body / _start/_resume/_value/_destroy trampolines, same
# register()), except `await <inner>` desugars to a drive-to-completion
# loop that forwards INNER's wait-descriptor upward via __mojo_coro_yield
# -- structurally identical to a generator's `yield from` for-loop, just
# yielding a wait-descriptor instead of a user value. Only mojo_async_sched.c
# (the outermost driver) ever interprets what gets yielded.

_AW_COUNTER = [0]


def _is_asyncio_sleep_call(node) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'sleep' and len(node.args) == 1
            and isinstance(node.func.obj, N.IdentExpr) and node.func.obj.name == 'asyncio')


def _is_asyncio_sock_recv_call(node) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'sock_recv' and len(node.args) == 1
            and isinstance(node.func.obj, N.IdentExpr) and node.func.obj.name == 'asyncio')


def _is_asyncio_run_call(node) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'run' and len(node.args) == 1
            and isinstance(node.func.obj, N.IdentExpr) and node.func.obj.name == 'asyncio')


def _await_target_name(node) -> str | None:
    """If `node` is a plain call to a bare top-level name (the only await
    target v0 forwards -- trusting the callee is itself eligible; if it
    isn't, the emitted call to a nonexistent __mgco_<name>_start just
    fails to link, caught by the gate, not a silent miscompile)."""
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr):
        return node.func.name
    return None


def _await_stmt_ok(s) -> bool:
    inner = s.value.value
    return (_is_asyncio_sleep_call(inner) or _is_asyncio_sock_recv_call(inner)
            or _await_target_name(inner) is not None)


def _async_awaits_ok(fn: N.FunctionDef) -> bool:
    """Every AwaitExpr must be a bare ExprStmt's value, or directly an
    Assign/VarDecl's value, with a recognized inner shape -- the only
    forms _rewrite_async_stmts desugars. Anything else (nested inside a
    larger expression, or an unrecognized callee shape) => ineligible."""
    total = sum(1 for n in _walk(fn) if isinstance(n, N.AwaitExpr))
    ok = 0
    for s in _walk(fn):
        if isinstance(s, (N.ExprStmt, N.AssignStmt, N.VarDecl)) \
                and isinstance(getattr(s, 'value', None), N.AwaitExpr) and _await_stmt_ok(s):
            ok += 1
    return ok == total


def _async_for_ok(fn: N.FunctionDef) -> bool:
    """Every `async for x in <iter>:` must target a plain single name and
    iterate a plain call to a bare top-level name -- the only shape
    _async_for_drive_stmts desugars."""
    for n in _walk(fn):
        if isinstance(n, N.ForStmt) and getattr(n, 'is_async', False):
            if not isinstance(n.target, str) or ',' in n.target:
                return False
            if _await_target_name(n.iterable) is None:
                return False
    return True


def _eligible_async_common(fn: N.FunctionDef) -> tuple[bool, str]:
    """Checks shared by a plain `async def` and an async GENERATOR."""
    if not fn.is_async:
        return False, 'not async'
    if getattr(fn, 'comptime_params', None):
        return False, 'comptime params'
    if getattr(fn, 'decorators', None):
        return False, 'decorated'
    for pname, pann in fn.params:
        if pann not in _SCALARISH:
            return False, f'param {pname!r} type {pann!r} (v0 scalar-only)'
    if getattr(fn, 'kwonly', None):
        return False, 'kwonly params (v0)'
    if not _async_awaits_ok(fn):
        return False, 'await in an unhandled shape (v0)'
    if not _async_for_ok(fn):
        return False, 'async for in an unhandled shape (v0)'
    return True, ''


def _eligible_async(fn: N.FunctionDef) -> tuple[bool, str]:
    if any(isinstance(n, (N.YieldExpr, N.YieldFromExpr)) for n in _walk(fn)):
        return False, 'async generator -- use _eligible_async_gen'
    return _eligible_async_common(fn)


def _eligible_async_gen(fn: N.FunctionDef) -> tuple[bool, str]:
    if not any(isinstance(n, N.YieldExpr) for n in _walk(fn)):
        return False, 'no yield'
    if any(isinstance(n, N.YieldFromExpr) for n in _walk(fn)):
        return False, 'yield from in an async generator (v0)'
    # v0: every yield must be a bare ExprStmt (no `x = yield`, no tuple
    # yields) and a scalar/pointer value (the tagged channel doesn't
    # distinguish value kinds -- v0 always treats a real yield as 'i').
    for n in _walk(fn):
        if isinstance(n, N.YieldExpr):
            if isinstance(n.value, N.TupleExpr):
                return False, 'tuple yield in an async generator (v0)'
    for s in _walk(fn):
        if isinstance(s, N.AssignStmt) and isinstance(s.value, N.YieldExpr):
            return False, '`x = yield ...` in an async generator (v0)'
        if isinstance(s, N.VarDecl) and isinstance(s.value, N.YieldExpr):
            return False, '`var x = yield ...` in an async generator (v0)'
    return _eligible_async_common(fn)


def _rewrite_async_expr(node, cvar: str):
    """Like _rewrite_expr, but for an async body -- there is no YieldExpr
    to replace (v0 excludes async generators), just recurse; AwaitExpr is
    handled at statement level by _rewrite_async_stmts before this is ever
    called on one."""
    if node is None or not hasattr(node, '__dict__'):
        return node
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            setattr(node, k, [_rewrite_async_expr(x, cvar) if hasattr(x, '__dict__') else x
                              for x in v])
        elif hasattr(v, '__dict__'):
            setattr(node, k, _rewrite_async_expr(v, cvar))
    return node


def _forward_plain(cvar: str, val_expr) -> N.ExprStmt:
    """Forward a wait-descriptor upward on an ordinary (non-tagged) yield
    channel -- used inside a plain async function/generator, where every
    yield is unambiguously a wait-descriptor."""
    return N.ExprStmt(value=_call('__mojo_coro_yield_i', [_c_ident(cvar), val_expr]))


def _forward_tagged(cvar: str, val_expr) -> N.ExprStmt:
    """Forward a wait-descriptor upward on the TAGGED channel (is_wd=1) --
    used inside an async GENERATOR body, which also has real `yield`s
    (is_wd=0) sharing the same channel; see mojo_coro.h."""
    return N.ExprStmt(value=_call('__mojo_gen_yield_tagged',
                                  [_c_ident(cvar), val_expr, N.IntLiteral(value=1)]))


def _await_drive_stmts(cvar: str, inner, forward=_forward_plain) -> tuple[list, object]:
    """The statement sequence driving one `await <inner>` to completion.
    Returns (stmts, result_expr). `forward` builds the ExprStmt that
    forwards one wait-descriptor upward (plain or tagged channel)."""
    if _is_asyncio_sleep_call(inner):
        secs = _rewrite_async_expr(inner.args[0], cvar)
        stmts = [N.ExprStmt(value=_call('__mojo_async_await_sleep', [_c_ident(cvar), secs]))]
        return stmts, N.IntLiteral(value=0)
    if _is_asyncio_sock_recv_call(inner):
        fd = _rewrite_async_expr(inner.args[0], cvar)
        _AW_COUNTER[0] += 1
        rv = f'__ar{_AW_COUNTER[0]}'
        stmts = [N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_async_await_sock_recv', [_c_ident(cvar), fd]))]
        return stmts, _c_ident(rv)
    name = _await_target_name(inner)
    args = [_rewrite_async_expr(a, cvar) for a in inner.args]
    _AW_COUNTER[0] += 1
    h = f'__ah{_AW_COUNTER[0]}'
    rv = f'__ar{_AW_COUNTER[0]}'
    stmts = [N.VarDecl(name=h, type_ann=None, value=_call(f'__mgco_{name}_start', args))]
    loop_body = [forward(cvar, _call(f'__mgco_{name}_value', [_c_ident(h)]))]
    stmts.append(N.WhileStmt(condition=_call(f'__mgco_{name}_resume', [_c_ident(h)]),
                             body=loop_body, else_body=None))
    stmts.append(N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_gen_retval', [_c_ident(h)])))
    stmts.append(N.ExprStmt(value=_call(f'__mgco_{name}_destroy', [_c_ident(h)])))
    return stmts, _c_ident(rv)


def _async_for_drive_stmts(cvar: str, target: str, iterable, body, forward=_forward_plain) -> list:
    """`async for x in f(args): <body>` -- f is a compiled async-generator
    coroutine. Drives it exactly like _await_drive_stmts, except each
    resume may produce EITHER a wait-descriptor (forward upward, loop
    again) or a real yielded value (bind `target`, run the user body --
    which may `break`/`continue` the very same while loop, matching real
    Python `async for` semantics)."""
    name = _await_target_name(iterable)
    args = [_rewrite_async_expr(a, cvar) for a in (iterable.args if iterable else [])]
    _AW_COUNTER[0] += 1
    h = f'__afh{_AW_COUNTER[0]}'
    stmts = [N.VarDecl(name=h, type_ann=None, value=_call(f'__mgco_{name}_start', args))]
    inner_body = [
        forward(cvar, _call(f'__mgco_{name}_value', [_c_ident(h)])),
        N.ContinueStmt(),
    ]
    if_wd = N.IfStmt(
        condition=_call(f'__mgco_{name}_last_yield_was_wd', [_c_ident(h)]),
        then_body=inner_body, elifs=[], else_body=None)
    bind = N.AssignStmt(target=N.IdentExpr(name=target),
                        value=_call(f'__mgco_{name}_value', [_c_ident(h)]))
    loop_body = [if_wd, bind] + body
    stmts.append(N.WhileStmt(condition=_call(f'__mgco_{name}_resume', [_c_ident(h)]),
                             body=loop_body, else_body=None))
    stmts.append(N.ExprStmt(value=_call(f'__mgco_{name}_destroy', [_c_ident(h)])))
    return stmts


def _rewrite_async_stmts(stmts: list, cvar: str) -> list:
    out = []
    for s in stmts:
        if isinstance(s, N.ReturnStmt):
            if s.value is not None:
                out.append(N.ExprStmt(value=_call(SETRET_SHIM,
                                                  [_c_ident(cvar), _rewrite_async_expr(s.value, cvar)])))
            out.append(N.ReturnStmt(value=None))
            continue
        if isinstance(s, N.ExprStmt) and isinstance(s.value, N.AwaitExpr):
            drive, _rv = _await_drive_stmts(cvar, s.value.value)
            out.extend(drive)
            continue
        if isinstance(s, N.AssignStmt) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value)
            out.extend(drive)
            out.append(N.AssignStmt(target=s.target, value=rv))
            continue
        if isinstance(s, N.VarDecl) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value)
            out.extend(drive)
            out.append(N.VarDecl(name=s.name, type_ann=None, value=rv))
            continue
        if (isinstance(s, N.ForStmt) and getattr(s, 'is_async', False)
                and _await_target_name(s.iterable) is not None):
            body = _rewrite_async_stmts([_deep_copy_stmt(b) for b in s.body], cvar)
            out.extend(_async_for_drive_stmts(cvar, s.target, s.iterable, body))
            continue
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_async_stmts(v, cvar))
            elif isinstance(v, list):
                setattr(s, k, [_rewrite_async_expr(x, cvar) if hasattr(x, '__dict__') else x for x in v])
            elif hasattr(v, '__dict__'):
                setattr(s, k, _rewrite_async_expr(v, cvar))
        out.append(s)
    return out


def _rewrite_async_gen_stmts(stmts: list, cvar: str) -> list:
    """Like _rewrite_async_stmts, but for an ASYNC GENERATOR body: real
    `yield e` goes out on the TAGGED channel with is_wd=0, and every
    await-forward on the SAME channel with is_wd=1 -- see mojo_coro.h."""
    out = []
    for s in stmts:
        if isinstance(s, N.ReturnStmt):
            if s.value is not None:
                out.append(N.ExprStmt(value=_call(SETRET_SHIM,
                                                  [_c_ident(cvar), _rewrite_async_expr(s.value, cvar)])))
            out.append(N.ReturnStmt(value=None))
            continue
        if isinstance(s, N.ExprStmt) and isinstance(s.value, N.YieldExpr):
            val = (_rewrite_async_expr(s.value.value, cvar) if s.value.value is not None
                   else N.IntLiteral(value=0))
            out.append(N.ExprStmt(value=_call('__mojo_gen_yield_tagged',
                                              [_c_ident(cvar), val, N.IntLiteral(value=0)])))
            continue
        if isinstance(s, N.ExprStmt) and isinstance(s.value, N.AwaitExpr):
            drive, _rv = _await_drive_stmts(cvar, s.value.value, forward=_forward_tagged)
            out.extend(drive)
            continue
        if isinstance(s, N.AssignStmt) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value, forward=_forward_tagged)
            out.extend(drive)
            out.append(N.AssignStmt(target=s.target, value=rv))
            continue
        if isinstance(s, N.VarDecl) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value, forward=_forward_tagged)
            out.extend(drive)
            out.append(N.VarDecl(name=s.name, type_ann=None, value=rv))
            continue
        if (isinstance(s, N.ForStmt) and getattr(s, 'is_async', False)
                and _await_target_name(s.iterable) is not None):
            body = _rewrite_async_gen_stmts([_deep_copy_stmt(b) for b in s.body], cvar)
            out.extend(_async_for_drive_stmts(cvar, s.target, s.iterable, body, forward=_forward_tagged))
            continue
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_async_gen_stmts(v, cvar))
            elif isinstance(v, list):
                setattr(s, k, [_rewrite_async_expr(x, cvar) if hasattr(x, '__dict__') else x for x in v])
            elif hasattr(v, '__dict__'):
                setattr(s, k, _rewrite_async_expr(v, cvar))
        out.append(s)
    return out


def _lower_one_async_gen(fn: N.FunctionDef, meta: list) -> N.FunctionDef:
    base = f'__mgco_{fn.name}'
    body_name = f'{base}_body'
    prologue = []
    for i, (pname, _pann) in enumerate(fn.params):
        prologue.append(N.VarDecl(name=pname, type_ann=None,
                                  value=_call(ARG_SHIM, [_c_ident(_CVAR), N.IntLiteral(value=i)])))
    new_body = prologue + _rewrite_async_gen_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR)
    body_fd = N.FunctionDef(name=body_name, params=[(_CVAR, 'Int')], return_type=None, body=new_body)
    body_fd.is_generator = False
    body_fd.is_async = False
    meta.append({
        'name': fn.name, 'struct': None, 'is_method': False, 'is_async': True,
        'is_async_gen': True,
        'base': base, 'body_name': body_name,
        'params': [_mojo_to_c_type(a) for _n, a in fn.params],
        'nargs': len(fn.params), 'value_ctype': 'int64_t', 'value_kind': 'i',
        'tuple_slot_ctypes': None,
        'defaults': list((getattr(fn, 'param_defaults', None) or {}).items()),
    })
    return body_fd


def _lower_one_async(fn: N.FunctionDef, meta: list) -> N.FunctionDef:
    base = f'__mgco_{fn.name}'
    body_name = f'{base}_body'
    prologue = []
    for i, (pname, _pann) in enumerate(fn.params):
        prologue.append(N.VarDecl(name=pname, type_ann=None,
                                  value=_call(ARG_SHIM, [_c_ident(_CVAR), N.IntLiteral(value=i)])))
    new_body = prologue + _rewrite_async_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR)
    body_fd = N.FunctionDef(name=body_name, params=[(_CVAR, 'Int')], return_type=None, body=new_body)
    body_fd.is_generator = False
    body_fd.is_async = False
    meta.append({
        'name': fn.name, 'struct': None, 'is_method': False, 'is_async': True,
        'base': base, 'body_name': body_name,
        'params': [_mojo_to_c_type(a) for _n, a in fn.params],
        'nargs': len(fn.params), 'value_ctype': 'int64_t', 'value_kind': 'i',
        'tuple_slot_ctypes': None,
        'defaults': list((getattr(fn, 'param_defaults', None) or {}).items()),
    })
    return body_fd


def _rewrite_asyncio_run(node, cvar: str | None):
    """`asyncio.run(f(...))` anywhere (typically a plain, non-async
    caller like `main`): construct f's coroutine (its bare call already
    routes through __mgco_f_start via _generator_api registration -- see
    register()), drive it to completion, and replace the whole expression
    with its return value. `cvar` is the enclosing coroutine's own __c
    when this appears inside another lowered body (None for an ordinary
    function), threaded through only so a nested case does not crash --
    asyncio.run() genuinely blocking inside a coroutine body is not a v0
    shape (kept out by _async_awaits_ok not recognizing it as an await
    target, so this path is only reached from ordinary, non-coroutine
    function bodies in practice)."""
    if node is None or not hasattr(node, '__dict__'):
        return node, []
    pre = []
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            newv = []
            for x in v:
                if hasattr(x, '__dict__'):
                    nx, npre = _rewrite_asyncio_run(x, cvar)
                    pre.extend(npre)
                    newv.append(nx)
                else:
                    newv.append(x)
            setattr(node, k, newv)
        elif hasattr(v, '__dict__'):
            nv, npre = _rewrite_asyncio_run(v, cvar)
            pre.extend(npre)
            setattr(node, k, nv)
    if _is_asyncio_run_call(node):
        call_expr, cpre = _rewrite_asyncio_run(node.args[0], cvar)
        pre.extend(cpre)
        _AW_COUNTER[0] += 1
        h = f'__arun{_AW_COUNTER[0]}'
        rv = f'__arunv{_AW_COUNTER[0]}'
        pre.append(N.VarDecl(name=h, type_ann=None, value=call_expr))
        pre.append(N.ExprStmt(value=_call('__mojo_async_run_gen', [_c_ident(h)])))
        pre.append(N.VarDecl(name=rv, type_ann=None,
                             value=_call('__mojo_gen_retval', [_c_ident(h)])))
        return _c_ident(rv), pre
    return node, pre


def _rewrite_asyncio_run_stmts(stmts: list, cvar: str | None) -> list:
    out = []
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            s.body = _rewrite_asyncio_run_stmts(s.body, cvar)
            out.append(s)
            continue
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_asyncio_run_stmts(v, cvar))
            elif isinstance(v, list):
                newv = []
                for x in v:
                    if hasattr(x, '__dict__'):
                        nx, pre = _rewrite_asyncio_run(x, cvar)
                        out.extend(pre)
                        newv.append(nx)
                    else:
                        newv.append(x)
                setattr(s, k, newv)
            elif hasattr(v, '__dict__'):
                nv, pre = _rewrite_asyncio_run(v, cvar)
                out.extend(pre)
                setattr(s, k, nv)
        out.append(s)
    return out


# ── the yield / return rewrite ─────────────────────────────────────────

def _c_ident(name: str) -> N.IdentExpr:
    return N.IdentExpr(name=name)


def _call(fn_name: str, args: list) -> N.CallExpr:
    return N.CallExpr(func=_c_ident(fn_name), args=list(args))


def _rewrite_expr(node, cvar: str, kind: str):
    """Recursively replace YieldExpr with a call to the kind-specific yield
    shim. Returns the (possibly new) node."""
    if node is None or not hasattr(node, '__dict__'):
        return node
    if isinstance(node, N.YieldExpr):
        if kind == 'tuple' and isinstance(node.value, N.TupleExpr):
            els = [_rewrite_expr(e, cvar, kind) for e in node.value.elements]
            boxed = _call(f'__mojo_tuple_box_{len(els)}', els)
            return _call('__mojo_coro_yield_i', [_c_ident(cvar), boxed])
        val = (_rewrite_expr(node.value, cvar, kind) if node.value is not None
               else N.IntLiteral(value=0))
        return _call(_yield_shim(kind), [_c_ident(cvar), val])
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            setattr(node, k, [_rewrite_expr(x, cvar, kind) if hasattr(x, '__dict__') else x
                              for x in v])
        elif hasattr(v, '__dict__'):
            setattr(node, k, _rewrite_expr(v, cvar, kind))
    return node


_yf_counter = [0]


def _rewrite_stmts(stmts: list, cvar: str, kind: str) -> list:
    out = []
    for s in stmts:
        if isinstance(s, N.ReturnStmt):
            if s.value is not None:
                out.append(N.ExprStmt(value=_call(SETRET_SHIM,
                                                  [_c_ident(cvar), _rewrite_expr(s.value, cvar, kind)])))
            out.append(N.ReturnStmt(value=None))
            continue
        if isinstance(s, N.ExprStmt) and isinstance(s.value, N.YieldFromExpr):
            # bare `yield from it`  ->  for __yfN in it: __mojo_coro_yield_k(__c, __yfN)
            # the ordinary codegen lowers the for-loop over `it` (another
            # generator, a list, a range, ...); if `it` is itself a
            # stack-switch generator this just nests coroutine calls on
            # separate stacks -- no special handling.
            _yf_counter[0] += 1
            tgt = f'__yf{_yf_counter[0]}'
            it = _rewrite_expr(s.value.value, cvar, kind)
            out.append(N.ForStmt(
                target=tgt, iterable=it,
                body=[N.ExprStmt(value=_call(_yield_shim(kind),
                                             [_c_ident(cvar), _c_ident(tgt)]))],
                else_body=None, is_async=False))
            continue
        # recurse into compound-statement bodies
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and all(hasattr(x, '__dict__') for x in v) \
                    and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_stmts(v, cvar, kind))
            elif isinstance(v, list):
                setattr(s, k, [_rewrite_expr(x, cvar, kind) if hasattr(x, '__dict__') else x for x in v])
            elif hasattr(v, '__dict__'):
                setattr(s, k, _rewrite_expr(v, cvar, kind))
        out.append(s)
    return out


_STMT_TYPES = tuple(
    getattr(N, nm) for nm in (
        'AssignStmt', 'AugAssignStmt', 'MultiAssignStmt', 'VarDecl', 'ExprStmt',
        'ReturnStmt', 'RaiseStmt', 'BreakStmt', 'ContinueStmt', 'PassStmt',
        'AssertStmt', 'IfStmt', 'WhileStmt', 'ForStmt', 'WithStmt', 'TryStmt',
        'MatchStmt', 'FunctionDef', 'ImportStmt', 'FromImportStmt', 'GlobalStmt',
        'DelStmt', 'StructDef',
    ) if hasattr(N, nm)
)


def _looks_like_stmt_list(v: list) -> bool:
    return all(isinstance(x, _STMT_TYPES) for x in v)


# ── lowering ───────────────────────────────────────────────────────────

def lower(stmts: list) -> tuple[list, list]:
    """Returns (new_stmts, coro_meta). coro_meta entries are dicts:
        {'name', 'base', 'params' (list of C types), 'value_ctype',
         'body_name', 'nargs'}
    """
    if not enabled():
        return stmts, []
    out = []
    meta = []
    method_bodies = []
    for s in stmts:
        if isinstance(s, N.FunctionDef) and getattr(s, 'is_generator', False):
            ok, _why = _eligible(s)
            if ok:
                out.append(_lower_one(s, meta))
                continue
        if isinstance(s, N.FunctionDef) and getattr(s, 'is_async', False) \
                and any(isinstance(n, N.YieldExpr) for n in _walk(s)):
            ok, _why = _eligible_async_gen(s)
            if ok:
                out.append(_lower_one_async_gen(s, meta))
                continue
        elif isinstance(s, N.FunctionDef) and getattr(s, 'is_async', False):
            ok, _why = _eligible_async(s)
            if ok:
                out.append(_lower_one_async(s, meta))
                continue
        if isinstance(s, N.StructDef):
            _kept = []
            for m in s.methods:
                if (isinstance(m, N.FunctionDef) and getattr(m, 'is_generator', False)
                        and _eligible(m, struct_name=s.name)[0]):
                    method_bodies.append(_lower_one(m, meta, struct_name=s.name))
                    # drop the generator method from the struct: gen_module's
                    # Phase 2a skips _supported_generator_methods anyway, and
                    # the body now lives as a top-level function
                else:
                    _kept.append(m)
            s.methods = _kept
        out.append(s)
    out = out + method_bodies
    out = _rewrite_asyncio_run_stmts(out, None)
    return out, meta


_CVAR = '__c'


def _mojo_to_c_type(ann: str) -> str:
    return {
        'Int': 'int64_t', 'Int64': 'int64_t', 'Int32': 'int64_t',
        'Bool': '_Bool', 'String': 'char *', 'StringLiteral': 'char *',
        '': 'int64_t', None: 'int64_t',
    }.get(ann, 'int64_t')


def _lower_one(fn: N.FunctionDef, meta: list,
               struct_name: str | None = None) -> N.FunctionDef:
    is_method = struct_name is not None
    base = (f'__mgco_{struct_name}_{fn.name}' if is_method
            else f'__mgco_{fn.name}')
    body_name = f'{base}_body'
    kind, _ = _generator_value_kind(fn)
    kind = kind or 'i'

    real_params = fn.params[1:] if is_method else fn.params
    # arg 0 is `self` for a method (a real typed body param), so ordinary
    # params start at __mojo_gen_arg index 1; else index 0.
    arg_base = 1 if is_method else 0
    prologue = []
    for i, (pname, _pann) in enumerate(real_params):
        prologue.append(N.VarDecl(name=pname, type_ann=None,
                                  value=_call(ARG_SHIM, [_c_ident(_CVAR),
                                                         N.IntLiteral(value=arg_base + i)])))

    new_body = prologue + _rewrite_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR, kind)
    body_params = [(_CVAR, 'Int')]
    if is_method:
        body_params.append(('self', struct_name))
    body_fd = N.FunctionDef(
        name=body_name,
        params=body_params,
        return_type=None,
        body=new_body,
    )
    body_fd.is_generator = False
    body_fd.is_async = False

    c_params = ([f'{struct_name} *'] if is_method else []) + \
               [_mojo_to_c_type(a) for _n, a in real_params]
    meta.append({
        'name': fn.name,
        'struct': struct_name,
        'is_method': is_method,
        'base': base,
        'body_name': body_name,
        'params': c_params,
        'nargs': len(real_params),
        'value_ctype': _KIND_CTYPE[kind],
        'value_kind': kind,
        'tuple_slot_ctypes': _generator_tuple_slots(fn) if kind == 'tuple' else None,
        'defaults': list((getattr(fn, 'param_defaults', None) or {}).items()),
    })
    return body_fd


def _deep_copy_stmt(node):
    """Shallow structural clone so rewrites don't mutate the original AST
    (the same FunctionDef object can be walked again elsewhere)."""
    import copy
    return copy.deepcopy(node)


# ── registration + C emission ─────────────────────────────────────────

_C_TRAMPOLINE_TMPL = """
/* --- stack-switch coroutine trampolines for generator {name!r} --- */
extern int64_t {new_fn} ({new_params});
extern int64_t __mojo_gen_resume (int64_t, int64_t);
extern int64_t __mojo_gen_value (int64_t);
extern void    __mojo_gen_destroy (int64_t);
extern void    {body_name} (int64_t{body_extra});
/* value_kind={value_kind} */

MojoGenerator *{base}_start ({start_params}) {{
  int64_t __g = {new_fn} ((int64_t)(&{body_name}){arg_fwd});
  return (MojoGenerator *)__g;
}}
_Bool {base}_resume (MojoGenerator *__g) {{
  return (_Bool)__mojo_gen_resume ((int64_t)__g, 0);
}}
{value_ctype} {base}_value (MojoGenerator *__g) {{
  return {value_unbox};
}}
void {base}_destroy (MojoGenerator *__g) {{
  __mojo_gen_destroy ((int64_t)__g);
}}
{last_yield_fn}
"""

_LAST_YIELD_TMPL = """extern int64_t __mojo_gen_last_yield_was_wd (int64_t);
_Bool {base}_last_yield_was_wd (MojoGenerator *__g) {{
  return (_Bool)__mojo_gen_last_yield_was_wd ((int64_t)__g);
}}
"""


def emit_c(meta_entry: dict) -> str:
    n = meta_entry['nargs']
    params = meta_entry['params']            # includes leading 'Struct *' for a method
    is_method = meta_entry.get('is_method')
    kind = meta_entry.get('value_kind', 'i')
    vct = _KIND_CTYPE[kind]
    nslots = len(params)                     # start-fn arg count (self + real args)
    start_params = ', '.join(f'{ct} __a{i}' for i, ct in enumerate(params)) or 'void'
    arg_fwd = ''.join(f', (int64_t)__a{i}' for i in range(nslots))
    new_params = ', '.join(['int64_t'] + ['int64_t'] * nslots)
    new_fn = (f'__mojo_gen_new_m{nslots - 1}' if is_method
              else f'__mojo_gen_new_{nslots}')
    if kind == 'p':
        value_unbox = f'({vct})__mojo_gen_value ((int64_t)__g)'
    elif kind == 'tuple':
        value_unbox = '(MojoList *)__mojo_gen_value ((int64_t)__g)'
    elif kind == 'd':
        value_unbox = ('({ double __d; long long __b = __mojo_gen_value ((int64_t)__g); '
                       '__builtin_memcpy(&__d, &__b, sizeof __d); __d; })')
    else:
        value_unbox = '__mojo_gen_value ((int64_t)__g)'
    body_extra = f', {meta_entry["struct"]} *' if is_method else ''
    last_yield_fn = (_LAST_YIELD_TMPL.format(base=meta_entry['base'])
                     if meta_entry.get('is_async_gen') else '')
    return _C_TRAMPOLINE_TMPL.format(
        name=meta_entry['name'], base=meta_entry['base'], last_yield_fn=last_yield_fn,
        body_name=meta_entry['body_name'], new_fn=new_fn, value_kind=kind,
        value_ctype=vct, value_unbox=value_unbox, body_extra=body_extra,
        start_params=start_params, arg_fwd=arg_fwd, new_params=new_params,
    )


def register(gen, meta: list) -> None:
    """Populate gen so the ordinary generator-call / for / next consumers
    treat each lowered generator exactly like a cpp-path one."""
    if not meta:
        return
    units = getattr(gen, '_stackswitch_coro_c_units', None)
    if units is None:
        units = gen._stackswitch_coro_c_units = []
    # Declared param types for the body-called shims so _emit_call coerces a
    # char*/pointer/double yield value to the int64_t the shim takes,
    # instead of emitting a raw "makes integer from pointer" call.
    gen.func_param_types.setdefault('__mojo_coro_yield_i', ['int64_t', 'int64_t'])
    gen.func_param_types.setdefault('__mojo_coro_yield_d', ['int64_t', 'double'])
    gen.func_param_types.setdefault('__mojo_gen_arg', ['int64_t', 'int64_t'])
    gen.func_param_types.setdefault('__mojo_gen_set_return', ['int64_t', 'int64_t'])
    for _k in range(2, 9):
        gen.func_param_types.setdefault(f'__mojo_tuple_box_{_k}', ['int64_t'] * _k)
        gen.func_return_types.setdefault(f'__mojo_tuple_box_{_k}', 'int64_t')
    # await/asyncio.run shims -- registered unconditionally (cheap; a call
    # to asyncio.run(<imported async fn>()) can appear in a module with no
    # async def of its own, so gating this on `meta` containing an
    # is_async entry would miss it).
    gen.func_param_types.setdefault('__mojo_async_await_sleep', ['int64_t', 'double'])
    gen.func_return_types.setdefault('__mojo_async_await_sleep', 'void')
    gen.func_param_types.setdefault('__mojo_async_await_sock_recv', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_async_await_sock_recv', 'int64_t')
    gen.func_param_types.setdefault('__mojo_gen_retval', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_retval', 'int64_t')
    gen.func_param_types.setdefault('__mojo_async_run_gen', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_async_run_gen', 'void')
    for m in meta:
        api = {
            'base': m['base'],
            'value_ctype': m['value_ctype'],
            'params': m['params'],
            'tuple_slot_ctypes': m.get('tuple_slot_ctypes'),
            'has_return_value': True,
            'is_async_gen': m.get('is_async_gen', False),
        }
        if m.get('defaults'):
            api['defaults'] = m['defaults']
        if m.get('is_method'):
            gen._generator_method_api[(m['struct'], m['name'])] = api
            gen._supported_generator_methods[(m['struct'], m['name'])] = None
        else:
            gen._generator_api[m['name']] = api
            # skip ordinary emission for the bare name + emit the extern block
            gen._supported_generators[m['name']] = None
        # the body must keep its exact name (the trampoline calls it) --
        # opt it out of overload-suffix mangling
        gen._extra_no_mangle.add(m['body_name'])
        gen.func_param_types[f"{m['base']}_start"] = m['params']
        gen.func_return_types[f"{m['base']}_start"] = 'MojoGenerator *'
        gen.func_return_types[f"{m['base']}_resume"] = '_Bool'
        gen.func_return_types[f"{m['base']}_value"] = m['value_ctype']
        gen.func_return_types[f"{m['base']}_destroy"] = 'void'
        if m.get('is_async_gen'):
            gen.func_return_types[f"{m['base']}_last_yield_was_wd"] = '_Bool'
            gen.func_param_types[f"{m['base']}_last_yield_was_wd"] = ['MojoGenerator *']
            gen.func_param_types.setdefault('__mojo_gen_yield_tagged', ['int64_t', 'int64_t', 'int64_t'])
            gen.func_return_types.setdefault('__mojo_gen_yield_tagged', 'int64_t')
            gen.func_param_types.setdefault('__mojo_gen_last_yield_was_wd', ['int64_t'])
            gen.func_return_types.setdefault('__mojo_gen_last_yield_was_wd', 'int64_t')
        units.append(emit_c(m))
