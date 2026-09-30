"""Beta-reduction for CAPTURING lambdas bound to a local and called directly.

A `lambda` expression lifts to a top-level C function taking only its own
declared parameters — a plain function POINTER, with nowhere to put the
enclosing function's locals. A lambda that reads one therefore compiled to
a body naming a variable that does not exist there, which the codegen
stubbed to 0: `var n = 7; var f = lambda: n; print(f())` printed 0 —
silently, with exit 0. A nested `def` closure does not have this problem
because it goes through the env-struct mechanism
(`mojo/middle/closures.py`), which lambdas never participate in.

Inlining is the right answer for the shape that actually dominates: a
lambda bound to a local and called *through that local, in the same
function*. There the body can be lowered at the call site, in the
enclosing scope, where every captured name already resolves — no function
pointer, no env struct, no capture plumbing at all.

The safety condition is the content of this module and it is CHECKED, not
assumed: the local must be assigned this lambda exactly once, never
rebound, and every other occurrence of its name in the enclosing body must
be the callee of a call. Anything else — passed as an argument, returned,
stored in a container, aliased — means the closure value outlives its call
site, and there is no call site to inline into.
"""

from __future__ import annotations

import mojo.middle.types as gimple_ctypes


def _param_names(node) -> list:
    """A LambdaExpr's declared parameter names, in order. `node.params`
    holds `(name, default_value)` pairs — the default is an expression or
    None, never a type annotation."""
    out = []
    for p in node.params or ():
        out.append(p[0] if isinstance(p, (tuple, list)) else p)
    return out


def _param_defaults(node) -> list:
    out = []
    for p in node.params or ():
        out.append(p[1] if isinstance(p, (tuple, list)) and len(p) > 1 else None)
    return out


def has_variadic_param(node) -> bool:
    """True if the lambda declares `*args` or `**kwargs`.

    Those need the extra positionals packed into a `MojoList *` and the
    keywords into a `MojoDict *` at every call site. The LIFTED path already
    does exactly that (see `_lower_LambdaExpr`'s `pname.startswith('**')`
    branches), so re-implementing the packing in the inliner would be a
    second, independently-maintained copy of one convention. Better to leave
    the variadic shape as it is today than to half-move it."""
    return any(str(p).startswith('*') for p in _param_names(node))


def _referenced_names(expr) -> set:
    """Every bare name READ anywhere in `expr`, descending into a nested
    lambda too: a lambda inside a lambda still closes over the OUTERMOST
    function's scope, so its free names are free here as well."""
    out = set()
    if expr is None or not hasattr(expr, '__dict__'):
        return out
    if isinstance(expr, gimple_ctypes.IdentExpr):
        out.add(expr.name)
    for _fname, fval in vars(expr).items():
        if _fname in ('line', 'col'):
            continue
        if isinstance(fval, list):
            for x in fval:
                out |= _referenced_names(x)
        elif isinstance(fval, tuple):
            for x in fval:
                out |= _referenced_names(x)
        elif hasattr(fval, '__dict__'):
            out |= _referenced_names(fval)
    return out


def free_names(node, enclosing: dict) -> list:
    """Sorted enclosing-scope names the lambda body reads.

    `enclosing` is the enclosing scope's `name -> ctype` map. A name the
    lambda does not itself declare, and that the enclosing scope actually
    holds a local for, is a capture."""
    declared = set(_param_names(node))
    for d in _param_defaults(node):
        if d is not None:
            declared |= _referenced_names(d)
    used = _referenced_names(node.body)
    return [n for n in sorted(used) if n not in declared and n in enclosing]


def _bind_site(stmt):
    """`(local_name, binder_node, value)` for a statement that binds a
    local, or None. `binder_node` is the node whose mere occurrence must
    NOT count as a use — the `VarDecl` itself, or the `IdentExpr` target
    of the assignment."""
    if isinstance(stmt, gimple_ctypes.VarDecl):
        return stmt.name, stmt, stmt.value
    if (isinstance(stmt, gimple_ctypes.AssignStmt)
            and isinstance(stmt.target, gimple_ctypes.IdentExpr)):
        return stmt.target.name, stmt.target, stmt.value
    return None


def candidate_lambdas(body: list, enclosing: dict) -> dict:
    """`{local_name: (lambda, binder_node)}` for every local in `body` bound
    to a CAPTURING, non-variadic lambda exactly once.

    A local bound twice, or rebound to anything, is dropped: the call site
    could not know which lambda it was inlining."""
    out = {}
    rebound = set()
    for stmt in _stmts(body):
        b = _bind_site(stmt)
        if b is None:
            continue
        name, binder, value = b
        if isinstance(value, gimple_ctypes.LambdaExpr):
            if name in out:
                rebound.add(name)
            out[name] = (value, binder)
        elif name in out:
            rebound.add(name)
    return {k: v for k, v in out.items()
            if k not in rebound
            and not has_variadic_param(v[0])
            and free_names(v[0], enclosing)}


