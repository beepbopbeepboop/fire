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

YIELD_SHIM   = '__mojo_coro_yield_i'
ARG_SHIM     = '__mojo_gen_arg'
SETRET_SHIM  = '__mojo_gen_set_return'


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


def _eligible(fn: N.FunctionDef) -> tuple[bool, str]:
    if fn.is_async:
        return False, 'async'
    if getattr(fn, 'comptime_params', None):
        return False, 'comptime params'
    if getattr(fn, 'decorators', None):
        return False, 'decorated'
    # v0: no `yield from`, no nested generator defs, no yield in a nested def
    for n in _walk(fn):
        if isinstance(n, N.YieldFromExpr):
            return False, 'yield from (v0)'
    # v0: params must be simple positional scalars (or none)
    for pname, pann in fn.params:
        if pann not in _SCALARISH:
            return False, f'param {pname!r} type {pann!r} (v0 scalar-only)'
    if getattr(fn, 'kwonly', None):
        return False, 'kwonly params (v0)'
    return True, ''


# ── the yield / return rewrite ─────────────────────────────────────────

def _c_ident(name: str) -> N.IdentExpr:
    return N.IdentExpr(name=name)


def _call(fn_name: str, args: list) -> N.CallExpr:
    return N.CallExpr(func=_c_ident(fn_name), args=list(args))


def _rewrite_expr(node, cvar: str):
    """Recursively replace YieldExpr with a call to the yield shim. Returns
    the (possibly new) node."""
    if node is None or not hasattr(node, '__dict__'):
        return node
    if isinstance(node, N.YieldExpr):
        val = _rewrite_expr(node.value, cvar) if node.value is not None else N.IntLiteral(value=0)
        return _call(YIELD_SHIM, [_c_ident(cvar), val])
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            setattr(node, k, [_rewrite_expr(x, cvar) if hasattr(x, '__dict__') else x
                              for x in v])
        elif hasattr(v, '__dict__'):
            setattr(node, k, _rewrite_expr(v, cvar))
    return node


def _rewrite_stmts(stmts: list, cvar: str) -> list:
    out = []
    for s in stmts:
        if isinstance(s, N.ReturnStmt):
            if s.value is not None:
                out.append(N.ExprStmt(value=_call(SETRET_SHIM,
                                                  [_c_ident(cvar), _rewrite_expr(s.value, cvar)])))
            out.append(N.ReturnStmt(value=None))
            continue
        # recurse into compound-statement bodies
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and all(hasattr(x, '__dict__') for x in v) \
                    and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_stmts(v, cvar))
            elif isinstance(v, list):
                setattr(s, k, [_rewrite_expr(x, cvar) if hasattr(x, '__dict__') else x for x in v])
            elif hasattr(v, '__dict__'):
                setattr(s, k, _rewrite_expr(v, cvar))
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
    for s in stmts:
        if isinstance(s, N.FunctionDef) and getattr(s, 'is_generator', False):
            ok, _why = _eligible(s)
            if ok:
                out.append(_lower_one(s, meta))
                continue
        out.append(s)
    return out, meta


_CVAR = '__c'


def _mojo_to_c_type(ann: str) -> str:
    return {
        'Int': 'int64_t', 'Int64': 'int64_t', 'Int32': 'int64_t',
        'Bool': '_Bool', 'String': 'char *', 'StringLiteral': 'char *',
        '': 'int64_t', None: 'int64_t',
    }.get(ann, 'int64_t')


def _lower_one(fn: N.FunctionDef, meta: list) -> N.FunctionDef:
    base = f'__mgco_{fn.name}'
    body_name = f'{base}_body'

    # prologue: var p_i = __mojo_gen_arg(__c, i)
    prologue = []
    for i, (pname, _pann) in enumerate(fn.params):
        prologue.append(N.VarDecl(name=pname, type_ann=None,
                                  value=_call(ARG_SHIM, [_c_ident(_CVAR), N.IntLiteral(value=i)])))

    new_body = prologue + _rewrite_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR)
    # a plain function returning nothing
    body_fd = N.FunctionDef(
        name=body_name,
        params=[(_CVAR, 'Int')],
        return_type=None,
        body=new_body,
    )
    body_fd.is_generator = False
    body_fd.is_async = False

    meta.append({
        'name': fn.name,
        'base': base,
        'body_name': body_name,
        'params': [_mojo_to_c_type(a) for _n, a in fn.params],
        'value_ctype': 'int64_t',   # v0
        'nargs': len(fn.params),
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
extern int64_t __mojo_gen_new_{nargs} ({new_params});
extern int64_t __mojo_gen_resume (int64_t, int64_t);
extern int64_t __mojo_gen_value (int64_t);
extern void    __mojo_gen_destroy (int64_t);
extern void    {body_name} (int64_t);

MojoGenerator *{base}_start ({start_params}) {{
  int64_t __g = __mojo_gen_new_{nargs} ((int64_t)(&{body_name}){arg_fwd});
  return (MojoGenerator *)__g;
}}
_Bool {base}_resume (MojoGenerator *__g) {{
  return (_Bool)__mojo_gen_resume ((int64_t)__g, 0);
}}
int64_t {base}_value (MojoGenerator *__g) {{
  return __mojo_gen_value ((int64_t)__g);
}}
void {base}_destroy (MojoGenerator *__g) {{
  __mojo_gen_destroy ((int64_t)__g);
}}
"""


def emit_c(meta_entry: dict) -> str:
    n = meta_entry['nargs']
    params = meta_entry['params']
    start_params = ', '.join(f'{ct} __a{i}' for i, ct in enumerate(params)) or 'void'
    arg_fwd = ''.join(f', (int64_t)__a{i}' for i in range(n))
    new_params = ', '.join(['int64_t'] + ['int64_t'] * n)
    return _C_TRAMPOLINE_TMPL.format(
        name=meta_entry['name'], base=meta_entry['base'],
        body_name=meta_entry['body_name'], nargs=n,
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
    for m in meta:
        api = {
            'base': m['base'],
            'value_ctype': m['value_ctype'],
            'params': m['params'],
            'tuple_slot_ctypes': None,
            'has_return_value': True,
        }
        if m.get('defaults'):
            api['defaults'] = m['defaults']
        gen._generator_api[m['name']] = api
        # mark as a "supported generator" so gen_module skips ordinary
        # emission for the bare name and emits the extern decl block
        gen._supported_generators[m['name']] = None
        # the body must keep its exact name (the trampoline calls it) --
        # opt it out of overload-suffix mangling
        gen._extra_no_mangle.add(m['body_name'])
        gen.func_param_types[f"{m['base']}_start"] = m['params']
        gen.func_return_types[f"{m['base']}_start"] = 'MojoGenerator *'
        gen.func_return_types[f"{m['base']}_resume"] = '_Bool'
        gen.func_return_types[f"{m['base']}_value"] = m['value_ctype']
        gen.func_return_types[f"{m['base']}_destroy"] = 'void'
        units.append(emit_c(m))
