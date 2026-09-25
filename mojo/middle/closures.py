"""Shared nested-function (closure) discovery for all codegen backends.

ONE copy of the real machinery: capture discovery, mut-name analysis,
sibling shared-env merge, and transitive capture fixup. GIMPLE
(`mojo/backend_gimple/module_gen.py`) and the formal arm64 path
(`formal/build.py`) both call `discover_closures`; future architecture
backends must too. Do not fork a simplified hoist.

`ctx` is any backend object exposing the TypeCtx protocol:
    var_types, func_return_types, struct_field_types (dicts)
    _func_param_defaults, _nested_async_api (dicts)
    _method_threaded_comptime_params (dict)
    _quick_type(expr) -> str
    _resolve_type(ptype) -> str
    _infer_return_type(body) -> str
    _struct_method_overload_ids(structdef) -> list[str]
Optional:
    selfhost_param_ctype(pname, ptype, fn) -> str | None
        (GIMPLE self-host only; formal omits it)
"""
from __future__ import annotations

from fire_compiler import (
    AssignStmt, AugAssignStmt, CallExpr, ExprStmt, ForStmt, FunctionDef,
    IdentExpr, IfStmt, LambdaExpr, MemberExpr, StructDef, TryStmt, VarDecl,
    WhileStmt, WithStmt,     _as_funcdef_node, _as_str, _as_list,
)
from mojo.middle.types import _declared_vars_body, _mojo_type, _used_idents_node
from mojo.middle.exprtypes import _walk_ast, _struct_name_of
from mojo.middle.solvers import ClosureInfo


def _selfhost_fn_reassigns_method(_fn, _pnames=('gen', 'self')) -> bool:
    """True if `_fn`'s body monkey-patches a METHOD on the `gen`/`self` param
    (`gen._emit = intercepted_emit` — the `_gen_stmt_TryStmt` emit-
    interception idiom). Those functions must keep the param OPAQUE in the
    closure pre-pass: typed as `GimpleGen *`, the nested closures capture a
    real void method as a value and the reassignment / later calls don't
    lower to valid C. try/except codegen already doesn't run natively, so
    leaving it stubbed (as before) is no regression.

    Only the METHOD-reassignment shape counts — the RHS is a nested `def`
    name or a lambda. An ORDINARY `self.<datafield> = value` assignment
    (which `gen_module_impl` and most GimpleGen methods do constantly) must
    NOT trip this: it would wrongly force `self`/`gen` to `int64_t` in the
    closure pre-pass, so `_scan_for_closures`'s capture of `self` typed
    `int64_t` -> `self._mutated_free_names(...)` stubbed -> `mojo_set_union
    (self, ...)` -> SEGV compiling any program with a nested `def`."""
    _local_defs = {_d.name for _d in _walk_ast(getattr(_fn, 'body', []) or [])
                   if isinstance(_d, FunctionDef)}
    for _n in _walk_ast(getattr(_fn, 'body', []) or []):
        if (isinstance(_n, AssignStmt) and isinstance(_n.target, MemberExpr)
                and isinstance(_n.target.obj, IdentExpr)
                and _n.target.obj.name in _pnames):
            _rhs = _n.value
            if isinstance(_rhs, LambdaExpr):
                return True
            if isinstance(_rhs, IdentExpr) and _rhs.name in _local_defs:
                return True
    return False


def _gmi_all_stmts_nonfunc(stmts) -> list:
    """Hoisted out of `gen_module_impl._scan_for_closures` (was a
    2-level-deep nested closure) — see `_gmi_prefold_toplevel_comptime`'s
    docstring. Recursive, pure. Returns a list of statements recursively
    through control flow, NOT entering FunctionDef bodies. Explicit
    per-node-type branches (not `getattr(s, <loop-var>)` + `isinstance`):
    the self-hosted backend's `isinstance(<int64_t>, list)` stub is always
    false, so a dynamic getattr keyed by a runtime attr name would make it
    never recurse into any control flow."""
    result = []
    for s in stmts:
        result.append(s)
        if isinstance(s, FunctionDef):
            continue
        if isinstance(s, IfStmt):
            result.extend(_gmi_all_stmts_nonfunc(s.then_body))
            if s.else_body:
                result.extend(_gmi_all_stmts_nonfunc(s.else_body))
            for _cond, _eb in (s.elifs or []):
                result.extend(_gmi_all_stmts_nonfunc(_eb))
        elif isinstance(s, TryStmt):
            result.extend(_gmi_all_stmts_nonfunc(s.body))
            for _h in (s.handlers or []):
                _hb = getattr(_h, 'body', None)
                if _hb:
                    result.extend(_gmi_all_stmts_nonfunc(_hb))
            if s.else_body:
                result.extend(_gmi_all_stmts_nonfunc(s.else_body))
            if s.finally_body:
                result.extend(_gmi_all_stmts_nonfunc(s.finally_body))
        elif isinstance(s, (WhileStmt, ForStmt, WithStmt)):
            result.extend(_gmi_all_stmts_nonfunc(s.body))
            if isinstance(s, (WhileStmt, ForStmt)) and getattr(s, 'else_body', None):
                result.extend(_gmi_all_stmts_nonfunc(s.else_body))
    return result



