"""gimple_gen_coro.py -- Layer 1 of the A3 stack-switch coroutine codegen
(doc/COROUTINE.html §5.4).

An AST pre-pass, run in gimple_codegen._run_pipeline right after
ast_rewriter.rewrite. This is the DEFAULT generator/async backend as of
doc/COROUTINE.html §5.5 (the cutover) -- MOJO_CORO=cpp opts back into the
old gimple_cpp_*.py C++20-coroutine emitter for one release as a
differential oracle; MOJO_CORO=stackswitch (or simply unset) selects this
path. For each eligible top-level generator FunctionDef `g` it:

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

import fire_compiler as N
# `_is_asyncio_sleep_call`/`_is_asyncio_sock_recv_call` used to be defined
# a second time here, byte-for-byte the same structural check as gimple_
# exprtypes.py's own (the cpp-path's identical `asyncio.sleep`/`sock_recv`
# call-shape recognizers) -- two top-level functions in two different
# `.py` siblings sharing the exact same bare name collided under a single
# self-hosted whole-program compile (fire.py compiling its own source):
# both got attributed to whichever module's `_compile_imported_module`
# pass reached the shared-by-bare-name `_imported_func_home` entry FIRST,
# so both ended up mangled to the SAME C symbol -- a GCC "redefinition"
# error invisible to every other test (they never inline the whole
# self-hosting closure the way `make check-selfhost`/`make bootstrap` do).
# Reusing gimple_exprtypes.py's copy (its own is slightly stricter --
# rejects a kwarg-form call, which this module's own args[0]-indexing
# `_await_drive_stmts` needs anyway) fixes the collision at the root
# instead of just renaming around it, per this project's own "consolidate
# duplicates" convention.
from gimple_exprtypes import _is_asyncio_sleep_call, _is_asyncio_sock_recv_call
import gimple_ctypes

_ENV = 'MOJO_CORO'
_MODE = 'stackswitch'
_OLD_MODE = 'cpp'

ARG_SHIM     = '__mojo_gen_arg'
SETRET_SHIM  = '__mojo_gen_set_return'
_KIND_CTYPE  = {'i': 'int64_t', 'p': 'char *', 'd': 'double', 'tuple': 'MojoList *'}


def _yield_shim(kind: str) -> str:
    # int/pointer both go through the int64_t yield -- _emit_call coerces a
    # char*/pointer arg to int64_t via the registered param types. Only a
    # genuine double needs the bitcast variant.
    return '__mojo_coro_yield_d' if kind == 'd' else '__mojo_coro_yield_i'


def enabled() -> bool:
    # §5.5 cutover: stack-switch is now the DEFAULT (unset, or explicitly
    # MOJO_CORO=stackswitch) -- MOJO_CORO=cpp is the escape hatch back to
    # the old gimple_cpp_*.py C++20-coroutine emitter, kept live for one
    # release as a differential oracle (doc/COROUTINE.html §5.5/§5.6).
    return os.environ.get(_ENV, _MODE) != _OLD_MODE


# ── eligibility ─────────────────────────────────────────────────────────

def _walk(node):
    """Return node and every AST descendant (attributes + list attributes),
    as a list, in the same pre-order sequence a recursive `yield`/`yield
    from` walk would produce.

    Deliberately NOT a generator (it used to be): a `yield`/`yield from`
    function compiles to a REAL stack-switching coroutine in this
    codegen, and this runtime's own docs (runtime/fire_runtime.h) already
    flag that "a coroutine body can't use setjmp/longjmp directly" — a
    `mojo_raise()` firing (from a try/except ELSEWHERE in this compiler's
    own pipeline) while this walk is mid-iteration can longjmp across
    that coroutine's own separate fiber stack — undefined behavior.
    Found and fixed via bugs/CODEGEN_noshim_dumpfull_preexisting_
    divergence.md: this exact function, compiled to `__mgco__walk_body`,
    was caught live in lldb suspended mid-yield at the moment a
    zip()-nested-tuple `ValueError` (meant to be caught locally by
    `_gen_stmt_ForStmt`'s try/except and fall back gracefully) instead
    escaped all the way to the module-level handler — only when this
    compiler self-hosted. See `gimple_gen_stmts._iter_ast`'s identical
    fix (same bug, sibling function) for the fuller writeup.

    None of this function's many call sites need laziness (each one -
    `for`/`sum(1 for ...)`/`any(... for ...)` - fully consumes the
    result), so building a real list up front with an explicit stack
    avoids the coroutine machinery entirely for this internal walk."""
    result = []
    stack = [node]
    while stack:
        cur = stack.pop()
        result.append(cur)
        d = getattr(cur, '__dict__', None)
        if not d:
            continue
        children = []
        for v in d.values():
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, '__dict__'):
                        children.append(x)
            elif hasattr(v, '__dict__'):
                children.append(v)
        # Push in reverse so children still pop (and thus visit their
        # own full subtrees) in original left-to-right order.
        stack.extend(reversed(children))
    return result


_SCALARISH = {'Int', 'Int64', 'Int32', 'Bool', 'String', 'StringLiteral', '', None,
             'int', 'bool', 'str', 'float'}


_FLOAT_ANNS  = {'Float64', 'Float32', 'Float16', 'Float', 'float', 'Float64Literal'}
_STRING_ANNS = {'String', 'StringLiteral', 'StringSlice', 'str'}
_INT_ANNS    = {'Int', 'Int64', 'Int32', 'Int16', 'Int8', 'UInt', 'UInt64', 'UInt32',
                'Bool', 'int', 'bool'}


def _ann_kind(ann) -> str | None:
    """Map a (purely syntactic) parameter / field type annotation to a yield
    C kind ('i'/'p'/'d'), or None when the annotation is missing or not a
    recognised scalar. `ann` is normally the annotation *string* carried in
    FunctionDef.params / VarDecl.type_ann, but tolerate an IdentExpr node."""
    if ann is None:
        return None
    if not isinstance(ann, str):
        ann = getattr(ann, 'name', None)
        if not isinstance(ann, str):
            return None
    if ann in _FLOAT_ANNS:
        return 'd'
    if ann in _STRING_ANNS:
        return 'p'
    if ann in _INT_ANNS:
        return 'i'
    return None


def _literal_kind(expr) -> str | None:
    """Kind of a bare literal expression, or ('list', elem_kind) for a list
    display of homogeneous literal elements. None when not a literal."""
    if isinstance(expr, (N.StringLiteral, N.TstringLiteral)):
        return 'p'
    if isinstance(expr, N.FloatLiteral):
        return 'd'
    if isinstance(expr, (N.IntLiteral, N.BoolLiteral)):
        return 'i'
    if isinstance(expr, N.ListExpr):
        eks = {_literal_kind(e) for e in expr.elements}
        eks.discard(None)
        if len(eks) == 1:
            k = list(eks)[0]
            if isinstance(k, str):
                return ('list', k)
    return None


def _static_env(fn: N.FunctionDef, struct_def=None) -> dict:
    """Best-effort, purely-syntactic name -> yield-kind map available to the
    Layer-1 pre-pass (before GimpleGen / struct_field_types exist):

      * `fn`'s own parameter type annotations         -> env['<param>']
      * `fn`'s local `name = <literal>` / `name = [literals]` assignments
                                                      -> env['<local>']
      * for a generator METHOD, the enclosing struct's field types, taken
        from class-body annotations and from `__init__`'s
        `self.<f> = <annotated-param-or-literal>` assignments
                                                      -> env['self.<field>']

    Values are 'i'/'p'/'d', or ('list', elem_kind) for a list-typed local."""
    env: dict = {}
    for pname, pann in getattr(fn, 'params', []):
        k = _ann_kind(pann)
        if k is not None:
            env[pname] = k
    # Fill unannotated params from the unanimous cross-call-site kind
    # contract (bugs/hard/CODEGEN_coro_stackswitch_yield_kind_identifier_
    # inference.md repro 1: `def g(x): yield x` called only `g(3.5)`).
    for pname, k in _CALLSITE_PARAM_KINDS.get(getattr(fn, 'name', None), {}).items():
        env.setdefault(pname, k)
    list_elem: dict = {}   # local name -> {elem kinds seen via `= [...]` / .append(...)}
    for n in _walk(fn):
        tgt = val = ann = None
        if isinstance(n, N.AssignStmt) and isinstance(n.target, N.IdentExpr):
            tgt, val, ann = n.target.name, n.value, getattr(n, 'type_ann', None)
        elif isinstance(n, N.VarDecl):
            tgt, val, ann = n.name, n.value, n.type_ann
        if tgt is not None:
            k = _ann_kind(ann)
            if k is None:
                k = _literal_kind(val)
            if k is None and val is not None:
                k = _yield_kind(val)          # BinaryOp / literal fallthrough
            # `it = iter(<list-local>)` — carry the source list's element
            # kind onto the iterator local, so `yield next(it)` /
            # `for x in it:` in the body resolve their yield-kind (string /
            # float payloads would otherwise silently truncate to int64_t).
            if (k is None and isinstance(val, N.CallExpr)
                    and isinstance(val.func, N.IdentExpr) and val.func.name == 'iter'
                    and len(val.args) == 1 and isinstance(val.args[0], N.IdentExpr)):
                _src = val.args[0].name
                _sv = env.get(_src)
                if isinstance(_sv, tuple) and _sv[0] == 'list':
                    k = _sv
                elif len(list_elem.get(_src, ())) == 1:
                    k = ('list', list(list_elem[_src])[0])
            if isinstance(k, tuple) and k[0] == 'list':
                list_elem.setdefault(tgt, set()).add(k[1])
            elif isinstance(k, str):
                env.setdefault(tgt, k)
        # `<name>.append(<literal>)` refines a list-local's element kind
        if (isinstance(n, N.CallExpr) and isinstance(n.func, N.MemberExpr)
                and n.func.member in ('append', 'insert')
                and isinstance(n.func.obj, N.IdentExpr) and n.args):
            ek = _literal_kind(n.args[-1])
            if isinstance(ek, str):
                list_elem.setdefault(n.func.obj.name, set()).add(ek)
    for nm, eks in list_elem.items():
        if len(eks) == 1 and nm not in env:
            env[nm] = ('list', list(eks)[0])
    # `for <v> in <list-local-or-literal>:` binds <v> to the element kind
    for n in _walk(fn):
        if not isinstance(n, N.ForStmt):
            continue
        tname = n.target.name if isinstance(n.target, N.IdentExpr) \
            else (n.target if isinstance(n.target, str) else None)
        if tname is None or tname in env:
            continue
        it = n.iterable
        ek = None
        if isinstance(it, N.IdentExpr):
            v = env.get(it.name)
            if isinstance(v, tuple) and v[0] == 'list':
                ek = v[1]
        else:
            lk = _literal_kind(it)
            if isinstance(lk, tuple) and lk[0] == 'list':
                ek = lk[1]
        if isinstance(ek, str):
            env[tname] = ek
    if struct_def is not None:
        for f in getattr(struct_def, 'fields', []):
            if isinstance(f, N.VarDecl):
                k = _ann_kind(getattr(f, 'type_ann', None))
                if k is not None:
                    env[f'self.{f.name}'] = k
        init = next((m for m in getattr(struct_def, 'methods', [])
                     if isinstance(m, N.FunctionDef) and m.name == '__init__'), None)
        if init is not None:
            pann_by_name = {p: a for p, a in init.params}
            for n in _walk(init):
                if (isinstance(n, N.AssignStmt)
                        and isinstance(n.target, N.MemberExpr)
                        and isinstance(n.target.obj, N.IdentExpr)
                        and n.target.obj.name == 'self'):
                    fld = f'self.{n.target.member}'
                    k = _ann_kind(getattr(n, 'type_ann', None))
                    if k is None and isinstance(n.value, N.IdentExpr):
                        k = _ann_kind(pann_by_name.get(n.value.name))
                    if k is None:
                        k = _literal_kind(n.value)
                    if k is not None and not isinstance(k, tuple):
                        env.setdefault(fld, k)
    return env


def _yield_kind(expr, env: dict | None = None) -> str | None:
    """Best-effort C kind of a yielded value: 'i' int/bool/pointer (the
    yield call always coerces to int64_t, so 'i' vs 'p' only affects the
    <base>_value RETURN type), 'p' string pointer, 'd' float, 'tuple' a
    tuple literal (not handled yet). None == can't tell (treated as 'i').

    `env` (from `_static_env`) resolves a bare identifier / `self.<field>` /
    `<list-local>[idx]` reference to a kind when a syntactic type source is
    in reach -- without it those all fall through to None (== 'i'), which
    silently truncated float/string yields (bugs/hard/CODEGEN_coro_
    stackswitch_yield_kind_identifier_inference.md)."""
    env = env or {}
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
    if isinstance(expr, N.IdentExpr):
        v = env.get(expr.name)
        return v if isinstance(v, str) else None
    if isinstance(expr, N.MemberExpr) and isinstance(expr.obj, N.IdentExpr) \
            and expr.obj.name == 'self':
        return env.get(f'self.{expr.member}')
    if isinstance(expr, N.SubscriptExpr) and isinstance(expr.obj, N.IdentExpr):
        v = env.get(expr.obj.name)
        if isinstance(v, tuple) and v[0] == 'list':
            return v[1]
        return None
    # `next(it)` / `next(it, default)` where `it` was bound by
    # `it = iter(<list-local>)` — the element kind carried onto `it` in
    # `_static_env` (as a ('list', kind) entry) is this expression's kind.
    if (isinstance(expr, N.CallExpr) and isinstance(expr.func, N.IdentExpr)
            and expr.func.name == 'next' and expr.args
            and isinstance(expr.args[0], N.IdentExpr)):
        v = env.get(expr.args[0].name)
        if isinstance(v, tuple) and v[0] == 'list':
            return v[1]
        return None
    if isinstance(expr, N.TernaryExpr):
        tk, ek = _yield_kind(expr.then_val, env), _yield_kind(expr.else_val, env)
        if tk == ek:
            return tk
        if 'p' in (tk, ek):
            return 'p'
        if 'd' in (tk, ek):
            return 'd'
        return None
    if isinstance(expr, N.BinaryOp):
        lk, rk = _yield_kind(expr.left, env), _yield_kind(expr.right, env)
        if 'p' in (lk, rk):
            return 'p'
        if 'd' in (lk, rk):
            return 'd'
        return 'i'
    return None


_KIND_TO_SLOT_CTYPE = {'i': 'int64_t', 'p': 'char *', 'd': 'double', None: 'int64_t'}


def _generator_tuple_slots(fn: N.FunctionDef, env: dict | None = None):
    """If every `yield` in `fn` yields a tuple LITERAL of the same arity,
    return the per-slot C type list; else None. Used only when
    _generator_value_kind says 'tuple'."""
    shapes = []
    for n in _walk(fn):
        if isinstance(n, N.YieldExpr):
            if not isinstance(n.value, N.TupleExpr):
                return None
            shapes.append(tuple(_yield_kind(e, env) for e in n.value.elements))
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
        # avoid next(iter(...)) -- a known self-host miscompile trigger
        # (see project memory: "next(iter(...)) -> _next undefined-symbol
        # regression"); a plain list index compiles cleanly instead.
        k = list(kinds)[0] if kinds else None
        if k == 'tuple':
            # A nested tuple literal in a slot (Lib/modulefinder.py's
            # `yield "store", (name,)` / `yield "relative_import", (level,
            # fromlist, name)`) would box recursively into its own
            # MojoList *, but the consumer side has no channel to recover
            # the INNER elements' types (they are heterogeneous across
            # sites: str / list / int), so `for x in args:` / `a, b = args`
            # in the consumer body reads raw pointer bits. Refuse honestly
            # rather than silently miscompile -- see
            # bugs/CODEGEN_generator_function_Lib_modulefinder.md.
            return None            # nested tuple in a slot -- needs a tagged inner value model
        slots.append(_KIND_TO_SLOT_CTYPE[k])
    return slots


def _generator_value_kind(fn: N.FunctionDef,
                          env: dict | None = None) -> tuple[str | None, str]:
    kinds = set()
    has_tuple = has_nontuple = False
    for n in _walk(fn):
        if isinstance(n, N.YieldExpr):
            k = _yield_kind(n.value, env)
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
        return ('tuple', '') if _generator_tuple_slots(fn, env) is not None \
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


def _lambdas_ok(fn: N.FunctionDef) -> bool:
    """A `lambda` literal in the body is fine -- the desugared body is
    ordinary code and the ordinary codegen path lifts it to a top-level C
    function -- EXCEPT for shapes that path miscompiles: a `*args`/
    `**kwargs` parameter (emits a broken forward declaration) or a
    parameter with a default value (silently reads garbage for the
    defaulted slot). Refuse those so the module falls through to the cpp
    path's own honest refusal instead of emitting broken/wrong C.
    (bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md)"""
    for n in _walk(fn):
        if isinstance(n, N.LambdaExpr):
            for pname, pdefault in n.params:
                if pname.startswith('*') or pdefault is not None:
                    return False
    return True


def _own_property_names(struct_def) -> set:
    """Names of `@property` getter methods directly on `struct_def`."""
    out = set()
    for m in getattr(struct_def, 'methods', []) or []:
        if isinstance(m, N.FunctionDef) and 'property' in (getattr(m, 'decorators', None) or []):
            out.add(m.name)
    return out


def _seed_prop_names(stmts: list) -> dict:
    """`{struct name: set of @property getter names}`, INCLUDING those
    inherited from base classes defined in the same module. Returned as a
    plain local (threaded through `_eligible`/`_property_call_ok`) rather
    than stashed in a module global — a `NAME = {}` module-level dict has no
    write accessor on the self-hosted compiled path, so `_PROP_NAMES[k] = v`
    there was a NULL-dict store (`mojo_dict_set_int` SIGBUS in
    `_seed_prop_names` under `MOJO_NO_SHIM=1`)."""
    _pn: dict = {}
    defs = {s.name: s for s in stmts if isinstance(s, N.StructDef)}
    for name, sd in defs.items():
        seen = set()
        stack = [name]
        acc = set()
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in defs:
                continue
            seen.add(cur)
            acc |= _own_property_names(defs[cur])
            for b in (getattr(defs[cur], 'bases', None) or []):
                bn = b if isinstance(b, str) else getattr(b, 'name', None)
                if bn:
                    stack.append(bn)
        _pn[name] = acc
    return _pn


def _property_call_ok(fn: N.FunctionDef, struct_name, struct_def,
                      prop_names: dict | None = None) -> bool:
    """Refuse a generator method whose body *calls* the result of a
    `@property` getter -- `self.<prop>(args)` where `<prop>` is a property
    (Lib/ipaddress.py's `self._address_class(x)`: `_address_class` is a
    `@property` returning a class object, then invoked to construct an
    address). The ordinary call-lowering the A3 body shares mis-lowers this
    as a direct method call `Struct__prop(self, args)` (arity 2 vs the
    getter's 1) -- broken C, a real miscompile. No support for a
    property-returned callable value exists; refuse honestly so the module
    falls through to the cpp path's own refusal instead of emitting broken
    code."""
    if struct_def is None:
        return True
    props = ((prop_names.get(struct_name) if prop_names else None)
             or _own_property_names(struct_def))
    if not props:
        return True
    for n in _walk(fn):
        if (isinstance(n, N.CallExpr) and isinstance(n.func, N.MemberExpr)
                and isinstance(n.func.obj, N.IdentExpr)
                and n.func.obj.name in ('self', 'cls')
                and n.func.member in props):
            return False
    return True


def _eligible(fn: N.FunctionDef, struct_name: str | None = None,
              struct_def=None, prop_names: dict | None = None) -> tuple[bool, str]:
    if fn.is_async:
        return False, 'async'
    if getattr(fn, 'comptime_params', None):
        return False, 'comptime params'
    _decos = getattr(fn, 'decorators', None) or []
    # v0: a @classmethod generator METHOD is accepted (its `cls` receiver
    # is an opaque, never-read int64_t placeholder slot -- the same ABI
    # the cpp path used and the call-site machinery in
    # gimple_gen_methods.py already resolves, both for `Cls.gen(...)` and
    # `cls.gen(...)`). Any other decorator, or a @classmethod on a plain
    # (non-method) generator, still falls through.
    if _decos:
        if struct_name is not None and _decos == ['classmethod']:
            if any(isinstance(n, (N.IdentExpr, N.MemberExpr))
                   and getattr(n, 'name', None) == 'cls'
                   for n in _walk(fn)):
                return False, 'classmethod generator body references `cls` (v0)'
        else:
            return False, 'decorated'
    if not _yield_from_ok(fn):
        return False, 'yield from with return-value capture (v0)'
    if not _lambdas_ok(fn):
        return False, 'lambda with *args/**kwargs or a default parameter'
    if not _property_call_ok(fn, struct_name, struct_def, prop_names):
        return False, 'calls the result of a @property getter (v0)'
    params = fn.params
    _is_cm = False
    if struct_name is not None:
        _is_cm = _decos == ['classmethod']
        _want = 'cls' if _is_cm else 'self'
        if not params or params[0][0] != _want:
            return False, f'generator method without a plain `{_want}` first param (v0)'
        params = params[1:]   # self/cls is handled by the codegen
    if _is_cm:
        # The newly-accepted @classmethod path is deliberately narrower
        # than the long-standing `self`/free-function one: a `str`/`String`
        # param is nominally in `_SCALARISH` but actually crosses as a
        # `char *` pointer whose bits `__mojo_gen_arg` hands back as a bare
        # int64_t -- string ops on it (`len`, iteration) then operate on
        # the raw address. Accept only genuinely-numeric or unannotated
        # params here (an unannotated bytes/memoryview source still works:
        # the body's `memoryview(x)` / `bytes(x)` constructor re-casts the
        # pointer bits itself -- zipfile `_Extra.split`).
        for pname, pann in params:
            if pann not in (None, '') and pann not in _INT_ANNS and pann not in _FLOAT_ANNS:
                return False, (f'@classmethod generator param {pname!r} type '
                               f'{pann!r} (v0: numeric or unannotated only)')
    # v0: remaining params must be simple positional scalars (or none)
    for pname, pann in params:
        if pann not in _SCALARISH:
            return False, f'param {pname!r} type {pann!r} (v0 scalar-only)'
    if getattr(fn, 'kwonly', None):
        return False, 'kwonly params (v0)'
    kind, why = _generator_value_kind(fn, _static_env(fn, struct_def))
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

# name -> [param names in order], for every top-level async/generator def
# in the module CURRENTLY being lowered -- populated fresh at the start of
# each lower() call (never carries over between modules) so a keyword-
# argument await/create_task target (`await f(should_fail=True)`) can be
# resolved to the right positional slot. Same-module only, matching
# _await_target_name's own "bare top-level name" scope.
_PARAM_NAMES: dict[str, list[str]] = {}

# Generator/async-def name -> {unannotated-param-name: yield-kind ('i'/'p'/'d')}
# inferred from a whole-module scan of that generator's CALL SITES, when
# every call passes a statically-typed argument for that positional slot
# and they all agree (the "unanimous cross-call scalar contract" that
# ordinary functions get from _infer_param_types -- a generator's fixed
# single-C-value-kind ABI has no per-call monomorphization, so this is the
# only way a fully-unannotated param like `def g(x): yield x` called
# `g(3.5)` picks up its type). Disagreeing call sites -> slot left out
# (unresolved, defaults to int64_t). Populated fresh at the top of each
# lower(); keyed by bare name, same single-module/single-threaded lifetime
# rationale as _PARAM_NAMES. bugs/hard/CODEGEN_coro_stackswitch_yield_
# kind_identifier_inference.md repro 1.
_CALLSITE_PARAM_KINDS: dict[str, dict[str, str]] = {}

# Local/param names bound from create_task/create_raising_task in the async
# def CURRENTLY being lowered -- set by _lower_one_async(_gen) before it
# calls _rewrite_async_stmts, so _await_drive_stmts can tell an `await
# <coro handle>` (generator-resume drive loop) from an `await <Future
# handle>` (Awaitable-protocol waiter-list park). Same per-lower() lifetime
# and single-threaded rationale as _PARAM_NAMES.
_TASK_VARS: set = set()

# Bare names of struct `async def` METHODS in the module currently being
# lowered that passed async-method eligibility -- populated fresh at the
# top of each lower() call. Lets `await <obj>.<name>(...)` at a call site
# be recognised as an async-method await (constructed via the struct's own
# __mgco_<Struct>_<name>_start, driven by the generic await drive loop).
_ASYNC_METHOD_NAMES: set = set()

# Names of every StructDef in the module currently being lowered --
# populated fresh at the top of each lower() call. Lets a struct-typed
# PARAM on a top-level (non-method) async def keep its pointer type: it is
# unpacked from its `__mojo_gen_arg` slot with a `(<T> *)` cast (structs
# cross the C boundary as `T *` -- BUG-2026-030) and passed to the body as
# a real typed `<T> *` C param, instead of collapsing to an opaque
# int64_t. See bugs/COMPILE_FAIL_asyncio_queues.md gap 2.
_STRUCT_NAMES: set = set()


def _is_struct_param(pann) -> bool:
    return isinstance(pann, str) and pann in _STRUCT_NAMES


# ── native Future-class bridge ─────────────────────────────────────────
# A user/stdlib class whose `__await__` (or `__iter__`) is the *standard*
# Awaitable-protocol generator:
#
#     def __await__(self):
#         if not self.done():
#             [<simple self.<attr> = ... assigns>]
#             yield self
#         [if not self.done(): raise RuntimeError(...)]
#         return self.result()
#
# is recognised structurally and mapped ONTO the native A3 `MojoFuture`
# handle model this runtime already provides: an instance of the class IS
# an `int64_t` future handle (`__mojo_future_new()`), its constructor
# lowers exactly like `create_future()`, `.done()/.result()/.set_result()`
# lower to the `__mojo_future_*` shims (via the existing sync + async
# Future-op hooks, which fire once the receiver is a bare int64_t), and
# `await <instance>` parks on the native waiter list via
# `__mojo_async_await_future` -- composing with cross-coroutine wakeup,
# `create_task` concurrency and deque round-tripping already in place.
#
# Conservative: the class is REPLACED by the native handle wholesale (its
# StructDef is dropped, every `: <Cls>` annotation becomes `Int`, every
# `<Cls>(...)` call becomes `create_future()`). A class of this shape that
# ALSO carries other state/methods callable on an instance is out of
# scope for v0 -- but the standard asyncio `Future.__await__` shape this
# targets has exactly `done`/`result`/`set_result` as its awaited surface.
_NATIVE_FUTURE_CLASSES: set = set()


def _is_bare_self_call(node, name: str) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == name and not node.args
            and not getattr(node, 'kwargs', None)
            and isinstance(node.func.obj, N.IdentExpr)
            and node.func.obj.name == 'self')


def _is_not_self_done(node) -> bool:
    return (isinstance(node, N.UnaryOp) and node.op == 'not'
            and _is_bare_self_call(node.operand, 'done'))


def _is_standard_await_generator(m) -> bool:
    if not (isinstance(m, N.FunctionDef) and m.name in ('__await__', '__iter__')):
        return False
    if not any(isinstance(n, N.YieldExpr) for n in _walk(m)):
        return False
    body = [s for s in m.body if not isinstance(s, getattr(N, 'PassStmt', ()))]
    if not body:
        return False
    last = body[-1]
    if not (isinstance(last, N.ReturnStmt) and _is_bare_self_call(last.value, 'result')):
        return False
    for s in body[:-1]:
        if isinstance(s, N.IfStmt) and _is_not_self_done(s.condition):
            for inner in s.then_body:
                if (isinstance(inner, N.ExprStmt)
                        and isinstance(inner.value, N.YieldExpr)
                        and isinstance(inner.value.value, N.IdentExpr)
                        and inner.value.value.name == 'self'):
                    return True
    return False


def _detect_native_future_classes(stmts) -> None:
    _NATIVE_FUTURE_CLASSES.clear()
    for s in stmts:
        if isinstance(s, N.StructDef) and any(
                _is_standard_await_generator(m) for m in s.methods):
            _NATIVE_FUTURE_CLASSES.add(s.name)


def _rewrite_native_future_refs(stmts) -> list:
    """In-place: drop native-future StructDefs, rewrite `: <Cls>`
    annotations to `Int`, rewrite `<Cls>(...)` construction to
    `create_future()`."""
    if not _NATIVE_FUTURE_CLASSES:
        return stmts

    def fix(node):
        if node is None or not hasattr(node, '__dict__'):
            return
        # constructor call -> create_future()
        if (isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr)
                and node.func.name in _NATIVE_FUTURE_CLASSES):
            node.func = N.IdentExpr(name='create_future')
            node.args = []
            if hasattr(node, 'kwargs'):
                node.kwargs = []
        for k, v in list(vars(node).items()):
            if k in ('line', 'col'):
                continue
            if k in ('type_ann', 'return_type') and v in _NATIVE_FUTURE_CLASSES:
                setattr(node, k, 'Int')
            elif k == 'params' and isinstance(v, list):
                node.params = [(pn, 'Int' if pa in _NATIVE_FUTURE_CLASSES else pa)
                               for pn, pa in v]
            elif isinstance(v, list):
                for x in v:
                    fix(x)
            elif hasattr(v, '__dict__'):
                fix(v)

    for s in stmts:
        fix(s)
    return [s for s in stmts
            if not (isinstance(s, N.StructDef) and s.name in _NATIVE_FUTURE_CLASSES)]


def _resolve_call_args(name: str, node, cvar: str) -> list:
    """Positional args, in order, for a call to `name(...)` -- resolving
    any keyword arguments via _PARAM_NAMES when known. Falls back to
    positional-only (kwargs dropped) if `name` wasn't seen -- the emitted
    call then has the wrong arity, caught by the compile/link gate, not a
    silent miscompile (same trust-the-gate posture _await_target_name
    itself documents)."""
    args = list(node.args)
    kwargs = list(getattr(node, 'kwargs', None) or [])
    if not kwargs:
        return [_rewrite_async_expr(a, cvar) for a in args]
    params = _PARAM_NAMES.get(name)
    if not params:
        return [_rewrite_async_expr(a, cvar) for a in args]
    resolved = [None] * len(params)
    for i, a in enumerate(args):
        resolved[i] = a
    for k, v in kwargs:
        if k in params:
            resolved[params.index(k)] = v
    return [_rewrite_async_expr(a, cvar) if a is not None else N.IntLiteral(value=0)
            for a in resolved]


def _is_asyncio_run_call(node) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'run' and len(node.args) == 1
            and isinstance(node.func.obj, N.IdentExpr) and node.func.obj.name == 'asyncio')


def _unwrap_transfer(node):
    """Strip a leading `^` transfer sigil (`task^`)."""
    if isinstance(node, N.UnaryOp) and node.op == '^':
        return node.operand
    return node


def _is_create_task_call(node) -> bool:
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr)
            and node.func.name in ('create_task', 'create_raising_task'))


def _is_task_wait_call(node, task_vars: set) -> bool:
    if not (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'wait' and not node.args):
        return False
    obj = _unwrap_transfer(node.func.obj)
    return isinstance(obj, N.IdentExpr) and obj.name in task_vars


def _await_target_name(node) -> str | None:
    """If `node` is a plain call to a bare top-level name (the only fresh
    await target v0 forwards -- trusting the callee is itself eligible; if
    it isn't, the emitted call to a nonexistent __mgco_<name>_start just
    fails to link, caught by the gate, not a silent miscompile)."""
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr):
        return node.func.name
    return None


def _await_held_handle(node):
    """`await task^` / `await task` -- awaiting an ALREADY-CONSTRUCTED
    coroutine handle (e.g. one held from create_task/create_raising_task),
    as opposed to a fresh `f(args)` call. Returns the handle IdentExpr, or
    None."""
    u = _unwrap_transfer(node)
    return u if isinstance(u, N.IdentExpr) else None


def _is_future_wait_call(node) -> bool:
    """`await <expr>.wait()` -- an Event.wait() bound-method call, no args.
    Lowers onto __mojo_async_await_event_wait (the same Future waiter list).
    `<expr>` must evaluate to an int64_t Event handle."""
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member == 'wait' and not node.args
            and not getattr(node, 'kwargs', None))


def _is_async_method_call(node) -> bool:
    """`await <obj>.<method>(args)` where `<method>` is a compiled struct
    `async def` method (name in _ASYNC_METHOD_NAMES). The generic await
    drive loop constructs the coroutine by leaving the `<obj>.<method>(...)`
    call in place -- the ordinary type-aware codegen lowers it to
    `__mgco_<Struct>_<method>_start(obj, args...)` via _generator_method_api
    -- then drives it exactly like a top-level `await f(args)`."""
    return (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and node.func.member in _ASYNC_METHOD_NAMES
            and not getattr(node, 'kwargs', None))


def _await_stmt_ok(s, task_vars: set) -> bool:
    inner = s.value.value
    if _is_asyncio_sleep_call(inner) or _is_asyncio_sock_recv_call(inner):
        return True
    if _await_target_name(inner) is not None:
        return True
    if _is_future_wait_call(inner):
        return True
    if _is_async_method_call(inner):
        return True
    if isinstance(_unwrap_transfer(inner), N.MemberExpr):
        # `await <expr>.<field>` -- a Future/Event HANDLE held in a struct
        # field (e.g. queues.py's `await self._finished` shape). Parked on
        # its waiter list via __mojo_async_await_future.
        return True
    h = _await_held_handle(inner)
    if h is None:
        return False
    # `await task^`/`await task` where task came from create_task, OR
    # `await <future handle>` (Awaitable protocol) -- a bare local/param
    # name that isn't a known task var is treated as a Future handle.
    return True


def _scan_task_vars(fn: N.FunctionDef) -> set:
    """Local vars this function's own body binds from `create_task`/
    `create_raising_task` -- the only handles `await <var>^` may target."""
    tv = set()
    for s in _walk(fn):
        if (isinstance(s, (N.AssignStmt, N.VarDecl))
                and _is_create_task_call(getattr(s, 'value', None))):
            name = s.name if isinstance(s, N.VarDecl) else (
                s.target.name if isinstance(s.target, N.IdentExpr) else None)
            if name:
                tv.add(name)
    return tv


def _async_awaits_ok(fn: N.FunctionDef) -> bool:
    """Every AwaitExpr must be a bare ExprStmt's value, or directly an
    Assign/VarDecl's value, with a recognized inner shape -- the only
    forms _rewrite_async_stmts desugars. Anything else (nested inside a
    larger expression, or an unrecognized callee shape) => ineligible."""
    task_vars = _scan_task_vars(fn)
    total = sum(1 for n in _walk(fn) if isinstance(n, N.AwaitExpr))
    ok = 0
    for s in _walk(fn):
        if isinstance(s, (N.ExprStmt, N.AssignStmt, N.VarDecl, N.ReturnStmt)) \
                and isinstance(getattr(s, 'value', None), N.AwaitExpr) \
                and _await_stmt_ok(s, task_vars):
            ok += 1
    return ok == total


_LOCK_CTORS = {'BlockingScopedLock', 'BlockingSpinLock'}


def _is_lock_with(node) -> bool:
    """`with BlockingScopedLock(lock):` / `BlockingSpinLock(...)` -- this
    runtime is strictly single-threaded/cooperative (a coroutine only ever
    yields control at an explicit suspension point; nothing interleaves
    between two statements with none in between), so a scoped mutual-
    exclusion guard around a body with NO suspension point inside it is a
    provable no-op and can be elided entirely, mirroring the existing
    cpp-path treatment (test_async_with_lock_guard.py) exactly, including
    its safety rule: refuse (never silently elide) if the body contains a
    real suspension point, where a different coroutine genuinely could
    run during the wait."""
    return (isinstance(node, N.WithStmt) and len(node.items) == 1
            and node.items[0].alias is None
            and isinstance(node.items[0].expr, N.CallExpr)
            and isinstance(node.items[0].expr.func, N.IdentExpr)
            and node.items[0].expr.func.name in _LOCK_CTORS)


def _lock_with_body_suspends(node) -> bool:
    return any(isinstance(x, (N.AwaitExpr, N.YieldExpr, N.YieldFromExpr))
              for s in node.body for x in _walk(s))


def _lock_withs_ok(fn: N.FunctionDef) -> bool:
    for n in _walk(fn):
        if isinstance(n, N.WithStmt) and _is_lock_with(n) and _lock_with_body_suspends(n):
            return False
    return True


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


def _eligible_async_common(fn: N.FunctionDef, nested: bool = False,
                           is_method: bool = False) -> tuple[bool, str]:
    """Checks shared by a plain `async def` and an async GENERATOR.
    `nested=True` (a `@parameter async def` local to an ordinary function,
    e.g. create_task's wrapper idiom) allows the `@parameter` decorator
    specifically -- it's a compile-time-only marker in this codegen, not
    a runtime behavior change -- while a top-level def stays refused for
    ANY decorator."""
    if not fn.is_async:
        return False, 'not async'
    if getattr(fn, 'comptime_params', None):
        return False, 'comptime params'
    decorators = getattr(fn, 'decorators', None) or []
    if nested:
        if any(d != 'parameter' for d in decorators):
            return False, 'decorated (v0 allows only @parameter on a nested async def)'
    elif decorators:
        return False, 'decorated'
    _params = fn.params
    if is_method:
        if not _params or _params[0][0] != 'self':
            return False, 'async method without a plain `self` first param (v0)'
        _params = _params[1:]   # self is typed by the codegen from the struct
    for pname, pann in _params:
        if pann not in _SCALARISH and not _is_struct_param(pann):
            return False, f'param {pname!r} type {pann!r} (v0 scalar / struct only)'
    if getattr(fn, 'kwonly', None):
        return False, 'kwonly params (v0)'
    if not _async_awaits_ok(fn):
        return False, 'await in an unhandled shape (v0)'
    if not _async_for_ok(fn):
        return False, 'async for in an unhandled shape (v0)'
    if not _lock_withs_ok(fn):
        return False, 'with <lock>: containing a suspension point (unsafe to elide)'
    return True, ''


def _eligible_async(fn: N.FunctionDef, nested: bool = False,
                    is_method: bool = False) -> tuple[bool, str]:
    if any(isinstance(n, (N.YieldExpr, N.YieldFromExpr)) for n in _walk(fn)):
        return False, 'async generator -- use _eligible_async_gen'
    return _eligible_async_common(fn, nested=nested, is_method=is_method)


def _eligible_async_gen(fn: N.FunctionDef, nested: bool = False,
                        is_method: bool = False) -> tuple[bool, str]:
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
    return _eligible_async_common(fn, nested=nested, is_method=is_method)


def _rewrite_async_expr(node, cvar: str):
    """Like _rewrite_expr, but for an async body -- there is no YieldExpr
    to replace (v0 excludes async generators), just recurse; AwaitExpr is
    handled at statement level by _rewrite_async_stmts before this is ever
    called on one."""
    if node is None or not hasattr(node, '__dict__'):
        return node
    # Awaitable protocol: rewrite Future/Event operations to the A3 runtime
    # shims (runtime/mojo_coro_gen.c). Confined to async-coroutine-body
    # lowering -- the ordinary synchronous compiled path is untouched.
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr) \
            and not getattr(node, 'kwargs', None):
        _m = node.func.member
        _obj = node.func.obj
        if _m == 'set_result' and len(node.args) == 1:
            return _call('__mojo_future_set_result',
                         [_rewrite_async_expr(_obj, cvar),
                          _rewrite_async_expr(node.args[0], cvar)])
        if _m == 'create_future' and not node.args:
            return _call('__mojo_future_new', [])
        if _m == 'set' and not node.args:
            return _call('__mojo_event_set', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'is_set' and not node.args:
            return _call('__mojo_event_is_set', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'done' and not node.args:
            return _call('__mojo_future_done', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'result' and not node.args:
            return _call('__mojo_future_result', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'set_exception' and len(node.args) == 1:
            _tag, _msg = _exc_arg_to_shim_args(node.args[0], cvar)
            return _call('__mojo_future_set_exception',
                         [_rewrite_async_expr(_obj, cvar), _tag, _msg])
        if _m == 'exception' and not node.args:
            return _call('__mojo_future_exception', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'cancel' and not node.args:
            return _call('__mojo_future_cancel', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'cancelled' and not node.args:
            return _call('__mojo_future_cancelled', [_rewrite_async_expr(_obj, cvar)])
        if _m == 'set_running_or_notify_cancel' and not node.args:
            return _call('__mojo_future_set_running_or_notify_cancel',
                         [_rewrite_async_expr(_obj, cvar)])
        if _m == 'add_done_callback' and len(node.args) == 1:
            # The 3rd arg (callable-kind tag) is supplied by
            # gimple_gen_calls._lower_call's dedicated interception, which
            # inspects the lowered C type of the callback value (so a
            # capturing closure / bound method passed by name is tagged
            # correctly, not just a syntactic `self.cb` MemberExpr).
            return _call('__mojo_future_add_done_callback',
                         [_rewrite_async_expr(_obj, cvar),
                          _rewrite_async_expr(node.args[0], cvar)])
        if _m == 'remove_done_callback' and len(node.args) == 1:
            return _call('__mojo_future_remove_done_callback',
                         [_rewrite_async_expr(_obj, cvar),
                          _rewrite_async_expr(node.args[0], cvar)])
        if _m in ('Future',) and not node.args:
            return _call('__mojo_future_new', [])
        if _m in ('Event',) and not node.args:
            return _call('__mojo_event_new', [])
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr) \
            and not node.args and not getattr(node, 'kwargs', None):
        if node.func.name == 'create_future':
            return _call('__mojo_future_new', [])
        if node.func.name == 'Event':
            return _call('__mojo_event_new', [])
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
    # Awaitable protocol: `await <event>.wait()` -- park on the Event's
    # waiter list (same list as a Future's; runtime/mojo_coro_gen.c).
    if _is_future_wait_call(inner):
        obj = _rewrite_async_expr(inner.func.obj, cvar)
        _AW_COUNTER[0] += 1
        rv = f'__ar{_AW_COUNTER[0]}'
        stmts = [N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_async_await_event_wait', [_c_ident(cvar), obj]))]
        return stmts, _c_ident(rv)
    # Awaitable protocol: `await <expr>.<field>` -- a Future/Event handle
    # held in a struct field; park on its waiter list.
    _mem = _unwrap_transfer(inner)
    if isinstance(_mem, N.MemberExpr):
        obj = _rewrite_async_expr(_mem, cvar)
        _AW_COUNTER[0] += 1
        rv = f'__ar{_AW_COUNTER[0]}'
        stmts = [N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_async_await_future', [_c_ident(cvar), obj]))]
        return stmts, _c_ident(rv)
    # Awaitable protocol: `await <future handle>` -- a bare local/param name
    # that is NOT a create_task handle is a Future; park on its waiter list.
    _hh = _await_held_handle(inner)
    if (_hh is not None and _await_target_name(inner) is None
            and _hh.name not in _TASK_VARS):
        _AW_COUNTER[0] += 1
        rv = f'__ar{_AW_COUNTER[0]}'
        stmts = [N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_async_await_future',
                                       [_c_ident(cvar), _c_ident(_hh.name)]))]
        return stmts, _c_ident(rv)
    # Awaitable protocol: `await <task>` / `await task^` where `task` came
    # from create_task() -- the task coroutine was eagerly scheduled onto
    # the shared ready queue at creation, so this must NOT re-drive it with
    # a private __mojo_gen_resume loop (that would double-resume the same
    # MojoCoro). Park on it via __mojo_async_await_task (MOJO_WD_TASK); the
    # scheduler wakes us when the task runs to completion.
    if (_hh is not None and _await_target_name(inner) is None
            and _hh.name in _TASK_VARS):
        _AW_COUNTER[0] += 1
        rv = f'__ar{_AW_COUNTER[0]}'
        stmts = [N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_async_await_task',
                                       [_c_ident(cvar), _c_ident(_hh.name)]))]
        return stmts, _c_ident(rv)
    name = _await_target_name(inner)
    if name is not None:
        # fresh `await f(args)` -- construct via f's own _start (the only
        # name-specific step; everything after is generic).
        args = _resolve_call_args(name, inner, cvar)
        h_expr = _call(f'__mgco_{name}_start', args)
    else:
        # `await task^` / `await task` -- an already-constructed handle
        # (e.g. held from create_task/create_raising_task); ownership
        # transfers to this drive loop, which destroys it when done.
        h_expr = _rewrite_async_expr(_unwrap_transfer(inner), cvar)
    _AW_COUNTER[0] += 1
    h = f'__ah{_AW_COUNTER[0]}'
    rv = f'__ar{_AW_COUNTER[0]}'
    stmts = [N.VarDecl(name=h, type_ann=None, value=h_expr)]
    loop_body = [forward(cvar, _call('__mojo_gen_value', [_c_ident(h)]))]
    stmts.append(N.WhileStmt(condition=_call('__mojo_gen_resume', [_c_ident(h), N.IntLiteral(value=0)]),
                             body=loop_body, else_body=None))
    stmts.append(N.VarDecl(name=rv, type_ann=None,
                           value=_call('__mojo_gen_retval', [_c_ident(h)])))
    stmts.append(N.ExprStmt(value=_call('__mojo_gen_destroy', [_c_ident(h)])))
    return stmts, _c_ident(rv)


def _async_for_drive_stmts(cvar: str, target: str, iterable, body, forward=_forward_plain) -> list:
    """`async for x in f(args): <body>` -- f is a compiled async-generator
    coroutine. Drives it exactly like _await_drive_stmts, except each
    resume may produce EITHER a wait-descriptor (forward upward, loop
    again) or a real yielded value (bind `target`, run the user body --
    which may `break`/`continue` the very same while loop, matching real
    Python `async for` semantics)."""
    name = _await_target_name(iterable)
    args = _resolve_call_args(name, iterable, cvar) if iterable else []
    _AW_COUNTER[0] += 1
    h = f'__afh{_AW_COUNTER[0]}'
    stmts = [N.VarDecl(name=h, type_ann=None, value=_call(f'__mgco_{name}_start', args))]
    inner_body = [
        forward(cvar, _call('__mojo_gen_value', [_c_ident(h)])),
        N.ContinueStmt(),
    ]
    if_wd = N.IfStmt(
        condition=_call('__mojo_gen_last_yield_was_wd', [_c_ident(h)]),
        then_body=inner_body, elifs=[], else_body=None)
    bind = N.AssignStmt(target=N.IdentExpr(name=target),
                        value=_call('__mojo_gen_value', [_c_ident(h)]))
    loop_body = [if_wd, bind] + body
    stmts.append(N.WhileStmt(condition=_call('__mojo_gen_resume', [_c_ident(h), N.IntLiteral(value=0)]),
                             body=loop_body, else_body=None))
    stmts.append(N.ExprStmt(value=_call('__mojo_gen_destroy', [_c_ident(h)])))
    return stmts


def _rewrite_async_stmts(stmts: list, cvar: str) -> list:
    out = []
    for s in stmts:
        if isinstance(s, N.ReturnStmt) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value)
            out.extend(drive)
            out.append(N.ExprStmt(value=_call(SETRET_SHIM, [_c_ident(cvar), rv])))
            out.append(N.ReturnStmt(value=None))
            continue
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
        if _is_lock_with(s):
            # provable no-op in this strictly single-threaded/cooperative
            # runtime (gated by _lock_withs_ok at eligibility) -- elide
            # the guard, keep the body.
            out.extend(_rewrite_async_stmts([_deep_copy_stmt(b) for b in s.body], cvar))
            continue
        if isinstance(s, N.TryStmt):
            for h in (s.handlers or []):
                h.body = _rewrite_async_stmts(h.body, cvar)
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
        if isinstance(s, N.ReturnStmt) and isinstance(s.value, N.AwaitExpr):
            drive, rv = _await_drive_stmts(cvar, s.value.value, forward=_forward_tagged)
            out.extend(drive)
            out.append(N.ExprStmt(value=_call(SETRET_SHIM, [_c_ident(cvar), rv])))
            out.append(N.ReturnStmt(value=None))
            continue
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
        if _is_lock_with(s):
            out.extend(_rewrite_async_gen_stmts([_deep_copy_stmt(b) for b in s.body], cvar))
            continue
        if isinstance(s, N.TryStmt):
            for h in (s.handlers or []):
                h.body = _rewrite_async_gen_stmts(h.body, cvar)
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


def _async_method_setup(fn, base, struct_name):
    """Shared prologue/param plumbing for a plain `async def` and an async
    generator, top-level OR a struct method. For a method: arg 0 is the
    real `self` receiver (passed to the body as a typed 2nd C param, like
    _lower_one's generator-method path), so `__mojo_gen_arg` indices for
    the ordinary params start at 1 and `self` gets no prologue entry."""
    is_method = struct_name is not None
    base = base or (f'__mgco_{N._as_str(struct_name)}_{N._as_str(fn.name)}' if is_method
                    else f'__mgco_{N._as_str(fn.name)}')
    real_params = fn.params[1:] if is_method else fn.params
    arg_base = 1 if is_method else 0
    prologue = []
    for i, (pname, pann) in enumerate(real_params):
        slot = _call(ARG_SHIM, [_c_ident(_CVAR), N.IntLiteral(value=arg_base + i)])
        if _is_struct_param(pann):
            # A struct-typed param crosses as `T *` (BUG-2026-030). The
            # `__mojo_gen_arg` slot holds that pointer bit-pattern as an
            # int64_t; route it back to `T *` through UnsafePointer[T](...)
            # -- the exact int-address -> pointer erasure _lower_pointer_ctor
            # / _resolve_type already implement (void* two-step, GIMPLE
            # rejects a direct int64_t->T* cast).
            val = N.CallExpr(
                func=N.SubscriptExpr(obj=N.IdentExpr(name='UnsafePointer'),
                                     index=N.IdentExpr(name=pann)),
                args=[slot])
            prologue.append(N.VarDecl(name=pname, type_ann=pann, value=val))
        else:
            prologue.append(N.VarDecl(name=pname, type_ann=None, value=slot))
    body_params = [(_CVAR, 'Int')]
    if is_method:
        body_params.append(('self', struct_name))
    c_params = ([f'{struct_name} *'] if is_method else []) + \
               [(f'{a} *' if _is_struct_param(a) else _mojo_to_c_type(a))
                for _n, a in real_params]
    return base, is_method, real_params, prologue, body_params, c_params


def _lower_one_async_gen(fn: N.FunctionDef, meta: list, base: str | None = None,
                         struct_name: str | None = None, struct_def=None) -> N.FunctionDef:
    base, is_method, real_params, prologue, body_params, c_params = \
        _async_method_setup(fn, base, struct_name)
    body_name = f'{base}_body'
    _TASK_VARS.clear()
    _TASK_VARS.update(_scan_task_vars(fn))
    new_body = prologue + _rewrite_async_gen_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR)
    body_fd = N.FunctionDef(name=body_name, params=body_params, return_type=None, body=new_body)
    body_fd.is_generator = False
    body_fd.is_async = False
    meta.append({
        'name': N._as_str(fn.name), 'struct': struct_name, 'is_method': is_method, 'is_async': True,
        'is_async_gen': True,
        'base': base, 'body_name': body_name,
        'params': c_params,
        'nargs': len(real_params), 'value_ctype': 'int64_t', 'value_kind': 'i',
        'tuple_slot_ctypes': None,
        'defaults': list((getattr(fn, 'param_defaults', None) or {}).items()),
    })
    return body_fd


def _lower_one_async(fn: N.FunctionDef, meta: list, base: str | None = None,
                     struct_name: str | None = None, struct_def=None) -> N.FunctionDef:
    base, is_method, real_params, prologue, body_params, c_params = \
        _async_method_setup(fn, base, struct_name)
    body_name = f'{base}_body'
    _TASK_VARS.clear()
    _TASK_VARS.update(_scan_task_vars(fn))
    new_body = prologue + _rewrite_async_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR)
    body_fd = N.FunctionDef(name=body_name, params=body_params, return_type=None, body=new_body)
    body_fd.is_generator = False
    body_fd.is_async = False
    meta.append({
        'name': N._as_str(fn.name), 'struct': struct_name, 'is_method': is_method, 'is_async': True,
        'base': base, 'body_name': body_name,
        'params': c_params,
        'nargs': len(real_params), 'value_ctype': 'int64_t', 'value_kind': 'i',
        'tuple_slot_ctypes': None,
        'defaults': list((getattr(fn, 'param_defaults', None) or {}).items()),
    })
    return body_fd


def _rewrite_asyncio_run(node, cvar: str | None, task_vars: set, local_map: dict | None = None):
    """Whole-module expression rewrite for the three ways ordinary code
    drives a compiled coroutine to completion and blocks for its result:
      - `asyncio.run(f(...))`
      - `create_task(f(...))` / `create_raising_task(f(...))` -- v0 has no
        real concurrency between separate tasks (each is driven fully to
        completion the moment `.wait()` is called, exactly like
        asyncio.run), so this is a pure passthrough: replaced with `f(...)`
        itself (already routes to __mgco_f_start via _generator_api).
      - `<task>.wait()` / `<task>^.wait()` on a var seen bound from one of
        the above (task_vars) -- drive-to-completion + read the result.
        An uncaught exception in the task re-raises here for free (the
        same __mojo_coro_resume contract every other consumer relies on),
        so RaisingTask vs Task needs no separate representation.
      - a BARE call to a local nested helper (`var coro = wrapper()`,
        with no `create_task`/`asyncio.run` wrapper at all) -- the
        "detached async" idiom (bugs/hard/CODEGEN_coro_detached_async_
        take_handle.md: device_context.mojo's `enqueue_cpu_function`/
        `enqueue_cpu_range`, which construct the coroutine directly and
        drive it via `_take_handle()` + an external C dispatch, never
        `create_task`/`.wait()`). Same qualified-`_start` rewrite as the
        create_task case, just without the create_task wrapper to unwrap
        first.
    `cvar`/task_vars are threaded through only so a nested case (not a v0
    shape -- kept out by eligibility) does not crash."""
    if node is None or not hasattr(node, '__dict__'):
        return node, []
    local_map = local_map or {}
    if _is_create_task_call(node):
        inner = node.args[0]
        if isinstance(inner, N.CallExpr) and isinstance(inner.func, N.IdentExpr) \
                and inner.func.name in local_map:
            # a LOCAL nested `@parameter async def` (create_task's
            # wrapper idiom) -- bypass the generic _generator_api name
            # dispatch entirely (two different enclosing functions may
            # each have their own same-named nested helper) and call its
            # qualified _start directly.
            args = [_rewrite_asyncio_run(a, cvar, task_vars, local_map)[0] for a in inner.args]
            return _call(f'{local_map[inner.func.name]}_start', args), []
        return _rewrite_asyncio_run(inner, cvar, task_vars, local_map)
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr) \
            and node.func.name in local_map:
        args = [_rewrite_asyncio_run(a, cvar, task_vars, local_map)[0] for a in node.args]
        return _call(f'{local_map[node.func.name]}_start', args), []
    pre = []
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            newv = []
            for x in v:
                if hasattr(x, '__dict__'):
                    nx, npre = _rewrite_asyncio_run(x, cvar, task_vars, local_map)
                    pre.extend(npre)
                    newv.append(nx)
                else:
                    newv.append(x)
            setattr(node, k, newv)
        elif hasattr(v, '__dict__'):
            nv, npre = _rewrite_asyncio_run(v, cvar, task_vars, local_map)
            pre.extend(npre)
            setattr(node, k, nv)
    if _is_asyncio_run_call(node) or _is_task_wait_call(node, task_vars):
        _AW_COUNTER[0] += 1
        h = f'__arun{_AW_COUNTER[0]}'
        rv = f'__arunv{_AW_COUNTER[0]}'
        if _is_asyncio_run_call(node):
            # `asyncio.run(...)` only has a defined meaning for a BARE CALL
            # to a supported compiled async function -- anything else (a
            # plain variable, a literal, an arbitrary expression) has no
            # generator/coroutine handle to drive. Without this check, a
            # non-call argument passed straight through the generic
            # recursive rewrite below unchanged, and got wrapped as if it
            # WERE a real handle (`__arun1 = x; __mojo_async_run_gen
            # (__arun1);`) -- a genuine silent miscompile (the raw int/
            # whatever value reinterpreted as a `MojoGenerator *` at
            # runtime), not merely a test-expectation mismatch. Refuse
            # honestly instead, matching every other unsupported shape in
            # this file's own "cannot compile module" convention.
            if not isinstance(node.args[0], N.CallExpr):
                raise RuntimeError(
                    "cannot compile module: asyncio.run(...) requires a "
                    "bare call to a supported compiled async function as "
                    "its argument -- got a non-call expression, which has "
                    "no coroutine handle to drive")
            call_expr, cpre = _rewrite_asyncio_run(node.args[0], cvar, task_vars, local_map)
            pre.extend(cpre)
            pre.append(N.VarDecl(name=h, type_ann=None, value=call_expr))
            pre.append(N.ExprStmt(value=_call('__mojo_async_run_gen', [_c_ident(h)])))
        else:
            # `<task>.wait()` -- task_expr is already a live handle (the
            # var create_task's passthrough left it bound to); reuse it
            # directly instead of introducing a redundant copy.
            task_expr = _unwrap_transfer(node.func.obj)
            pre.append(N.VarDecl(name=h, type_ann=None, value=task_expr))
            pre.append(N.ExprStmt(value=_call('__mojo_async_run_gen', [_c_ident(h)])))
        pre.append(N.VarDecl(name=rv, type_ann=None,
                             value=_call('__mojo_gen_retval', [_c_ident(h)])))
        return _c_ident(rv), pre
    return node, pre


def _rewrite_asyncio_run_stmts(stmts: list, cvar: str | None, task_vars: set | None = None,
                               local_map: dict | None = None, local_maps: dict | None = None) -> list:
    lmaps = local_maps or {}
    lm = local_map or {}
    out = []
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            fn_ordinary = not getattr(s, 'is_generator', False) and not getattr(s, 'is_async', False)
            fn_task_vars = _scan_task_vars(s) if fn_ordinary else set()
            # Merge the ENCLOSING scope's already-active local_map (`lm`)
            # under this function's own entry, rather than discarding it --
            # a hoisted nested async def (`inc`) defined in one function is
            # still in lexical scope inside a FURTHER-nested sibling
            # function (`caller`) of that same enclosing function, so
            # `caller`'s own `tg.create_task(inc())` must see the same
            # qualified-`{base}_start` rename. Matches real Python lexical
            # scoping (an inner def sees every enclosing scope's bindings).
            fn_lm = {**lm, **lmaps.get(s.name, {})} if fn_ordinary else {}
            s.body = _rewrite_asyncio_run_stmts(s.body, cvar, fn_task_vars, fn_lm, lmaps)
            out.append(s)
            continue
        tv = task_vars or set()
        if (isinstance(s, (N.AssignStmt, N.VarDecl)) and _is_create_task_call(s.value)):
            # passthrough: `var task = create_task(f(...))` -> `var task = f(...)`
            # (pass the FULL create_task(...) node, not the pre-unwrapped
            # inner call -- _rewrite_asyncio_run's own _is_create_task_call
            # branch is what applies `lm`'s qualified-name rewrite for a
            # local nested helper; skipping straight to the inner call
            # bypassed that and let a bare `wrapper()` fall through to the
            # global _generator_api dispatch instead, which collides
            # across scopes for same-named nested helpers.)
            new_val, pre = _rewrite_asyncio_run(s.value, cvar, tv, lm)
            out.extend(pre)
            if isinstance(s, N.VarDecl):
                out.append(N.VarDecl(name=s.name, type_ann=None, value=new_val))
                _tname = s.name
            else:
                out.append(N.AssignStmt(target=s.target, value=new_val))
                _tname = s.target.name if isinstance(s.target, N.IdentExpr) else None
            # Eager task scheduling: enqueue the freshly-constructed
            # coroutine handle onto the shared scheduler ready queue so
            # sibling tasks actually run concurrently and a producer can
            # wake an already-parked consumer (bugs/COMPILE_FAIL_asyncio_
            # queues.md gap 3). A later `await <task>` parks via
            # __mojo_async_await_task instead of privately re-driving it.
            if _tname is not None:
                out.append(N.ExprStmt(value=_call('__mojo_async_task_schedule',
                                                  [_c_ident(_tname)])))
            continue
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                setattr(s, k, _rewrite_asyncio_run_stmts(v, cvar, tv, lm, lmaps))
            elif isinstance(v, list):
                newv = []
                for x in v:
                    if hasattr(x, '__dict__'):
                        nx, pre = _rewrite_asyncio_run(x, cvar, tv, lm)
                        out.extend(pre)
                        newv.append(nx)
                    else:
                        newv.append(x)
                setattr(s, k, newv)
            elif hasattr(v, '__dict__'):
                nv, pre = _rewrite_asyncio_run(v, cvar, tv, lm)
                out.extend(pre)
                setattr(s, k, nv)
        out.append(s)
    return out


# ── the yield / return rewrite ─────────────────────────────────────────

def _c_ident(name: str) -> N.IdentExpr:
    return N.IdentExpr(name=name)


def _call(fn_name: str, args: list) -> N.CallExpr:
    return N.CallExpr(func=_c_ident(fn_name), args=list(args))


import zlib as _zlib


def _exc_type_tag(name: str) -> int:
    return (_zlib.crc32(name.encode()) & 0x7fffffff) or 1


def _looks_like_exc_class(name: str) -> bool:
    return bool(name) and name[:1].isupper() and (
        name.endswith('Error') or name.endswith('Exception')
        or name in ('CancelledError', 'GeneratorExit', 'KeyboardInterrupt'))


def _exc_arg_to_shim_args(arg, cvar: str) -> tuple:
    """Lower a `set_exception(<arg>)` argument to the (type_tag_int,
    message_expr) pair __mojo_future_set_exception takes -- the same
    shapes `raise` lowering (gimple_gen_stmts._gen_stmt_RaiseStmt)
    recognises: `Exc("msg")`, `Exc`, or a bare bound name."""
    name = None
    msg = None
    if (isinstance(arg, N.CallExpr) and isinstance(arg.func, N.IdentExpr)):
        name = arg.func.name
        if len(arg.args) == 1 and isinstance(arg.args[0], N.StringLiteral):
            msg = arg.args[0]
    elif isinstance(arg, N.IdentExpr) and _looks_like_exc_class(arg.name):
        name = arg.name
    tag = _exc_type_tag(name) if name else 0
    if msg is None:
        msg = N.StringLiteral(value="")
    else:
        msg = _rewrite_async_expr(msg, cvar)
    return N.IntLiteral(value=tag), msg


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
        if isinstance(s, N.TryStmt):
            for h in (s.handlers or []):
                h.body = _rewrite_stmts(h.body, cvar, kind)
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

_NUMERIC_CTORS = {'Float64': 'd', 'Float32': 'd', 'Float': 'd', 'float': 'd',
                  'Int': 'i', 'Int64': 'i', 'Int32': 'i', 'int': 'i',
                  'Bool': 'i', 'bool': 'i',
                  'String': 'p', 'StringSlice': 'p', 'str': 'p'}


def _argkind(expr, caller_env: dict | None = None) -> str | None:
    """Static yield-C-kind of a call ARGUMENT expression, or None when it
    can't be told purely syntactically. Literals, a unary +/- of a literal,
    a numeric/string constructor call, and (via `caller_env`, a _static_env
    of the calling function) a bare identifier / self.<field> reference."""
    k = _literal_kind(expr)
    if isinstance(k, str):
        return k
    if isinstance(expr, N.UnaryOp) and expr.op in ('-', '+'):
        return _argkind(expr.operand, caller_env)
    if isinstance(expr, N.CallExpr) and isinstance(expr.func, N.IdentExpr):
        return _NUMERIC_CTORS.get(expr.func.name)
    if caller_env:
        return _yield_kind(expr, caller_env)
    return None


def _scan_callsite_param_kinds(stmts: list) -> None:
    """Populate _CALLSITE_PARAM_KINDS from a whole-module scan of every call
    to a generator / async def, mapping each unannotated positional (or
    keyword) parameter to the unanimous static kind of the arguments passed
    for it across all call sites. See _CALLSITE_PARAM_KINDS' docstring."""
    _CALLSITE_PARAM_KINDS.clear()
    # gen name -> [(pname, pann), ...] (receiver dropped for methods)
    gen_params: dict[str, list] = {}

    def _record(fd, drop_self):
        ps = fd.params[1:] if drop_self else fd.params
        gen_params.setdefault(fd.name, list(ps))

    for s in stmts:
        if isinstance(s, N.FunctionDef) and (getattr(s, 'is_generator', False)
                                             or getattr(s, 'is_async', False)):
            _record(s, drop_self=False)
        if isinstance(s, N.StructDef):
            for m in s.methods:
                if isinstance(m, N.FunctionDef) and (getattr(m, 'is_generator', False)
                                                     or getattr(m, 'is_async', False)):
                    _record(m, drop_self=bool(m.params) and m.params[0][0] in ('self', 'cls'))
    if not gen_params:
        return

    # per gen: param name -> set of kinds seen (a None poisons the slot)
    seen: dict = {g: {} for g in gen_params}

    def _visit_call(node, caller_env):
        fn = node.func
        gname = fn.name if isinstance(fn, N.IdentExpr) else \
            (fn.member if isinstance(fn, N.MemberExpr) else None)
        pinfo = gen_params.get(gname)
        if pinfo is None:
            return
        cenv = caller_env
        slot = seen[gname]
        for i, a in enumerate(node.args):
            if i >= len(pinfo):
                break
            pname, pann = pinfo[i]
            if _ann_kind(pann) is not None:
                continue
            slot.setdefault(pname, set()).add(_argkind(a, cenv))
        kw = {p: a for p, a in getattr(node, 'kwargs', []) or []}
        by_name = {p: pa for p, pa in pinfo}
        for pname, a in kw.items():
            if pname not in by_name or _ann_kind(by_name[pname]) is not None:
                continue
            slot.setdefault(pname, set()).add(_argkind(a, cenv))

    for s in stmts:
        fns = []
        if isinstance(s, N.FunctionDef):
            fns.append(s)
        elif isinstance(s, N.StructDef):
            fns.extend(m for m in s.methods if isinstance(m, N.FunctionDef))
        for fn in fns:
            cenv = _static_env(fn)
            for n in _walk(fn):
                if isinstance(n, N.CallExpr):
                    _visit_call(n, cenv)
        # module-level calls (rare, e.g. a bare generator call in a stmt)
        if not isinstance(s, (N.FunctionDef, N.StructDef)):
            for n in _walk(s):
                if isinstance(n, N.CallExpr):
                    _visit_call(n, None)

    for gname, slot in seen.items():
        resolved = {}
        for pname, kinds in slot.items():
            kinds = {k for k in kinds if k is not None} if None not in kinds else set()
            # avoid `next(iter(...))` -- a known self-host miscompile trigger
            # (see _generator_tuple_slots' identical note / project memory:
            # "next(iter(...)) -> _next undefined-symbol regression")
            if len(kinds) == 1:
                resolved[pname] = list(kinds)[0]
        if resolved:
            _CALLSITE_PARAM_KINDS[gname] = resolved


def lower(stmts: list) -> tuple[list, list]:
    """Returns (new_stmts, coro_meta). coro_meta entries are dicts:
        {'name', 'base', 'params' (list of C types), 'value_ctype',
         'body_name', 'nargs'}
    """
    if not enabled():
        return stmts, []
    _PARAM_NAMES.clear()
    _ASYNC_METHOD_NAMES.clear()
    _STRUCT_NAMES.clear()
    _detect_native_future_classes(stmts)
    stmts = _rewrite_native_future_refs(stmts)
    _scan_callsite_param_kinds(stmts)
    _STRUCT_NAMES.update(s.name for s in stmts if isinstance(s, N.StructDef))
    _prop_names = _seed_prop_names(stmts)
    for s in stmts:
        if isinstance(s, N.FunctionDef) and (getattr(s, 'is_generator', False)
                                             or getattr(s, 'is_async', False)):
            _PARAM_NAMES[s.name] = [p for p, _a in s.params]
        if isinstance(s, N.StructDef):
            for m in s.methods:
                if not (isinstance(m, N.FunctionDef) and getattr(m, 'is_async', False)):
                    continue
                _isg = any(isinstance(n, N.YieldExpr) for n in _walk(m))
                _mok = (_eligible_async_gen(m, is_method=True)[0] if _isg
                        else _eligible_async(m, is_method=True)[0])
                if _mok:
                    _ASYNC_METHOD_NAMES.add(m.name)
                    _PARAM_NAMES.setdefault(m.name, [p for p, _a in m.params[1:]])
    out = []
    meta = []
    method_bodies = []
    for s in stmts:
        if isinstance(s, N.FunctionDef) and getattr(s, 'is_generator', False):
            ok, _why = _eligible(s, prop_names=_prop_names)
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
                        and not getattr(m, 'is_async', False)
                        and _eligible(m, struct_name=s.name, struct_def=s,
                                      prop_names=_prop_names)[0]):
                    method_bodies.append(_lower_one(m, meta, struct_name=s.name,
                                                   struct_def=s))
                    # drop the generator method from the struct: gen_module's
                    # Phase 2a skips _supported_generator_methods anyway, and
                    # the body now lives as a top-level function
                    continue
                if isinstance(m, N.FunctionDef) and getattr(m, 'is_async', False):
                    _isg = any(isinstance(n, N.YieldExpr) for n in _walk(m))
                    if _isg and _eligible_async_gen(m, is_method=True)[0]:
                        method_bodies.append(_lower_one_async_gen(
                            m, meta, struct_name=s.name, struct_def=s))
                        continue
                    if not _isg and _eligible_async(m, is_method=True)[0]:
                        method_bodies.append(_lower_one_async(
                            m, meta, struct_name=s.name, struct_def=s))
                        continue
                _kept.append(m)
            s.methods = _kept
        out.append(s)
    out = out + method_bodies
    out, nested_bodies, local_maps = _hoist_nested_async(out, meta)
    out = out + nested_bodies
    out = _rewrite_asyncio_run_stmts(out, None, local_maps=local_maps)
    return out, meta


# ── nested-async mutable closure capture (bugs/hard/CODEGEN_coro_nested_
# async_closure_capture.md) -- a captured free variable of a nested
# `@parameter async def` may be one of the ENCLOSING ordinary function's
# own top-level `var name = <init>` locals OR one of its PARAMETERS
# (Increment B), of scalar kind int/bool ('i'), float ('d', Increment C)
# or string ('p', Increment C). The initializer no longer has to be a
# bare int literal -- only statically confident in kind (Increment A:
# annotation, `_strict_init_kind`, or a same-module `def -> <scalar>`
# return type). A struct capture, an opaque unannotated-call initializer,
# or a capture reached only through a driven `async for` in a sibling
# async def is left ineligible (`_nested_async_capture_plan` -> None) and
# falls through to the existing gimple_cpp_* C++20-coroutine path
# unchanged, exactly like every other narrow eligibility gate in this
# file. Represented as a heap box -- a plain `int64_t` HANDLE regardless
# of the cell's element type (`_BOX_SHIMS`), never a raw pointer type,
# matching every other cross-boundary handle this file
# already uses -- rather than `&local` -- mirrors the ordinary (non-async)
# compiled path's own `{mut}`-capture convention (see gimple_gen_infra.
# py's `_seed_mut_captured_local_types` docstring for why: `-fgimple`
# rejects a stack local's address being taken anywhere in a function
# that ALSO cast-assigns/returns that same local elsewhere) -- except
# here the box is allocated via a plain runtime call
# (`__mojo_box_new_i64`, runtime/mojo_coro_gen.c) instead of the ordinary
# path's malloc-in-prologue, since this is a pure AST-to-AST rewrite with
# no `gen`/type-inference access yet (this whole module runs BEFORE
# GimpleGen is even constructed -- see the module docstring).
_BOX_NEW = '__mojo_box_new_i64'
_BOX_GET = '__mojo_box_get_i64'
_BOX_SET = '__mojo_box_set_i64'

# Increment A/B/C: typed box shim triples keyed by capture kind. The HANDLE
# is always a plain int64_t (the malloc'd cell address) so the hidden
# trailing-param threading is identical for every kind; only the cell's
# element type (and hence which get/set shim reads it) changes.
#   'i' int64_t / bool   'd' double (Float64/Float32)   'p' char * (String)
_BOX_SHIMS = {
    'i': ('__mojo_box_new_i64', '__mojo_box_get_i64', '__mojo_box_set_i64'),
    'd': ('__mojo_box_new_d',   '__mojo_box_get_d',   '__mojo_box_set_d'),
    'p': ('__mojo_box_new_p',   '__mojo_box_get_p',   '__mojo_box_set_p'),
}


# Same-module `def name(...) -> <ann>` -> scalar box kind ('i'/'d'/'p'),
# populated fresh at the top of each `_hoist_nested_async` pass. Lets
# `var x = compute()` (Increment A) pick up its kind from the callee's
# return annotation. Same single-module/single-pass lifetime as _PARAM_NAMES.
_FUNC_RET_KIND: dict[str, str] = {}


def _capsrc_name(n: str) -> str:
    """The renamed raw-parameter identifier a captured PARAMETER (Increment
    B) keeps its incoming value under, once the bare param name has been
    repurposed to hold that value's box handle in the enclosing body."""
    return '__capsrc_' + n


def _strict_init_kind(value, env: dict) -> str | None:
    """Confident scalar box kind ('i'/'d'/'p') of an initializer expression,
    or None. Stricter than `_yield_kind` (which falls back to 'i' for an
    unknown BinaryOp) -- an unrecognised shape MUST stay None so the
    capture is refused (cpp path), never mis-boxed."""
    if value is None:
        return None
    if isinstance(value, (N.IntLiteral, N.BoolLiteral)):
        return 'i'
    if isinstance(value, N.FloatLiteral):
        return 'd'
    if isinstance(value, (N.StringLiteral, N.TstringLiteral)):
        return 'p'
    if isinstance(value, N.IdentExpr):
        v = env.get(value.name)
        return v if v in ('i', 'd', 'p') else None
    if isinstance(value, N.CallExpr) and isinstance(value.func, N.IdentExpr):
        _b = {'int': 'i', 'len': 'i', 'ord': 'i', 'hash': 'i',
              'float': 'd', 'str': 'p', 'String': 'p', 'repr': 'p'}.get(value.func.name)
        # a call to a same-module `def name(...) -> <scalar>` -- Increment A
        # (`var rawCounter = compute()`): the callee's own return annotation
        # is a confident kind source even without GimpleGen type inference.
        return _b if _b is not None else _FUNC_RET_KIND.get(value.func.name)
    if isinstance(value, N.BinaryOp):
        lk = _strict_init_kind(value.left, env)
        rk = _strict_init_kind(value.right, env)
        if lk is None or rk is None:
            return None
        if lk == rk:
            return lk
        if {lk, rk} == {'i', 'd'}:
            return 'd'
        return None
    return None


def _outer_boxable_locals(outer: N.FunctionDef) -> dict:
    """`{name: (VarDecl, kind)}` for every top-level `var name = <init>`
    directly in `outer`'s own body whose value v0's capture box can
    represent -- kind 'i' (int/bool, Increment 0), 'd' (float) or 'p'
    (string) (Increment C). Increment A: the initializer no longer has to
    be a bare int literal, only statically confident in kind (explicit
    `Int`/`Float64`/`String`-family annotation, or a `_strict_init_kind`
    match)."""
    env = _static_env(outer)
    out = {}
    for s in outer.body:
        if not isinstance(s, N.VarDecl):
            continue
        k = _ann_kind(s.type_ann)
        if k is None:
            k = _strict_init_kind(s.value, env)
        if k in ('i', 'd', 'p'):
            out[s.name] = (s, k)
    return out


def _called_from_nested_async(outer: N.FunctionDef, name: str) -> bool:
    """True if `name` (a hoisted nested async's bare name) is invoked from
    inside a FURTHER-nested `async def` sibling. The box-handle threading
    only covers `outer`'s own body plus ordinary nested sibling functions
    (`_thread_box_through_siblings`), not a nested async's own driven call
    sites (`async for` / await drive loops), so such a shape is refused to
    the cpp path rather than risk an unthreaded call -- never a
    miscompile."""
    for s in outer.body:
        if isinstance(s, N.FunctionDef) and getattr(s, 'is_async', False):
            hits: list = []
            for st in s.body:
                _find_calls_to(st, name, hits)
            if hits:
                return True
    return False


def _outer_all_locals(outer: N.FunctionDef) -> set:
    """Every name `outer` itself binds (params + any locally-declared/
    assigned name, any type) -- used only to detect whether a nested
    async def captures ANYTHING from its enclosing scope at all, before
    checking whether v0 can actually support that specific capture."""
    return ({p for p, _a in outer.params}
            | gimple_ctypes._declared_vars_body(outer.body))


def _capture_scan_body(stmts: list) -> list:
    """`stmts`, with every lock-with statement (`with BlockingScopedLock/
    BlockingSpinLock(...):`) replaced by its own body inlined -- used ONLY
    to feed free-variable detection below. `_rewrite_async_stmts` elides a
    lock-with's context-manager expression ENTIRELY (see `_is_lock_with`),
    so e.g. `with BlockingScopedLock(lock): ...` never actually references
    `lock` in the compiled body -- without this, free-variable detection
    would see `lock` as a "used" identifier and refuse the capture as an
    unsupported (v0 int-only) capture even though the real compiled body
    never touches it. Duplicate identifier collection for a node that
    happens to get walked twice (this flattening's own recursion, plus
    `_used_idents_node`'s later full walk of a still-nested construct
    inside a KEPT statement) is harmless -- the caller only cares about
    set membership."""
    out = []
    for s in stmts:
        if _is_lock_with(s):
            out.extend(_capture_scan_body(s.body))
            continue
        out.append(s)
        for k, v in vars(s).items():
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                out.extend(_capture_scan_body(v))
    return out


def _nested_async_capture_plan(inner: N.FunctionDef, outer: N.FunctionDef) -> dict | None:
    """`{}` if `inner` captures nothing from `outer` (the common case --
    proceed exactly as before); a non-empty `{name: VarDecl}` are the
    captures to box; `None` when `inner` captures something from `outer`
    that v0 cannot support -- distinct from "no captures at all" so the
    caller can refuse (fall through to the cpp path) instead of silently
    compiling a body that references an unresolved bare name."""
    all_outer = _outer_all_locals(outer)
    used = set()
    for b in _capture_scan_body(inner.body):
        used |= gimple_ctypes._used_idents_node(b)
    inner_declared = ({p for p, _a in inner.params}
                       | gimple_ctypes._declared_vars_body(inner.body))
    captured_names = (used - inner_declared) & all_outer
    if not captured_names:
        return {}
    if _called_from_nested_async(outer, inner.name):
        return None            # unthreadable call site -- refuse (cpp path)
    boxable = _outer_boxable_locals(outer)
    penv = _static_env(outer)          # param annotation kinds + callsite contract
    outer_param_names = {p for p, _a in outer.params}
    plan: dict = {}
    for n in captured_names:
        if n in boxable:
            decl, k = boxable[n]
            plan[n] = (decl, k)
            continue
        if n in outer_param_names:      # Increment B: a captured PARAMETER
            k = penv.get(n)
            if k in ('i', 'd', 'p'):
                plan[n] = (None, k)
                continue
        return None                     # something v0 can't box -- refuse
    return plan


def _cap_rewrite_expr(node, box_names: dict):
    """Replace every read of a captured name with the kind-appropriate box
    getter (`__mojo_box_get_i64/_d/_p`) applied to `<box-handle ident>`.
    `box_names` maps the captured bare name to a `(cident, kind)` pair:
    `cident` is the C identifier holding its box handle IN THIS SCOPE (the
    nested body's own hidden parameter, or the enclosing function's own
    now-boxed local -- same name, new meaning); `kind` is 'i'/'d'/'p'."""
    if node is None or not hasattr(node, '__dict__'):
        return node
    if isinstance(node, N.IdentExpr) and node.name in box_names:
        _ci, _k = box_names[node.name]
        return _call(_BOX_SHIMS[_k][1], [_c_ident(_ci)])
    for k, v in list(vars(node).items()):
        if k in ('line', 'col'):
            continue
        if isinstance(v, list):
            setattr(node, k, [_cap_rewrite_expr(x, box_names) if hasattr(x, '__dict__') else x
                              for x in v])
        elif hasattr(v, '__dict__'):
            setattr(node, k, _cap_rewrite_expr(v, box_names))
    return node


def _cap_rewrite_stmts(stmts: list, box_names: dict) -> list:
    """Rewrite every read/write of a captured name (see _cap_rewrite_expr)
    throughout `stmts`. Never descends into a nested FunctionDef -- a
    further-nested closure resolves/handles its OWN captures separately
    (and, critically, must not have this scope's box_names mapping
    applied to whatever unrelated bare names it happens to also use)."""
    out = []
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            out.append(s)
            continue
        if (isinstance(s, N.AssignStmt) and isinstance(s.target, N.IdentExpr)
                and s.target.name in box_names):
            bname, bk = box_names[s.target.name]
            val = _cap_rewrite_expr(s.value, box_names)
            out.append(N.ExprStmt(value=_call(_BOX_SHIMS[bk][2], [_c_ident(bname), val])))
            continue
        if (isinstance(s, N.AugAssignStmt) and isinstance(s.target, N.IdentExpr)
                and s.target.name in box_names):
            bname, bk = box_names[s.target.name]
            cur = _call(_BOX_SHIMS[bk][1], [_c_ident(bname)])
            rhs = _cap_rewrite_expr(s.value, box_names)
            new_val = N.BinaryOp(op=s.op[:-1], left=cur, right=rhs)
            out.append(N.ExprStmt(value=_call(_BOX_SHIMS[bk][2], [_c_ident(bname), new_val])))
            continue
        if isinstance(s, N.VarDecl) and s.name in box_names:
            # A captured name re-declared in the SAME scope that captures
            # it can't happen (shadowing would make it a distinct local,
            # not a capture) -- guard rather than silently mis-rewrite.
            out.append(s)
            continue
        if isinstance(s, N.TryStmt):
            for h in (s.handlers or []):
                h.body = _cap_rewrite_stmts(h.body, box_names)
        for k, v in list(vars(s).items()):
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                setattr(s, k, _cap_rewrite_stmts(v, box_names))
            elif isinstance(v, list):
                setattr(s, k, [_cap_rewrite_expr(x, box_names) if hasattr(x, '__dict__') else x for x in v])
            elif hasattr(v, '__dict__'):
                setattr(s, k, _cap_rewrite_expr(v, box_names))
        out.append(s)
    return out


def _find_calls_to(node, name: str, out: list):
    """Every CallExpr(func=IdentExpr(name)) in `node`, never descending
    into a nested FunctionDef (mirrors _cap_rewrite_stmts's own pruning
    -- a further-nested closure's own calls are its own business)."""
    if node is None or not hasattr(node, '__dict__'):
        return
    if isinstance(node, N.FunctionDef):
        return
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr) and node.func.name == name:
        out.append(node)
    for v in vars(node).values():
        if isinstance(v, list):
            for x in v:
                if hasattr(x, '__dict__'):
                    _find_calls_to(x, name, out)
        elif hasattr(v, '__dict__'):
            _find_calls_to(v, name, out)


def _collect_nested_ordinary_funcs(stmts: list, out: dict) -> None:
    """`out[name] = FunctionDef` for every ordinary (non-async, non-
    generator) function nested ANYWHERE within `stmts`, descending
    through nested scopes. Any hoisted async def is already gone from
    the tree by the time this runs (`_hoist_nested_async` removed it)."""
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            if not getattr(s, 'is_async', False) and not getattr(s, 'is_generator', False):
                out[s.name] = s
                _collect_nested_ordinary_funcs(s.body, out)
            continue
        for k, v in vars(s).items():
            if k in ('line', 'col'):
                continue
            if isinstance(v, list) and v and _looks_like_stmt_list(v):
                _collect_nested_ordinary_funcs(v, out)


def _fn_refs_captures(fn: N.FunctionDef, cap_names: set) -> bool:
    """True if `fn`'s own body directly reads/writes one of `cap_names`
    (not counting a deeper nested function's references, nor a name `fn`
    itself re-declares/shadows)."""
    used = set()
    for b in _capture_scan_body(fn.body):
        used |= gimple_ctypes._used_idents_node(b)
    declared = ({p for p, _a in fn.params}
                | gimple_ctypes._declared_vars_body(fn.body))
    return bool((used - declared) & cap_names)


def _hidden_box_name(n: str) -> str:
    """The C identifier a threaded nested function receives the box
    handle for captured local `n` under (its hidden trailing param)."""
    return f'__cap_{n}'


def _append_box_args(call, cap_map: dict) -> None:
    """Append the box-handle hidden-param identifier as a trailing
    IdentExpr argument to `call`, for each captured name. Builds the
    name by string concatenation (not by subscripting a local dict
    comprehension) so the self-hosted compiler infers it as `char *`."""
    for n in cap_map:
        call.args.append(_c_ident(_hidden_box_name(n)))


def _append_cap_args(call, cap_map: dict) -> None:
    """Append each captured NAME itself (the enclosing function's own
    now-boxed local) as a trailing IdentExpr argument to `call`."""
    for n in cap_map:
        call.args.append(_c_ident(n))


def _apply_nested_async_capture(inner: N.FunctionDef, outer: N.FunctionDef, cap_map: dict):
    """Wires a non-empty `_nested_async_capture_plan` result: boxes each
    captured outer local (mutating its declaring VarDecl in place),
    rewrites the REST of `outer`'s own body to read/write the box instead
    of a plain scalar, rewrites `inner`'s body to read/write the SAME box
    through a hidden trailing parameter, and appends that hidden
    parameter (plain `Int`, so `_lower_one_async`'s ordinary
    `__mojo_gen_arg` prologue binds it with zero further changes there)
    to `inner.params`, plus a matching trailing argument at every call to
    `inner.name` inside `outer`'s own body (create_task(wrapper()) and
    the bare `wrapper()` detached-async idiom both already route through
    the ordinary arg list from here on).

    Cross-closure case (the bug doc's item 4): when a FURTHER-nested
    ordinary sibling function (`caller()`, defined alongside `inner`
    inside `outer`) is the one that actually calls `inner` -- or itself
    references a captured local, or calls another such function -- the
    box handle(s) are threaded THROUGH that sibling too: it receives
    each box as its own hidden trailing `Int` parameter, its calls to
    `inner` / other threaded siblings get the matching trailing
    argument, its own direct reads/writes of a captured name are
    rewritten through the box, and the call to it from `outer`'s body
    forwards `outer`'s own box local. This is the same
    transitive-closure-through-an-ordinary-nested-function shape the
    ordinary compiled path's own 2026-07-27 fix solved for plain
    `{mut}` closures, done here as a pure AST rewrite over the plain
    `int64_t` box handle."""
    box_kind = {n: k for n, (_d, k) in cap_map.items()}
    hidden = {n: (_hidden_box_name(n), box_kind[n]) for n in cap_map}
    outer_box = {n: (n, box_kind[n]) for n in cap_map}

    prepend: list = []
    for name, (decl, k) in cap_map.items():
        newshim = _BOX_SHIMS[k][0]
        if decl is not None:
            decl.value = _call(newshim, [decl.value])
        else:
            # Increment B: a captured PARAMETER has no declaring VarDecl --
            # rename the raw param and prepend a box-init reading it, so the
            # bare param name now denotes the box handle in `outer`'s body
            # (the same invariant a boxed body-local satisfies in place).
            outer.params = [((_capsrc_name(pn) if pn == name else pn), pa)
                            for pn, pa in outer.params]
            prepend.append(N.VarDecl(
                name=name, type_ann=None,
                value=_call(newshim, [_c_ident(_capsrc_name(name))])))
    if prepend:
        outer.body = prepend + list(outer.body)

    outer.body = _cap_rewrite_stmts(outer.body, outer_box)
    inner.body = _cap_rewrite_stmts(inner.body, hidden)
    inner.params = list(inner.params) + [(_hidden_box_name(n), "Int") for n in cap_map]

    # ── transitive threading through ordinary nested sibling functions ──
    _thread_box_through_siblings(inner.name, outer, cap_map, hidden, set(cap_map))
    # `outer.body` (reassigned just above, prepend + rewrites included) is
    # now the live body; `_hoist_nested_async` finishes by filtering the
    # hoisted async defs out of THIS list, so nothing is lost.
    return prepend


def _fn_body_calls(fn: N.FunctionDef, name: str) -> list:
    hits: list = []
    for st in fn.body:
        _find_calls_to(st, name, hits)
    return hits


def _thread_box_through_siblings(inner_name: str, outer: N.FunctionDef,
                                 cap_map: dict, hidden: dict, cap_names: set) -> None:
    """See `_apply_nested_async_capture`'s docstring, cross-closure case.
    `inner_name` is the hoisted nested async's bare name; every ordinary
    function nested in `outer` that (transitively) calls it or references
    a captured local receives the box handle(s) as hidden trailing
    params, with its calls and the call to it from `outer` given the
    matching trailing arguments."""
    nested_funcs: dict = {}
    for st in outer.body:
        if (isinstance(st, N.FunctionDef) and not getattr(st, 'is_async', False)
                and not getattr(st, 'is_generator', False)):
            nested_funcs[st.name] = st
            _collect_nested_ordinary_funcs(st.body, nested_funcs)
    all_names: list = list(nested_funcs.keys())
    needy: list = []
    for fname in all_names:
        fn = nested_funcs[fname]
        if len(_fn_body_calls(fn, inner_name)) > 0 or _fn_refs_captures(fn, cap_names):
            needy.append(fname)
    changed = True
    while changed:
        changed = False
        for fname in all_names:
            if fname in needy:
                continue
            fn = nested_funcs[fname]
            hit = False
            for other in needy:
                if len(_fn_body_calls(fn, other)) > 0:
                    hit = True
            if hit:
                needy.append(fname)
                changed = True
    for fname in needy:
        fn = nested_funcs[fname]
        fn.body = _cap_rewrite_stmts(fn.body, hidden)
        new_params: list = list(fn.params)
        for n in cap_map:
            new_params.append((_hidden_box_name(n), 'Int'))
        fn.params = new_params
        targets: list = [inner_name]
        for other in needy:
            targets.append(other)
        for tgt in targets:
            if tgt == fname:
                continue
            for call in _fn_body_calls(fn, tgt):
                _append_box_args(call, cap_map)
    # calls that live directly in `outer`'s own body (not inside a nested
    # function) read `outer`'s own now-boxed local by name.
    outer_targets: list = [inner_name]
    for other in needy:
        outer_targets.append(other)
    for tgt in outer_targets:
        hits: list = []
        for st in outer.body:
            _find_calls_to(st, tgt, hits)
        for call in hits:
            _append_cap_args(call, cap_map)


def _hoist_nested_async(stmts: list, meta: list):
    """A `@parameter async def wrapper(): ...` local to an ordinary
    function (the create_task(wrapper()) idiom) is lowered exactly like a
    top-level one, EXCEPT its base is qualified by the enclosing function's
    name (`__mgco_<outer>_<wrapper>`) -- two different enclosing functions
    may each define their own nested helper with the SAME bare name (a
    real shape this project's test suite specifically covers), so a flat
    `_generator_api`-style registration would collide. Returns
    (stmts_with_nested_defs_removed, hoisted_body_defs,
    {enclosing_fn_name: {nested_name: qualified_base}})."""
    hoisted = []
    local_maps: dict[str, dict[str, str]] = {}
    _FUNC_RET_KIND.clear()
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            _rk = _ann_kind(getattr(s, 'return_type', None))
            if _rk:
                _FUNC_RET_KIND[s.name] = _rk
    for s in stmts:
        if not (isinstance(s, N.FunctionDef) and not getattr(s, 'is_generator', False)
                and not getattr(s, 'is_async', False)):
            continue
        rename = {}
        # `_apply_nested_async_capture` rewrites (and may reassign) `s.body`
        # in place -- capture reads/writes in the enclosing body, the box
        # init prepend. Iterate a stable snapshot of the ORIGINAL nested
        # defs, then rebuild `s.body` by filtering the (rewritten) current
        # `s.body` -- NOT from a separately-accumulated `kept` list, which
        # would drop those in-body rewrites (an enclosing-scope write of a
        # captured local becomes a new __mojo_box_set_* ExprStmt node).
        original_body = list(s.body)
        for inner in original_body:
            if isinstance(inner, N.FunctionDef) and getattr(inner, 'is_async', False):
                base = f'__mgco_{s.name}_{inner.name}'
                if any(isinstance(n, N.YieldExpr) for n in _walk(inner)):
                    ok, _why = _eligible_async_gen(inner, nested=True)
                    if ok:
                        # Increment D: a mutable outer capture into a nested
                        # async GENERATOR is boxed exactly like the plain
                        # `async def` branch below. A capture v0's box
                        # cannot represent -- or one reached only through a
                        # driven `async for` consumer, which the box-handle
                        # threading does not cover -- yields `None` here and
                        # falls through to the cpp path unchanged.
                        cap_map = _nested_async_capture_plan(inner, s)
                        if cap_map is None:
                            continue
                        if cap_map:
                            _apply_nested_async_capture(inner, s, cap_map)
                        hoisted.append(_lower_one_async_gen(inner, meta, base=base))
                        meta[-1]['nested'] = True
                        rename[inner.name] = base
                        continue
                else:
                    cap_map = _nested_async_capture_plan(inner, s)
                    if cap_map is not None:
                        ok, _why = _eligible_async(inner, nested=True)
                        if ok:
                            if cap_map:
                                _apply_nested_async_capture(inner, s, cap_map)
                            hoisted.append(_lower_one_async(inner, meta, base=base))
                            meta[-1]['nested'] = True
                            rename[inner.name] = base
                            continue
        if rename:
            s.body = [x for x in s.body
                      if not (isinstance(x, N.FunctionDef)
                              and getattr(x, 'is_async', False)
                              and x.name in rename)]
            local_maps[s.name] = rename
    return stmts, hoisted, local_maps


_CVAR = '__c'


def _mojo_to_c_type(ann: str) -> str:
    return {
        'Int': 'int64_t', 'Int64': 'int64_t', 'Int32': 'int64_t', 'int': 'int64_t',
        'Bool': '_Bool', 'bool': '_Bool',
        'String': 'char *', 'StringLiteral': 'char *', 'str': 'char *',
        'float': 'double',
        '': 'int64_t', None: 'int64_t',
    }.get(ann, 'int64_t')


def _lower_one(fn: N.FunctionDef, meta: list,
               struct_name: str | None = None,
               struct_def=None) -> N.FunctionDef:
    is_method = struct_name is not None
    # A @classmethod generator method: `cls` is NOT a real typed receiver
    # (verified in _eligible to be unreferenced in the body). Its start
    # signature carries an opaque, never-read int64_t placeholder in slot
    # 0 -- exactly the shape gimple_gen_methods.py's `_generator_method_
    # api` call-site lowering already expects for a classmethod generator
    # -- but the trampoline / body have NO `{Struct} *` param, so for
    # emit_c/body purposes this behaves like a free-function generator
    # with one extra leading (ignored) int64_t arg slot.
    is_classmethod = is_method and (getattr(fn, 'decorators', None) or []) == ['classmethod']
    has_self = is_method and not is_classmethod
    base = (f'__mgco_{N._as_str(struct_name)}_{N._as_str(fn.name)}' if is_method
            else f'__mgco_{N._as_str(fn.name)}')
    body_name = f'{base}_body'
    env = _static_env(fn, struct_def)
    kind, _ = _generator_value_kind(fn, env)
    kind = kind or 'i'

    real_params = fn.params[1:] if is_method else fn.params
    # arg 0 is `self`/`cls` (a method), so ordinary params start at
    # __mojo_gen_arg index 1; a plain function starts at 0.
    arg_base = 1 if is_method else 0
    # Per-real-param yield C kind: the param's own annotation first, then
    # the unanimous cross-call-site contract (env, populated by
    # _scan_callsite_param_kinds). A 'd' (double) param can't round-trip
    # through the int64_t arg ABI as a plain (int64_t) cast -- it needs a
    # bit-cast at the call site (emit_c's arg_fwd) and the reinterpreting
    # __mojo_gen_arg_d reader here.
    param_kinds = []
    for pname, pann in real_params:
        k = _ann_kind(pann)
        if k is None:
            v = env.get(pname)
            k = v if isinstance(v, str) else None
        param_kinds.append(k)
    prologue = []
    for i, (pname, _pann) in enumerate(real_params):
        if param_kinds[i] == 'd':
            prologue.append(N.VarDecl(name=pname, type_ann='Float64',
                                      value=_call('__mojo_gen_arg_d',
                                                  [_c_ident(_CVAR),
                                                   N.IntLiteral(value=arg_base + i)])))
        else:
            prologue.append(N.VarDecl(name=pname, type_ann=None,
                                      value=_call(ARG_SHIM, [_c_ident(_CVAR),
                                                             N.IntLiteral(value=arg_base + i)])))

    new_body = prologue + _rewrite_stmts([_deep_copy_stmt(s) for s in fn.body], _CVAR, kind)
    body_params = [(_CVAR, 'Int')]
    if has_self:
        body_params.append(('self', struct_name))
    body_fd = N.FunctionDef(
        name=body_name,
        params=body_params,
        return_type=None,
        body=new_body,
    )
    body_fd.is_generator = False
    body_fd.is_async = False

    _lead = ([f'{struct_name} *'] if has_self else
             ['int64_t'] if is_classmethod else [])
    _real_ct = []
    for (_n, a), pk in zip(real_params, param_kinds):
        ct = _mojo_to_c_type(a)
        if ct == 'int64_t' and pk == 'd':
            ct = 'double'          # unannotated param, kind from call sites
        _real_ct.append(ct)
    c_params = _lead + _real_ct
    meta.append({
        'name': N._as_str(fn.name),
        'struct': struct_name,
        'is_method': is_method,
        'has_self': has_self,
        'is_classmethod': is_classmethod,
        'base': base,
        'body_name': body_name,
        'params': c_params,
        'nargs': len(real_params),
        'value_ctype': _KIND_CTYPE[kind],
        'value_kind': kind,
        'tuple_slot_ctypes': _generator_tuple_slots(fn, env) if kind == 'tuple' else None,
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
extern void    __mojo_gen_resume_once (int64_t);
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
    # `has_self` (a real `{Struct} *` receiver) selects the method
    # trampoline shape; a @classmethod generator has NO such receiver
    # (its leading int64_t `cls` slot is just an ordinary ignored arg),
    # so it uses the plain free-function `__mojo_gen_new_{n}` path.
    is_method = meta_entry.get('has_self', meta_entry.get('is_method'))
    kind = meta_entry.get('value_kind', 'i')
    vct = _KIND_CTYPE[kind]
    nslots = len(params)                     # start-fn arg count (self + real args)
    start_params = ', '.join(f'{ct} __a{i}' for i, ct in enumerate(params)) or 'void'
    # A `double` arg slot is stashed as its raw 64 bits (reader side is
    # __mojo_gen_arg_d); every other slot is an int64_t / pointer that a
    # plain cast carries losslessly.
    def _fwd(i):
        if params[i].strip() == 'double':
            return (f', ({{ int64_t __t{i}; double __s{i} = __a{i}; '
                    f'__builtin_memcpy(&__t{i}, &__s{i}, sizeof __t{i}); __t{i}; }})')
        return f', (int64_t)__a{i}'
    arg_fwd = ''.join(_fwd(i) for i in range(nslots))
    new_params = ', '.join(['int64_t'] + ['int64_t'] * nslots)
    new_fn = (f'__mojo_gen_new_m{nslots - 1}' if is_method
              else f'__mojo_gen_new_{nslots}')
    if kind == 'p':
        value_unbox = f'({vct})__mojo_gen_value ((int64_t)__g)'
    elif kind == 'tuple':
        # DESIGN.html R3 exception, NOT routed through gen._coerce_to_type:
        # this whole function builds a raw C-source TEMPLATE STRING with no
        # `gen` in scope at all (it emits static trampoline C, not
        # per-call-site codegen) - `kind` is the generator's OWN declared
        # yield-value kind (proven statically per-generator, same as the
        # `kind == 'p'` branch just above using `vct` the same way), not a
        # runtime guess, so this cast is safe; it just has no chokepoint to
        # route through structurally.
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
    # The native-Future-class bridge (_rewrite_native_future_refs) drops the
    # user's `Future` StructDef wholesale, so a module that ONLY defines
    # such a class produces no coro `meta` -- but its ordinary (sync)
    # module-level functions still call `.cancel()` / `.set_exception()` /
    # `.add_done_callback()` etc. on the bare int64_t handle and need the
    # __mojo_future_* shim externs declared + the sync hooks armed.
    if _NATIVE_FUTURE_CLASSES:
        gen._native_future_bridge = True
    if not meta and not _NATIVE_FUTURE_CLASSES:
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
    gen.func_param_types.setdefault('__mojo_gen_arg_d', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_arg_d', 'double')
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
    gen.func_param_types.setdefault('__mojo_gen_resume', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_resume', 'int64_t')
    gen.func_param_types.setdefault('__mojo_gen_value', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_value', 'int64_t')
    gen.func_param_types.setdefault('__mojo_gen_destroy', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_destroy', 'void')
    # "Detached async" (bugs/hard/CODEGEN_coro_detached_async_take_handle.md)
    # -- the resume_fn half of the `_coro_resume_fn`/`_coro_destroy_fn`
    # pair BUILTIN_VALUE_MAP substitutes this for under MOJO_CORO=
    # stackswitch (gimple_codegen.GimpleGen.__init__); `__mojo_gen_destroy`
    # above already has the exact destroy_fn shape needed as-is.
    gen.func_param_types.setdefault('__mojo_gen_resume_once', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_resume_once', 'void')
    # Nested-async mutable closure capture (bugs/hard/CODEGEN_coro_nested_
    # async_closure_capture.md) -- v0 int-literal-local heap box, see
    # _nested_async_capture_plan's own docstring.
    gen.func_param_types.setdefault(_BOX_NEW, ['int64_t'])
    gen.func_return_types.setdefault(_BOX_NEW, 'int64_t')
    gen.func_param_types.setdefault(_BOX_GET, ['int64_t'])
    gen.func_return_types.setdefault(_BOX_GET, 'int64_t')
    gen.func_param_types.setdefault(_BOX_SET, ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault(_BOX_SET, 'void')
    # Increment C: typed capture-box shims (float / string cell).
    gen.func_param_types.setdefault('__mojo_box_new_d', ['double'])
    gen.func_return_types.setdefault('__mojo_box_new_d', 'int64_t')
    gen.func_param_types.setdefault('__mojo_box_get_d', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_box_get_d', 'double')
    gen.func_param_types.setdefault('__mojo_box_set_d', ['int64_t', 'double'])
    gen.func_return_types.setdefault('__mojo_box_set_d', 'void')
    gen.func_param_types.setdefault('__mojo_box_new_p', ['char *'])
    gen.func_return_types.setdefault('__mojo_box_new_p', 'int64_t')
    gen.func_param_types.setdefault('__mojo_box_get_p', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_box_get_p', 'char *')
    gen.func_param_types.setdefault('__mojo_box_set_p', ['int64_t', 'char *'])
    gen.func_return_types.setdefault('__mojo_box_set_p', 'void')
    gen.func_param_types.setdefault('__mojo_gen_last_yield_was_wd', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_last_yield_was_wd', 'int64_t')
    gen.func_param_types.setdefault('__mojo_gen_yield_tagged', ['int64_t', 'int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_gen_yield_tagged', 'int64_t')
    gen.func_param_types.setdefault('__mojo_async_run_gen', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_async_run_gen', 'void')
    # Eager task scheduling (bugs/COMPILE_FAIL_asyncio_queues.md gap 3).
    gen.func_param_types.setdefault('__mojo_async_task_schedule', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_async_task_schedule', 'void')
    gen.func_param_types.setdefault('__mojo_async_await_task', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_async_await_task', 'int64_t')
    # Awaitable protocol: Future/Event handles (runtime/mojo_coro_gen.c).
    gen.func_param_types.setdefault('__mojo_future_new', [])
    gen.func_return_types.setdefault('__mojo_future_new', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_done', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_done', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_result', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_result', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_set_result', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_future_set_result', 'void')
    gen.func_param_types.setdefault('__mojo_future_set_exception', ['int64_t', 'int64_t', 'char *'])
    gen.func_return_types.setdefault('__mojo_future_set_exception', 'void')
    gen.func_param_types.setdefault('__mojo_future_exception', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_exception', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_cancel', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_cancel', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_cancelled', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_cancelled', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_set_running_or_notify_cancel', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_future_set_running_or_notify_cancel', 'int64_t')
    gen.func_param_types.setdefault('__mojo_future_add_done_callback', ['int64_t', 'int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_future_add_done_callback', 'void')
    gen.func_param_types.setdefault('__mojo_future_remove_done_callback', ['int64_t', 'int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_future_remove_done_callback', 'int64_t')
    gen.func_param_types.setdefault('__mojo_async_await_future', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_async_await_future', 'int64_t')
    gen.func_param_types.setdefault('__mojo_event_new', [])
    gen.func_return_types.setdefault('__mojo_event_new', 'int64_t')
    gen.func_param_types.setdefault('__mojo_event_set', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_event_set', 'void')
    gen.func_param_types.setdefault('__mojo_event_is_set', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_event_is_set', 'int64_t')
    gen.func_param_types.setdefault('__mojo_event_clear', ['int64_t'])
    gen.func_return_types.setdefault('__mojo_event_clear', 'void')
    gen.func_param_types.setdefault('__mojo_async_await_event_wait', ['int64_t', 'int64_t'])
    gen.func_return_types.setdefault('__mojo_async_await_event_wait', 'int64_t')
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
            # `_emit_generator_start_call` (gimple_gen_calls.py) pads a
            # caller's missing trailing args from `gen._func_param_defaults
            # [f"{base}_start"]`, exactly like the cpp path's own
            # `_register_free_generator` populates for a cpp-lowered
            # generator (gimple_module_gen.py) -- this stackswitch path
            # only ever set `api['defaults']` (consulted nowhere) and
            # never this key, so a generator called with fewer args than
            # declared (`def prod(n, step=10): ...` called as `prod(3)`)
            # padded the missing slot with a typed zero instead of the
            # real default, silently miscompiling every such call.
            gen._func_param_defaults[f"{m['base']}_start"] = m['defaults']
        if m.get('is_method'):
            gen._generator_method_api[(m['struct'], m['name'])] = api
            gen._supported_generator_methods[(m['struct'], m['name'])] = None
        elif m.get('nested'):
            # A local `@parameter async def` (create_task's wrapper idiom):
            # every reference is rewritten directly to its qualified
            # `{base}_start` name by gimple_gen_coro's own local_map (two
            # different enclosing functions may reuse the same bare name),
            # so this must NOT be keyed by the bare name in the shared
            # _generator_api namespace -- keyed by the qualified base
            # instead, solely so gen_module's extern-decl preamble block
            # (which just iterates _generator_api.values()) still declares
            # these trampolines. There is no top-level def with this bare
            # name to skip emitting, so _supported_generators is untouched.
            gen._generator_api[m['base']] = api
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
