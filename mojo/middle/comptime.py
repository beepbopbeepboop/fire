"""Compile-time constant evaluation — the `comptime` rules, once.

`comptime` is not a backend-specific feature: it is the language rule that a
`comptime` binding is a compile-time constant, that a `comptime if` over a
statically known condition is resolved *at compile time*, and that a read of
a `comptime` name yields that constant wherever it appears. Both compiled
backends therefore have to agree on it, so the evaluator lives here once
rather than once per backend:

  * the gimple/C path (`resolve_shared._eval_const`, `emit_infra
    ._eval_const_int` / `_eval_const_bool`) is a thin wrapper over these,
    passing its own `gen._comptime_vals` and — for the one backend-specific
    case, evaluating a *call* to an imported function at compile time — a
    `call_hook`;
  * the formal arm64 path (`formal/arm64_codegen.ARM64Codegen`) calls the
    same functions with its own binding table and no call hook (it has no
    imported-function elaborator to call).

NOT the root-level `comptime.py`, which is a different thing entirely: that
one *runs* a Mojo function at compile time as cached machine code (the
gimple path's `call_hook` below is what reaches for it). This module is the
backend-neutral folder for literals, operators and already-bound names.

The rule the two backends share, stated once:

  1. `comptime NAME = <const>` binds NAME to the folded value and emits NO
     runtime code.
  2. `comptime if C:` with C statically known emits only the taken branch.
     With C not statically known it degrades to a runtime branch — same
     observable behavior, no silent miscompile.
  3. Every *read* of a bound name — in any expression context, not just
     another comptime one — yields the constant.

(3) is not a detail: an earlier gimple version consulted the binding table
only from comptime contexts, so an ordinary read of a `comptime` name fell
through to the unknown-identifier placeholder and silently emitted `0`. Both
backends resolve the name in their generic identifier path for that reason.
"""


import sys

import fire_compiler as _fc

# The AST node classes are imported by name (the way every other module in
# mojo/middle/ does it) rather than off a namespace, so `isinstance` checks
# here are the same checks the backends make.
BoolLiteral = _fc.BoolLiteral
IntLiteral = _fc.IntLiteral
StringLiteral = _fc.StringLiteral
IdentExpr = _fc.IdentExpr
MemberExpr = _fc.MemberExpr
UnaryOp = _fc.UnaryOp
BinaryOp = _fc.BinaryOp
CompareChain = _fc.CompareChain
CallExpr = _fc.CallExpr


def compare_op(op: str, left, right):
    """Fold one comparison-chain link, or None if `op` is not a known comparison.

    Exactly the operator set mojo/backend_gimple/emit_resolve
    ._eval_const_compare_op folds, and deliberately no wider: adding an
    operator here would silently start folding chains the gimple path
    previously reported as unresolvable. A plain if/elif chain, not a dict
    of lambdas — self-hosting gimple_codegen.py couldn't link a
    dict-of-lambdas at self-host link time (undefined
    `_GimpleGen__eval_const_lambda_N` symbols; this codegen's own
    closure-lowering doesn't support several small same-scope lambdas bound
    into one dict literal). Returns None for an unrecognized op, distinct
    from a real False."""
    if op == '==':  return left == right
    if op == '!=':  return left != right
    if op == '<':   return left < right
    if op == '<=':  return left <= right
    if op == '>':   return left > right
    if op == '>=':  return left >= right
    return None


def fold_arith(op: str, left: int, right: int):
    """Fold one arithmetic/logical operator on two NUMBERS, or None.

    A function of its own, with ANNOTATED parameters, for the same reason
    `compare_op` is one: `eval_const` may hand back a `char *`, and a
    statically compiled backend will not narrow a local that holds one, so
    `l - r` in the caller emits pointer arithmetic and `l // r` emits a call
    with two pointer arguments. Call-site narrowing does not fix it — these
    backends type a parameter once for the whole function, and an unannotated
    one comes out as a pointer (`compare_op` survives that only because every
    operator it uses is also valid on pointers). The annotations say what the
    caller has already established. Only called once both operands are
    narrowed to numbers, so the folding matches Python's exactly, bools
    included (`True + True` is 2 either way)."""
    if op == '+':   return left + right
    if op == '-':   return left - right
    if op == '*':   return left * right
    if op == '/':   return left // right
    if op == 'and': return left and right
    if op == 'or':  return left or right
    return None