def escapes(body: list, name: str, binder) -> bool:
    """True if `name` is used anywhere in `body` for anything other than
    being the callee of a call.

    The one supported use is `name(...)`. Anything else — stored, returned,
    passed as an argument, rebound — means the closure value outlives the
    call site, so inlining its body there would be wrong.

    `binder` is the node that merely BINDS the local; excluding it is
    essential, since without that every lambda trivially "escaped" through
    its own assignment and nothing would ever reduce."""
    # A name is a USE only when it is not a call's `func`. Deciding that
    # needs the parent, so collect the callee positions first: an earlier
    # version instead asked "is this CallExpr's func the lambda's name?",
    # which flagged the ENCLOSING call of `print(f())` — the `print(...)`
    # node's func is `print`, not `f`, so every legitimate direct call
    # looked like an escape and nothing reduced at all.
    callee_ids = set()
    for node in _walk_body(body):
        if (isinstance(node, gimple_ctypes.CallExpr)
                and isinstance(node.func, gimple_ctypes.IdentExpr)):
            callee_ids.add(id(node.func))
    for node in _walk_body(body):
        if not isinstance(node, gimple_ctypes.IdentExpr) or node.name != name:
            continue
        if node is binder:
            continue                          # the assignment that binds it
        if id(node) in callee_ids:
            continue                          # `name(...)` — the supported use
        return True                           # read, stored, passed, returned
    return False


def _stmts(body):
    """Top-level statements, not descending into nested FunctionDefs — a
    lambda inside a nested `def` belongs to that def's scope, not this
    one's. Returns a list, not a generator, for the reason `_walk` below
    documents."""
    if body is None:
        return []
    return [s for s in body
            if not isinstance(s, gimple_ctypes.FunctionDef)]


def _walk_body(body):
    """Every AST node under a STATEMENT LIST, as a LIST.

    `_walk` takes a single node and returns immediately for anything
    without a `__dict__` — which a list is — so passing a body to `_walk`
    directly returns NOTHING. That is not hypothetical: it silently
    disabled the escape check, which would have inlined
    genuinely-escaping lambdas."""
    out: list = []
    for stmt in (body or []):
        _walk_into(stmt, out)
    return out


def _walk(node):
    """Every AST node under `node`, not descending into a nested
    FunctionDef (its locals are a different scope), as a LIST.

    Deliberately NOT a generator, and the reason is the same one
    `mojo/middle/coro.py`'s identically-named `_walk` gives (see its
    docstring, and bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md):
    a `yield`/`yield from` function compiles to a real stack-switching
    coroutine in this codegen, and the A3 runtime cannot have a
    `mojo_raise()` longjmp across one. That is a liveness hazard, but the
    failure this ACTUALLY produced is more prosaic and much worse: this
    generator did not survive self-compilation at all, so the compiled
    `mojoc` emitted it as the `weak` "unavailable in compiled mode"
    stub — which returns nothing and prints a diagnostic per call. Every
    lambda-capture analysis in this module then silently examined ZERO
    nodes self-hosted, i.e. the whole `lambdareduce` pass was a no-op in
    the compiled compiler, and a `for node in _walk_body(body)` loop over
    a stub-returning call is what turned every `--dump-full` of the
    self-hosted compiler into a file of nothing but that diagnostic.

    None of this module's four `_walk_body` call sites needs laziness:
    two scan the whole body to build a set (`callee_ids`, `local_names`),
    one scans it fully, and `escapes_scope` returns early on the first
    escape but is bounded by one function body. The accumulator form is
    the same shape `exprtypes._walk_ast_into` already uses for exactly
    this reason, so this is a convergence on an existing pattern rather
    than a new one."""
    out: list = []
    _walk_into(node, out)
    return out


def _walk_into(node, out: list) -> None:
    """`_walk`'s body, appending into a caller-owned accumulator. Split out
    so the recursion is a plain self-call — a recursive `yield from`
    inside one function is precisely the shape that needed replacing."""
    if node is None or not hasattr(node, '__dict__'):
        return
    out.append(node)
    if isinstance(node, gimple_ctypes.FunctionDef):
        return
    for _fname, fval in vars(node).items():
        if _fname in ('line', 'col'):
            continue
        if isinstance(fval, (list, tuple)):
            for x in fval:
                _walk_into(x, out)
        elif hasattr(fval, '__dict__'):
            _walk_into(fval, out)


def local_names(body: list) -> set:
    """Every name the enclosing function binds locally: its parameters plus
    every assignment target / `var` declaration anywhere in the body.

    Needed because `gen.var_types` is populated INCREMENTALLY as statements
    are lowered, so at the time a call site is reached it holds only the
    locals declared ABOVE that point. A lambda capturing a local declared
    LATER in the function (`xs` bound after the lambda that closes over it,
    called after that) would look capture-free, and silently keep the broken
    lifted path. The ctype here is only a placeholder — the inlined body is
    lowered in the real scope, where the true type is known — so an unknown
    name defaulting to int64_t is harmless."""
    out = set()
    for node in _walk_body(body):
        if isinstance(node, gimple_ctypes.VarDecl) and node.name:
            out.add(node.name)
        elif (isinstance(node, gimple_ctypes.AssignStmt)
              and isinstance(node.target, gimple_ctypes.IdentExpr)):
            out.add(node.target.name)
    return out