def mutated_free_names(inner: FunctionDef, candidate_names) -> frozenset:
    """Which of `candidate_names` `inner`'s own body ever REASSIGNS.

    Moved verbatim from `mojo/backend_gimple/cpp_async.py` (the `gen`
    parameter was unused). Plain `name = ...` counts only in THIS def's
    body (nested defs excluded); augmented assigns count at any depth.
    Those names need by-REFERENCE capture; everything else is by-value.
    """
    mutated: set = set()
    _stack = list(_as_list(inner.body))
    while _stack:
        n = _stack.pop(0)
        if isinstance(n, FunctionDef):
            continue
        if isinstance(n, AssignStmt) and isinstance(n.target, IdentExpr):
            if n.target.name in candidate_names:
                mutated.add(n.target.name)
        elif isinstance(n, AugAssignStmt) and isinstance(n.target, IdentExpr):
            if n.target.name in candidate_names:
                mutated.add(n.target.name)
        elif isinstance(n, IfStmt):
            _stack.extend(n.then_body)
            for _, _eb in n.elifs:
                _stack.extend(_eb)
            if n.else_body:
                _stack.extend(n.else_body)
        elif isinstance(n, (WhileStmt, ForStmt)):
            _stack.extend(n.body)
            if getattr(n, 'else_body', None):
                _stack.extend(n.else_body)
        elif isinstance(n, WithStmt):
            _stack.extend(n.body)
        elif isinstance(n, TryStmt):
            _stack.extend(n.body)
            for _h in (n.handlers or []):
                _stack.extend(_h.body)
            if n.else_body:
                _stack.extend(n.else_body)
            if n.finally_body:
                _stack.extend(n.finally_body)
    return frozenset(mutated)