def eval_const(node, bindings: dict, platform: str = None):
    """Evaluate `node` as any compile-time constant (int, bool, or str) — or
    None if it isn't foldable.

    `bindings` is the backend's `comptime NAME = value` table (the gimple
    path's `gen._comptime_vals`, the arm64 path's own). A superset of
    eval_const_int/eval_const_bool, used where the constant's own type
    matters and not just its truthiness — e.g. a comptime `if` testing a
    comptime string alias.

    `platform` is the value `sys.platform` folds to. A backend passes the
    platform it is actually resolving for (also the hook a cross-compiler would
    need) and the gimple path keeps its existing
    `gimple_ctypes.sys.platform` resolution exactly. When nobody passes one,
    the host's own value is used.

    That fallback is a PLAIN `import sys`, and the "plain" is load-bearing:
    it was once `import sys as _sys`, and the self-hosted binary raised
    `AttributeError: platform` on it. An aliased import does not bind the way
    an unaliased one does once this file is compiled by mojoc rather than run
    by CPython, so `_sys` was not the sys module. It only surfaced after
    another process had populated the module cache, because that is the one
    route into eval_const that arrives with no platform attached.
    """
    if platform is None:
        try:
            platform = sys.platform
        except AttributeError:
            platform = None
    if isinstance(node, BoolLiteral): return node.value
    if isinstance(node, IntLiteral):  return node.value
    if isinstance(node, StringLiteral): return node.value
    if isinstance(node, IdentExpr):
        return bindings.get(node.name)
    if isinstance(node, UnaryOp) and node.op == '-':
        v = eval_const(node.operand, bindings, platform)
        return -v if isinstance(v, (int, bool)) and not isinstance(v, str) else None
    if isinstance(node, UnaryOp) and node.op == 'not':
        v = eval_const(node.operand, bindings, platform)
        return not v if isinstance(v, (bool, int)) else None
    if isinstance(node, BinaryOp):
        l = eval_const(node.left, bindings, platform)
        r = eval_const(node.right, bindings, platform)
        if l is None or r is None: return None
        op = node.op
        # `eval_const` yields an int or a str depending on the expression, and
        # a statically compiled backend types a local from its uses: one
        # variable that is sometimes a `char *` turns `l - r` into pointer
        # arithmetic and `l // r` into a call with two pointer arguments, which
        # is what stopped this file from compiling in the self-host build. The
        # narrowing has to be the SAME shape as the unary cases above, and
        # `not isinstance(..., str)` is load-bearing rather than redundant:
        # `isinstance(x, (int, bool))` alone does not exclude `char *` for
        # these backends, so without it the operands stay pointers and the
        # errors simply move down a few lines instead of going away.
        if (isinstance(l, (int, bool)) and not isinstance(l, str)
                and isinstance(r, (int, bool)) and not isinstance(r, str)):
            folded = fold_arith(op, l, r)
            if folded is not None:
                return folded
        # Comparisons fold for text as well as numbers, through the same helper
        # the CompareChain branch uses. Arithmetic on text deliberately does
        # NOT fold: `'a' + 'b'` is a pointer add in every statically compiled
        # backend here, and a compile-time folder is free to decline.
        return compare_op(op, l, r)

    if isinstance(node, CompareChain):
        left = eval_const(node.operands[0], bindings, platform)
        if left is None: return None
        for op, operand in zip(node.ops, node.operands[1:]):
            right = eval_const(operand, bindings, platform)
            if right is None: return None
            link = compare_op(op, left, right)
            if link is None: return None
            if not link: return False
            left = right
        return True
    # `sys.platform` is a genuinely compile-time-constant value for THIS host
    # (matching CPython's own sys.platform, which is the platform the
    # `if sys.platform == 'X': def f(): ...` conditional-toplevel-def idiom is
    # really being resolved for).
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name == 'sys' and node.member == 'platform'):
        return platform
    return None