def enclosing_scope(gen) -> dict:
    """`name -> ctype` for the enclosing function: the types known so far,
    unioned with the function's FULL local set (see `local_names`)."""
    scope = dict(getattr(gen, 'var_types', {}) or {})
    body = getattr(gen, '_cur_func_body', None)
    if body:
        for n in local_names(body):
            scope.setdefault(n, 'int64_t')
    return scope


def captures_anything(gen, node) -> bool:
    """True if this lambda reads any enclosing-scope local.

    Such a lambda is only representable when `reducible_lambdas` claims it
    (the body gets inlined into a scope where the name exists). Lifted, its
    body names a variable that is not in scope at all, and every read
    stubbed to 0 — a silent wrong answer. The caller uses this to refuse
    honestly instead."""
    return bool(free_names(node, enclosing_scope(gen)))


def bound_local_name(gen, node) -> str:
    """The name of the local this lambda is bound to in the enclosing
    function, or '?' if it cannot be determined.

    Needed only to make a refusal message actionable ("the lambda assigned
    to 'e' ..."), and it works for lambdas `candidate_lambdas` drops —
    a variadic or rebound one is exactly the case a refusal is about, so it
    is precisely the one that never got stamped by the reduction scan."""
    body = getattr(gen, '_cur_func_body', None)
    if not body:
        return '?'
    for stmt in _stmts(body):
        b = _bind_site(stmt)
        if b is not None and b[2] is node:
            return b[0]
    return getattr(node, '_bound_local', None) or '?'


def captures_only_locals(gen, node, enclosing: dict) -> bool:
    """True if every captured name is a LOCAL of the enclosing function —
    not one of its PARAMETERS.

    `captures_only_locals` asks whether the captured name's ctype can
    already known; this asks the separate question of whether that ctype can
    be TRUSTED. It cannot, for a parameter: the compiled path's parameter
    typing degrades under self-hosting, where the backend's own `gen`
    parameter — a `GimpleGen` struct pointer — arrives as a plain `int64_t`.
    A body inlined over that is typed against a type the variable does not
    have.

    Real repro: `mojo/backend_gimple/cpp_async.py`'s

        _sig_pn = lambda pn: gen._cpp_kw_param_renames.get(pn, pn)

    captures the `gen` parameter, so inlining it lowered
    `gen._cpp_kw_param_renames.get(...)` against an int64_t `gen` and
    produced `char *` values assigned into `int64_t` —
    `-Werror=int-conversion`, failing `make check-selfhost` outright.

    A local's ctype comes from its own annotation or initializer and is
    sound, so this costs nothing real: every shape this reduction was
    written for captures a `var`-bound local (`lambda: n`, `lambda:
    len(xs)`, `lambda x: n + x`).
    """
    params = getattr(gen, '_cur_func_params', None) or ()
    return not (set(free_names(node, enclosing)) & set(params))


def reducible_lambdas(gen) -> dict:
    """`{local_name: LambdaExpr}` for the enclosing function, computed once
    per function and cached on `gen`.

    A lambda qualifies only if it captures something, declares no
    `*args`/`**kwargs`, and its local never escapes — so a call site can
    inline the body in this scope with no env and no function pointer.

    Also stamps `_bound_local` on each qualifying node, which is how
    `_lower_LambdaExpr` recognises the same lambda at its assignment and
    skips lifting a body that is being inlined elsewhere."""
    # Cached by the IDENTITY OF THE BODY, not on a single `gen` slot. A
    # lifted closure calls `_reset_func` too, so a one-slot cache is
    # overwritten mid-function: a `var h = lambda...` / `h()` pair after
    # one saw the lifted closure's body instead of the enclosing one's, and
    # silently kept the broken lifted path. Keying on the body makes every
    # distinct body its own entry, so returning to the enclosing one is
    # always a hit on the right answer.
    body = getattr(gen, '_cur_func_body', None)
    cache = getattr(gen, '_reducible_lambdas_cache', None)
    if cache is None:
        cache = {}
        gen._reducible_lambdas_cache = cache
    if id(body) in cache:
        return cache[id(body)]
    enclosing = dict(getattr(gen, 'var_types', {}) or {})
    out = {}
    if body:
        # Union of the types known SO FAR and the function's FULL local set,
        # so a capture of a later-declared local is still recognised.
        for _n in local_names(body):
            enclosing.setdefault(_n, 'int64_t')
        for name, (lam, binder) in candidate_lambdas(body, enclosing).items():
            if escapes(body, name, binder):
                continue
            if not captures_only_locals(gen, lam, enclosing):
                continue
            try:
                lam._bound_local = name
            except AttributeError:
                pass
            out[name] = lam
    cache[id(body)] = out
    return out