def discover_closures(ctx, stmts) -> dict:
    """Discover every nested FunctionDef under `stmts`; fill `ctx._all_closures`.

    Returns `ctx._all_closures`: outer_name -> {inner_name -> ClosureInfo}.
    Side effects on ctx: var_types (restored), func_return_types (lifted
    signatures added), _func_param_defaults (lifted defaults), _all_closures.
    """
    ctx._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}

    def _scan_for_closures(ctx, outer_name: str, outer_scope: dict, body: list):
        """Scan a function/method body for nested FunctionDefs and register them as closures."""
        enriched_scope = dict(outer_scope)
        _saved_vt2 = dict(ctx.var_types)
        ctx.var_types.update(outer_scope)
        for bstmt in _gmi_all_stmts_nonfunc(body):
            if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                name = bstmt.target.name
                if name not in enriched_scope:
                    t = ctx._quick_type(bstmt.value)
                    # `original_emit = gen._emit` (a method taken as a value —
                    # the `_gen_stmt_TryStmt` emit-interception idiom): the
                    # body lowers this to a `MojoBoundMethod *` (see
                    # `_lower_bound_method_value`), but `_quick_type` reports
                    # the method's own return type (`void` / `int64_t`). A
                    # mismatched — or `void` — capture makes the env-struct
                    # field disagree with the body's local (hard C error).
                    if (isinstance(bstmt.value, MemberExpr)
                            and isinstance(bstmt.value.obj, IdentExpr)
                            and ctx.var_types.get(bstmt.value.obj.name, '').endswith(' *')):
                        _bmv_owner = _struct_name_of(
                            ctx.var_types[bstmt.value.obj.name])
                        if (f"{_bmv_owner}_{bstmt.value.member}" in ctx.func_return_types
                                and bstmt.value.member not in ctx.struct_field_types.get(_bmv_owner, {})):
                            t = 'MojoBoundMethod *'
                    if t == 'void':
                        t = 'int64_t'
                    enriched_scope[name] = t
                    ctx.var_types[name] = t
            elif isinstance(bstmt, VarDecl):
                if bstmt.name not in enriched_scope:
                    t = ctx._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                    if t == 'void':
                        t = 'int64_t'
                    enriched_scope[bstmt.name] = t
                    ctx.var_types[bstmt.name] = t
        ctx.var_types = _saved_vt2
        # Parallel structures instead of a list-of-3-tuples: a tuple element
        # indexed on the self-hosted compiled path erases to `int64_t`, and
        # the third field here (the set of names each sibling calls) then
        # can't be iterated (`mojo_unsupported_iter` at the sibling-merge
        # loop, silently zeroing out the shared-env grouping under
        # MOJO_NO_SHIM=1). `_sib_calls_flat` maps sibling name -> its called
        # names joined on NUL, so the merge pass re-`split`s a fresh local
        # list-of-str that iterates cleanly.
        _sibling_names: list = []
        _sib_calls_flat: dict = {}   # inner.name -> "\x00"-joined called names
        for stmt in _gmi_all_stmts_nonfunc(body):
            if not isinstance(stmt, FunctionDef):
                continue
            # `_as_funcdef_node`: identity in CPython, but its `-> FunctionDef`
            # annotation gives the self-hosted backend a real `FunctionDef *`
            # view of the otherwise-boxed loop element — without it `inner.name`
            # goes through dynamic getattr and the lifted symbol comes out
            # `outer_<garbage-bytes>`, the `_all_closures` key is garbage, and
            # every nested `def` degrades to a weak "unavailable" stub.
            inner     = _as_funcdef_node(stmt)
            inner_body = _as_list(inner.body)
            inner_params = _as_list(inner.params)
            if inner.is_async and not inner.is_generator:
                continue
            lifted    = f"{outer_name}_{inner.name}"
            # `_as_str` each element: `_used_idents_node` returns a set whose
            # str members erase to boxed int64_t under self-compile, so the
            # `used - inner_declared` difference below misses a declared name
            # (boxed vs clean str hash differently) — that name leaks into
            # `free`, `_as_str(v)` then finds it in `enriched_scope`, and the
            # closure gains a spurious capture whose env-struct allocation
            # (`_alloc_X_env()` vs `(X *)0`) flips run to run.
            used      = set()
            for body_node in inner_body:
                for _ui in _used_idents_node(body_node):
                    used.add(_as_str(_ui))
            inner_assign_targets = set()
            for bstmt in _gmi_all_stmts_nonfunc(inner_body):
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    inner_assign_targets.add(bstmt.target.name)
                elif isinstance(bstmt, ForStmt):
                    tgt = bstmt.target
                    if isinstance(tgt, str):
                        inner_assign_targets.add(tgt)
                    elif hasattr(tgt, 'name'):
                        inner_assign_targets.add(tgt.name)
            # A PLAIN for-loop unpack (`for _pn, _pt in inner.params:`),
            # NOT a comprehension (`{pn for pn, _ in ...}` — tuple-unpack-
            # in-a-comprehension boxes `pn` to int64_t self-hosted) and
            # NOT `for _p in inner.params: _p[0]` either — subscripting a
            # value obtained by single-var for-loop iteration over a real
            # AST list field is a SEPARATE, also-confirmed-broken self-
            # hosted trap (working `==` but corrupted `len()`/hashing on
            # the subscripted slot; see this file's `FromImportStmt.names`
            # fixes and the general writeup in bugs/CODEGEN_selfhost_
            # actual_types_identifier_field_key.md). A plain multi-target
            # unpack directly in the for-statement (not a comprehension,
            # not a subscript) is the one shape confirmed safe for
            # `list[tuple[str, str]]` dataclass fields throughout this
            # session's fixes (e.g. `gen_func`'s own param-seeding loop).
            # Previously this WAS `_p[0]`-subscripted (with an `_as_str`
            # guard) as a fix for the comprehension version — itself the
            # "dominant --dump-full fire.py nondeterminism" per the
            # original comment here — but that fix just swapped one
            # broken shape for the other; confirmed still nondeterministic
            # this session via `mojoc fire.py --dump-full` run twice in a
            # row disagreeing with ITSELF at a closure call's argument
            # count (module_loader.py's `_scan_source` closure).
            _ipn: set = set()
            for _pn, _pt in inner_params:
                _ipn.add(_pn)
            inner_declared: set = set()
            for _idv in (_ipn
                         | _declared_vars_body(inner_body)
                         | inner_assign_targets):
                inner_declared.add(_as_str(_idv))
            outer_params: set = set()
            for _op in outer_scope.keys():
                outer_params.add(_as_str(_op))
            free_globals: set = set()
            for _fg in ctx.func_return_types.keys():
                _fg = _as_str(_fg)
                if _fg not in outer_params:
                    free_globals.add(_fg)
            free         = used - inner_declared - free_globals
            # `_as_str(v)`: elements of `sorted(free)` (a set-of-str) erase
            # to boxed int64_t under self-compile — without the static
            # `str` view `v in enriched_scope` would hash the pointer.
            captures     = []
            for v in _as_list(sorted(free)):
                v = _as_str(v)
                if v in enriched_scope:
                    captures.append((v, enriched_scope[v]))
            _cap_names_so_far = {_cn for _cn, _ in captures}
            _called_names = {nd.func.name for nd in _walk_ast(inner_body)
                              if isinstance(nd, CallExpr) and isinstance(nd.func, IdentExpr)}
            _transitive_mut: set = set()
            for _called in _called_names:
                _t_api = ctx._nested_async_api.get(f"{outer_name}::{_called}")
                if _t_api is None:
                    continue
                for _tn, _tt in (_t_api.get('captures') or []):
                    if _tn not in _cap_names_so_far and _tn in enriched_scope:
                        captures.append((_tn, enriched_scope[_tn]))
                        _cap_names_so_far.add(_tn)
                    if _tn in (_t_api.get('mut_capture_names') or frozenset()):
                        _transitive_mut.add(_tn)
            env_struct   = f"{lifted}_env" if len(captures) > 0 else ""
            ci           = ClosureInfo(lifted, env_struct, captures, inner)
            _inner_dflts = getattr(inner, 'param_defaults', None) or {}
            if _inner_dflts:
                ctx._func_param_defaults[lifted] = [
                    (_pn2, _dv2) for _pn2, _dv2 in _inner_dflts.items()]
            ci.mut_names = mutated_free_names(inner, _cap_names_so_far) | _transitive_mut
            if outer_name not in ctx._all_closures:
                ctx._all_closures[outer_name] = {}
            ctx._all_closures[outer_name][inner.name] = ci
            _sibling_names.append(_as_str(inner.name))
            _sib_calls_flat[_as_str(inner.name)] = '\x00'.join(
                sorted(_as_str(_cnm) for _cnm in _called_names))
            if inner.return_type is not None:
                ctx.func_return_types[lifted] = ctx._resolve_type(inner.return_type)
            else:
                for pname, ptype in inner_params:
                    ctx.var_types[pname] = ctx._resolve_type(ptype)
                ctx.func_return_types[lifted] = ctx._infer_return_type(inner_body)
                ctx.var_types.clear()
            inner_scope = dict(enriched_scope)
            for pn, pt in inner_params:
                inner_scope[pn] = ctx._resolve_type(pt)
            for bstmt in inner_body:
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    name = bstmt.target.name
                    if name not in inner_scope:
                        inner_scope[name] = ctx._quick_type(bstmt.value)
            _scan_for_closures(ctx, lifted, inner_scope, inner_body)

        # Mutually-recursive SIBLING closures (e.g. `_infer_param_types`'s
        # `scan_expr` <-> `scan_nodes`) each got their OWN env struct with
        # only their OWN captures. When one calls the other,
        # `_lower_sibling_closure_call` can forward only the fields whose
        # names match between the two envs — the callee's other captures
        # stay NULL and it SEGVs (`accessed_fields.add(...)` on NULL). Give
        # each connected call-group ONE shared env struct holding the UNION
        # of the group's captures, so any member can call any other by
        # passing its own (now identical-layout) env through.
        if len(_sibling_names) > 1:
            _names_here: set = set()
            for _sc0 in _sibling_names:
                _names_here.add(_as_str(_sc0))
            _adj: dict[str, list] = {}
            for _n in _names_here:
                _adj[_as_str(_n)] = []
            for _nk, _cf in _sib_calls_flat.items():
                _n = _as_str(_nk)
                _cf = _as_str(_cf)
                for _m0 in _cf.split('\x00'):
                    _m = _as_str(_m0)
                    if _m and _m in _names_here and _m != _n:
                        if _m not in _adj[_n]:
                            _adj[_n].append(_m)
                        if _n not in _adj[_m]:
                            _adj[_m].append(_n)
            _seen_names: set = set()
            for _start in sorted(_names_here):
                if _start in _seen_names:
                    continue
                _stack: list = [_start]
                _members: list = []
                while _stack:
                    _cur = _as_str(_stack.pop())
                    if _cur in _seen_names:
                        continue
                    _seen_names.add(_cur)
                    _members.append(_cur)
                    for _nb0 in _adj[_cur]:
                        _nb = _as_str(_nb0)
                        if _nb not in _seen_names:
                            _stack.append(_nb)
                if len(_members) < 2:
                    continue
                _member_cis = [ctx._all_closures[outer_name][_m] for _m in _members]
                _merged_caps: dict[str, str] = {}
                _merged_mut: list = []
                for _mci in _member_cis:
                    for _cap in _mci.captures:  # index, not unpack — tuple-boxing bug
                        _cv = _as_str(_cap[0])
                        if _cv not in _merged_caps:
                            _merged_caps[_cv] = _as_str(_cap[1])
                    for _mn in (getattr(_mci, 'mut_names', None) or []):
                        if _mn not in _merged_mut:
                            _merged_mut.append(_mn)
                if not _merged_caps:
                    continue
                _shared_env = outer_name + "_" + "_".join(sorted(_members)) + "_env"
                _merged_list = [(_cv, _merged_caps[_cv]) for _cv in sorted(_merged_caps)]
                _shared_mut = frozenset([_mn for _mn in _merged_mut if _mn in _merged_caps])
                for _mci in _member_cis:
                    _mci.captures = list(_merged_list)
                    _mci.env_struct = _shared_env
                    _mci.mut_names = _shared_mut

        def _find_re_sub_callbacks(search_body, context_outer):
            for stmt in search_body:
                stmts_to_check = []
                if isinstance(stmt, AssignStmt):
                    stmts_to_check.append(stmt.value)
                elif isinstance(stmt, ExprStmt):
                    stmts_to_check.append(stmt.value)  # ExprStmt uses .value
                elif hasattr(stmt, 'body'):
                    _find_re_sub_callbacks(getattr(stmt, 'body', []), context_outer)
                    for clause in ('orelse', 'handlers', 'finalbody'):
                        _find_re_sub_callbacks(getattr(stmt, clause, []), context_outer)
                for expr in stmts_to_check:
                    if not isinstance(expr, CallExpr):
                        continue
                    func = expr.func
                    if (isinstance(func, MemberExpr)
                            and isinstance(func.obj, IdentExpr)
                            and func.obj.name == 're'
                            and func.member == 'sub'
                            and len(expr.args) >= 2):
                        cb_arg = expr.args[1]
                        if isinstance(cb_arg, IdentExpr):
                            inner_map = ctx._all_closures.get(context_outer, {})
                            if cb_arg.name in inner_map:
                                inner_map[cb_arg.name].is_re_sub_callback = True
        _find_re_sub_callbacks(body, outer_name)

    for s in stmts:
        if isinstance(s, FunctionDef):
            s = _as_funcdef_node(s)   # real FunctionDef view: keeps `pname`/
            # `ptype` from `s.params` as `char *` so `outer_scope` is keyed
            # by the parameter NAME, not a boxed pointer — otherwise a
            # nested closure's `if v in enriched_scope` capture filter never
            # matches and every capture is silently dropped (`return add`
            # from a capturing closure came out a bare funcptr, no env).
            outer_scope: dict = {}
            for pname, ptype in s.params:
                _sh_ct = None
                if not _selfhost_fn_reassigns_method(s):
                    _hook = getattr(ctx, 'selfhost_param_ctype', None)
                    if _hook is not None:
                        # `_hook` is the module-level
                        # `_selfhost_gen_self_param_ctype(gen, pname, ptype,
                        # node)` — a NON-capturing function, so its stored
                        # value is a raw code pointer. Pass `ctx` explicitly
                        # (4 args): the previous 3-arg call site invoked a
                        # capturing nested `def` wrapper through
                        # `mojo_fnptr_call_3`, which jumped to the closure's
                        # DATA pointer and SIGBUS'd
                        # (^EXC_BAD_ACCESS at a heap address; repro:
                        # std/atomic/atomic.mojo).
                        _sh_ct = _hook(ctx, pname, ptype, s)
                outer_scope[pname] = _sh_ct or ctx._resolve_type(ptype)
            _saved_vt = dict(ctx.var_types)
            ctx.var_types.update(outer_scope)
            for stmt in s.body:
                if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                    t = _mojo_type(stmt.type_ann)
                    outer_scope[stmt.name] = t
                    ctx.var_types[stmt.name] = t
                elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                    if stmt.target.name not in outer_scope:
                        t = ctx._quick_type(stmt.value)
                        outer_scope[stmt.target.name] = t
                        ctx.var_types[stmt.target.name] = t
            ctx.var_types = _saved_vt
            _scan_for_closures(ctx, s.name, outer_scope, s.body)
        elif isinstance(s, StructDef):
            _moids = ctx._struct_method_overload_ids(s)
            # index walk, NOT `zip(s.methods, _moids)` — the zip 2-tuple
            # unpack boxes `_oid` on the self-hosted path, so `f"...{_oid}"`
            # emitted the (non-deterministic) POINTER of the empty-string
            # oid into every closure-env struct name for a non-overloaded
            # method (stage2-vs-stage3 idempotency failure).
            for _smi in range(len(s.methods)):
                method = _as_funcdef_node(s.methods[_smi])
                _oid = _as_str(_moids[_smi]) if _smi < len(_moids) else ''
                outer_name = f"{s.name}_{method.name}{_oid}"
                outer_scope = {s.name.lower(): f"{s.name} *"}  # struct instance
                for pname, ptype in method.params:
                    if pname == 'self':
                        outer_scope['self'] = f"{s.name} *"
                    else:
                        outer_scope[pname] = ctx._resolve_type(ptype)
                for _cp_name in ctx._method_threaded_comptime_params.get((s.name, method.name), {}).get(_oid, []):
                    outer_scope[_cp_name] = 'int64_t'
                _saved_vt = dict(ctx.var_types)
                ctx.var_types.update(outer_scope)
                for stmt in method.body:
                    if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                        t = _mojo_type(stmt.type_ann)
                        outer_scope[stmt.name] = t
                        ctx.var_types[stmt.name] = t
                    elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                        if stmt.target.name not in outer_scope:
                            t = ctx._quick_type(stmt.value)
                            outer_scope[stmt.target.name] = t
                            ctx.var_types[stmt.target.name] = t
                ctx.var_types = _saved_vt
                _scan_for_closures(ctx, outer_name, outer_scope, method.body)

    _changed = True
    while _changed:
        _changed = False
        # Index-walk both dict levels, NOT nested `.items()` 2-tuple
        # unpacks: the SECOND one boxes `_ci` itself on the self-hosted
        # path, so `_ci.env_struct = f"{_ci.lifted_name}_env"` below
        # wrote a garbage/degraded string onto a mis-typed handle —
        # a real `MOJO_NO_SHIM=1 --dump myinterpreter.py` corruption
        # (raw heap-garbage bytes in place of a closure-env struct name
        # in the generated .ci, a hard GCC parse failure). Mirrors the
        # closure-typedef-emission loops' identical fix.
        for _outer_name in list(ctx._all_closures):
            _inner_map = ctx._all_closures[_outer_name]
            for _inner_name in list(_inner_map):
                _ci = _inner_map[_inner_name]
                _sub_closures = ctx._all_closures.get(_ci.lifted_name, {})
                if not _sub_closures:
                    continue
                _ci_param_names: set = set()  # index, not unpack — tuple-boxing bug
                for _cipp in _ci.inner_def.params:
                    _ci_param_names.add(_as_str(_cipp[0]))
                _ci_local_assigns = set()
                for _bstmt in _ci.inner_def.body:
                    if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                        _ci_local_assigns.add(_bstmt.target.name)
                _ci_own_vars = (_ci_param_names
                                | _declared_vars_body(_ci.inner_def.body)
                                | _ci_local_assigns)
                _ci_captures_dict = dict(_ci.captures)
                for _sub_ci in _sub_closures.values():
                    for _sv, _st in _sub_ci.captures:
                        if _sv not in _ci_own_vars and _sv not in _ci_captures_dict:
                            _ci.captures.append((_sv, _st))
                            _ci_captures_dict[_sv] = _st
                            if not _ci.env_struct:
                                _ci.env_struct = f"{_ci.lifted_name}_env"
                            _changed = True

    return ctx._all_closures