def eval_const_int(node, bindings: dict, call_hook=None):
    """Evaluate `node` as a compile-time int, or None.

    `call_hook(name, args) -> int | None` is the one backend-specific case —
    folding a *call* by running it at compile time. The gimple path passes a
    hook backed by elaborate.py + comptime.py (compiled-and-run the imported
    function); a backend with no such machinery (the arm64 path) omits it and
    simply does not fold calls."""
    if isinstance(node, IntLiteral):  return node.value
    if isinstance(node, BoolLiteral): return int(node.value)
    if isinstance(node, UnaryOp) and node.op == '-':
        v = eval_const_int(node.operand, bindings, call_hook)
        return -v if v is not None else None
    if isinstance(node, BinaryOp):
        l = eval_const_int(node.left, bindings, call_hook)
        r = eval_const_int(node.right, bindings, call_hook)
        if l is None or r is None: return None
        ops = {'+': l+r, '-': l-r, '*': l*r, '//': l//r if r else None,
               '%': l%r if r else None, '**': l**r,
               '==': int(l == r), '!=': int(l != r), '<': int(l < r),
               '<=': int(l <= r), '>': int(l > r), '>=': int(l >= r)}
        return ops.get(node.op)
    if isinstance(node, CompareChain):
        # Same short-circuit chained-comparison semantics as
        # myinterpreter.py's eval_CompareChain / _lower_compare_chain, just
        # over compile-time constants instead of runtime values.
        left = eval_const_int(node.operands[0], bindings, call_hook)
        if left is None: return None
        for op, operand in zip(node.ops, node.operands[1:]):
            right = eval_const_int(operand, bindings, call_hook)
            if right is None: return None
            link = compare_op(op, left, right)
            if link is None: return None
            if not link: return 0
            left = right
        return 1
    if call_hook is not None and isinstance(node, CallExpr) and isinstance(
            node.func, IdentExpr):
        argvals = [eval_const_int(a, bindings, call_hook) for a in node.args]
        if argvals and all(v is not None for v in argvals):
            return call_hook(node.func.name, argvals)
    return None


def eval_const_bool(node, bindings: dict, call_hook=None, platform: str = None):
    """Evaluate `node` as a compile-time bool, or None."""
    v = eval_const(node, bindings, platform)
    if isinstance(v, (bool, int)):
        return bool(v)
    # Fallback: eval_const_int also folds what eval_const does not (calls,
    # via the hook).
    result = eval_const_int(node, bindings, call_hook)
    return bool(result) if isinstance(result, (bool, int)) else None


# ── The STATEMENT-level comptime rules ────────────────────────────────────
#
# Everything below is a language decision, not a code-generation decision:
# given a `comptime` statement and the bindings in scope, what does the
# program MEAN? A backend's only remaining job is to emit code for the answer
# (materialize a constant, skip straight to one branch, unroll N copies of a
# body) and to supply a runtime fallback when the answer is "not statically
# known". That split is what lets the arm64 and x86-64 backends share one
# implementation of `comptime` instead of each growing its own.


def param_names(fn) -> list:
    """The `def f[a, b](...)` comptime parameter names, in declaration order.

    On every compiled path these are ordinary LEADING arguments: the call
    site evaluates the bracket expressions and passes them first, so the body
    reads them through the normal parameter machinery. (The interpreter
    instead binds them as names in scope — `_MojoBoundComptimeFunction` — but
    both give the body the same values for the same call.)"""
    return [p for p in (getattr(fn, 'comptime_params', None) or [])
            if isinstance(p, str) and p.isidentifier()]


def specialization_name(func):
    """`f[a, b](...)` → 'f': the bare name of the generic being specialized.

    The bracket expressions are NOT resolved here — their values only exist in
    the caller's scope, so the call site evaluates them."""
    if not isinstance(func, _fc.SubscriptExpr):
        return None
    base = func.obj
    if isinstance(base, _fc.IdentExpr):
        return base.name
    return None


def keyword_bracket_args(attrs, ct_params: list) -> dict:
    """The `f[a, b=…]` bracket's keyword half, as {ct-param name: expr}.

    `SubscriptExpr` keeps the two halves of a bracket apart: POSITIONAL items in
    `index`, KEYWORD items in `attrs` as `(name, expr)` pairs (fire_compiler,
    `_parse_postfix`'s "keyword-style bracket" arm). A keyword half is only
    honoured for a name `ct_params` actually declares, for the reason
    `specialization_args` gives for over-supplied brackets: the declaration is
    a LOSSY record, so an unrecognised name is far more often a parser gap (an
    MLIR op attribute, a `//`-separated runtime type parameter) than a mistake
    in the source. `name is None` is the parser's own record of an item it
    could not name, and is skipped for the same reason."""
    if not attrs:
        return {}
    declared = {p for p in ct_params if isinstance(p, str)}
    out = {}
    for pair in attrs:
        name, expr = pair
        if isinstance(name, str) and name in declared:
            out[name] = expr
    return out


def specialization_args(call, ct_params: list) -> list:
    """The argument expressions binding `ct_params` at this call site.

    `f[a, b](x)` supplies them in bracket order, bound BY POSITION — the same
    rule the interpreter applies (`_parse_generic_params_capture`'s docstring:
    "enough for the interpreter to bind a call-site subscript (`f[Int32]()`) to
    names by position").

    `f[a, b=…](x)` names the keyword half BY NAME (`keyword_bracket_args`), and
    the positional items fill the parameters the keyword half did not claim, in
    declaration order. That is the shape the stdlib writes a defaulted comptime
    parameter in (`def _write_to[*, is_repr: Bool](…)`, called
    `_write_to[is_repr=True](w)`), and reading only `index` for it bound the
    named parameter to 0 — the same word an unsupplied one gets, so the
    parameter was invisible rather than missing and the program computed a
    number the source never wrote.

    Anything the bracket does not supply binds to 0: these paths have no type
    inference to deduce a comptime parameter from the runtime arguments, and 0
    is the "unknown compile-time value" every other unresolved compile-time
    name already gets.

    Bindings BEYOND the declared list are ignored rather than rejected, and
    that is not leniency: `comptime_params` is a LOSSY record — the parser
    skips `//`-separated runtime type parameters, defaults, and any bracketed
    shape it does not recognize (fire_compiler._parse_generic_params_capture).
    So "more supplied than declared" is far more often a gap in that record
    than a mistake in the source, and rejecting it turns a parser limitation
    into a hard compile error on correct code."""
    if not isinstance(call.func, _fc.SubscriptExpr):
        return [_fc.IntLiteral(value=0) for _ in ct_params]
    idx = call.func.index
    supplied = list(idx.elements) if isinstance(idx, (_fc.TupleExpr,
                                                      _fc.ListExpr)) else [idx]
    by_name = keyword_bracket_args(getattr(call.func, 'attrs', None), ct_params)
    if by_name:
        # The keyword items are NOT in `index` (that is the whole of the
        # parser's split), so nothing has to be taken out of `supplied`; the
        # parameters a keyword claimed are simply not filled positionally.
        unbound = list(supplied)
        bound = []
        for name in ct_params:
            if isinstance(name, str) and name in by_name:
                bound.append(by_name[name])
            elif unbound:
                bound.append(unbound.pop(0))
            else:
                bound.append(_fc.IntLiteral(value=0))
        return bound
    if len(supplied) < len(ct_params):
        supplied = supplied + [_fc.IntLiteral(value=0)
                               for _ in range(len(ct_params) - len(supplied))]
    return supplied[:len(ct_params)]


def eval_const_call(node, bindings: dict, call_hook=None,
                    platform: str = None):
    """Fold a bare call by RUNNING it through `call_hook`, or None.

    This is the seam a backend plugs its compile-time evaluator into: the
    gimple path's hook compiles the callee and executes it as machine code
    (comptime.py), the formal arm64 path's compiles it with the arm64 backend
    (formal/comptime_runner.py). Both run the callee rather than interpreting
    it, so a folded constant and the code emitted for the same expression come
    from one implementation."""
    if call_hook is None:
        return None
    if not isinstance(node, _fc.CallExpr) or not isinstance(node.func,
                                                             _fc.IdentExpr):
        return None
    if node.kwargs:
        return None              # no keyword calling convention at comptime
    args = []
    for a in node.args:
        # Try `eval_const` first, not just eval_const_int: a comptime call's
        # argument is very often another comptime binding, and eval_const is
        # what resolves a name against the binding table. eval_const_int alone
        # has no IdentExpr case — that is the gimple path's behaviour, kept
        # exactly as it is — so it cannot see `comptime a = square(6)` being
        # passed straight into `comptime b = add(a, 1)`.
        v = eval_const(a, bindings, platform)
        if not isinstance(v, (int, bool)) or isinstance(v, str):
            v = eval_const_int(a, bindings, call_hook)
        if v is None:
            return None          # one unfolded argument ⇒ no constant
        args.append(int(v))
    return call_hook(node.func.name, args)


def resolve_var(stmt, bindings: dict, call_hook=None,
                platform: str = None):
    """What a `comptime NAME = value` statement binds, or None if it cannot.

    Returns ('value', v) for a scalar that folded, or ('list', ast) for a
    list/tuple binding — which has no single scalar to fold to but is still
    compile-time state, and is kept as its AST so `comptime for x in NAME` can
    unroll over it. None means "not a compile-time constant", which a backend
    must report rather than quietly turn into a runtime variable: that would
    give the program different behaviour than the source declares."""
    val = eval_const(stmt.value, bindings, platform)
    if val is None:
        # A call is the one shape `eval_const` cannot fold on its own; the
        # backend's hook runs it (see formal/comptime_runner.py).
        val = eval_const_call(stmt.value, bindings, call_hook, platform)
    if val is not None:
        return ('value', val)
    if isinstance(stmt.value, (_fc.ListExpr, _fc.TupleExpr)):
        return ('list', stmt.value)
    return None


def resolve_if(stmt, bindings: dict, platform: str = None,
               call_hook=None):
    """Which `comptime if` branch is taken, or None if it is not knowable.

    'then' / ('elif', i) / 'else' mean "emit only that branch"; None means the
    condition is not statically known and the backend must emit a runtime
    branch — same observable behaviour, no silent miscompile."""
    val = eval_const_bool(stmt.condition, bindings, call_hook,
                         platform=platform)
    if val is True:
        return 'then'
    if val is False:
        for i, (cond, _body) in enumerate(getattr(stmt, 'elifs', None) or []):
            if eval_const_bool(cond, bindings, call_hook,
                               platform=platform) is True:
                return ('elif', i)
        return 'else'
    return None


def resolve_for_iterable(iterable, bindings: dict, list_asts: dict,
                         unroll_cap: int, call_hook=None):
    """The element expressions a `comptime for` iterates, or None.

    Two forms fold: `range(...)`, expanded with the same bounds as the
    equivalent runtime loop (1/2/3 args, direction from the step's sign), and a
    name bound to a list/tuple comptime value. `range` synthesizes int
    literals; a list yields its own element expressions, so each iteration
    sees the literal it was written with. None means "not statically known" →
    the backend emits the ordinary runtime loop.

    `list_asts` is the backend's table of list-valued bindings (name → the
    ListExpr/TupleExpr AST), kept separate from `bindings` because that one
    must stay scalar-valued: `eval_const` reads it directly and is shared
    verbatim with the gimple path.

    `unroll_cap` bounds the expansion: a `comptime for i in range(0, 10**9)`
    must not become a billion instructions, and above the cap the runtime loop
    is exactly right anyway."""
    if isinstance(iterable, _fc.IdentExpr):
        bound = list_asts.get(iterable.name)
        if bound is not None:
            return list(bound.elements)
    if isinstance(iterable, _fc.CallExpr) and isinstance(iterable.func,
                                                          _fc.IdentExpr) \
            and iterable.func.name == 'range':
        rargs = list(iterable.args)
    else:
        return None
    if not (1 <= len(rargs) <= 3):
        return None
    vals = []
    for a in rargs:
        v = eval_const_int(a, bindings, call_hook)
        if v is None:
            return None
        vals.append(v)
    if len(vals) == 1:
        start, stop, step = 0, vals[0], 1
    elif len(vals) == 2:
        start, stop, step = vals[0], vals[1], 1
    else:
        start, stop, step = vals
    if step == 0:
        return None              # a zero step is a runtime error, not a loop
    out = []
    v = start
    while (v < stop if step > 0 else v > stop):
        if len(out) >= unroll_cap:
            return None
        out.append(_fc.IntLiteral(value=v))
        v += step
    return out

