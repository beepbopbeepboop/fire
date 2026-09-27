"""Phases 1-2 of doc/OWNERSHIP_MODEL.md:
  Phase 1 -- flow-sensitive move tracking / use-after-move diagnostics.
  Phase 2 -- single-call borrow-exclusivity checking (the "shared xor
             mutable" rule, scoped to conflicts visible within one call's
             own argument list).

This is a pure static-analysis pass over the parsed AST (fire_compiler.py's
node types) — it never touches codegen or the interpreter, and produces
only Diagnostic objects for the caller to report or reject on. It does not
implement destruction (Phase 3) or cross-statement borrow lifetimes.

== Phase 1: move tracking ==

Per-local lattice, tracked ONLY for plain local-variable bindings (function
params and names assigned via `x = ...`/`for x in ...`/`with ... as x`) —
struct fields, subscripts, and anything not a bare IdentExpr binding are
deliberately NOT tracked (doc: "no first-class reference/lifetime values
... out of scope" for this phase):

    live         -- currently a valid, readable/movable binding
    moved        -- transferred away (via `x^`, the ONLY move trigger —
                    see note below) on every path reaching this point
    maybe_moved  -- moved on SOME but not all preceding branches

A name absent from the tracked state (an untracked binding, a captured
closure variable, anything this pass couldn't resolve) is never flagged —
the lattice only ever produces MORE diagnostics as tracking improves, never
false positives from things it doesn't understand. This is a deliberate
soundness-for-precision tradeoff appropriate for a diagnostic pass: it is
allowed to miss real bugs (silently, by not tracking a binding), but must
never reject correct code.

IMPORTANT correction (found via real-world stress testing against
Modular's actual stdlib, not a hypothetical): passing a bare identifier to
an `owned` parameter WITHOUT `^` is an implicit COPY in real Mojo (if the
type is Copyable), not a move — only an explicit `x^` on a named lvalue
ever ends that binding's lifetime, regardless of what kind of expression
context it appears in (call argument, assignment RHS, return value, ...).
An earlier version of this pass treated "argument statically resolved to
an `owned` parameter" as an implicit move even without `^`, which produced
real false positives against `std/os/path/path.mojo`, `std/runtime/
asyncrt.mojo`, and `std/iter/__init__.mojo` (all ordinary `f(x)` calls to
an `owned`-parameter function, correctly relying on the implicit-copy
semantics). Fixed by deleting that logic entirely — `^` is the sole move
trigger, uniformly, and is already handled once, generically, wherever it
appears (see the `UnaryOp` case below), so no call-site special-casing was
needed for Phase 1's own scope.

Known Phase-1 limitations (by design, not oversights — see
doc/OWNERSHIP_MODEL.md):
  - Closures (`LambdaExpr` bodies, nested `def`) are analyzed as their own
    independent scope with a fresh parameter-only state; a move that
    happens to a captured outer-scope binding INSIDE a closure body is not
    reflected back into the enclosing function's tracking. This is a real
    gap (flagged in doc/OWNERSHIP_MODEL.md's Phase 1 section as the hard
    case) — safe (no false positives) but incomplete.
  - Loops use a two-pass fixed point (analyze the body once to find its own
    exit state, merge that back with the entry state, then re-analyze the
    body against the merged entry so a use near the TOP of the loop body
    that only becomes invalid because of a move near the BOTTOM of the
    previous iteration is still caught) rather than iterating to a true
    fixed point. Two passes are enough for straight-line loop bodies; a
    loop whose OWN internal branching changes the merged state on a third
    pass is not handled (considered rare enough not to block Phase 1).

== Phase 2: single-call borrow exclusivity ==

Real Mojo's aliasing rule (doc/OWNERSHIP_MODEL.md rule 7): any number of
concurrent `read` borrows of a value are fine, but a `mut` borrow requires
exclusivity — no other borrow (read or mut) of the SAME value may be live
at the same time. This codebase has no first-class reference/lifetime
values that outlive a single call (no `ref`-typed locals kept alive across
statements), so the only conflict shape actually expressible here is
WITHIN one call's own argument list: the same binding passed through two
(or more) of that call's parameters, at least one of which is `mut` — e.g.
`def swap(mut a: Int, mut b: Int): ...` called as `swap(x, x)`.

Callee resolution for this check (`_resolve_callee`) is intentionally
narrow: only a bare-name call to a known module-level function, or
`self.method(...)` against the CURRENT struct's own method table. This is
the SAME resolver shape an earlier version of Phase 1 used incorrectly for
move-tracking (see the git history / the "IMPORTANT correction" above) —
reused here deliberately, because for BORROW conflicts (unlike moves)
"argument statically resolved to a `mut` parameter" is exactly the right
signal, no `^`/copy subtlety involved. An unresolved callee produces no
diagnostic (never a guess).

Validated (not just unit-tested) against real source: every fixture in
test_ownership_check.py, plus a zero-crash, zero-false-positive sweep of
every `.mojo` file under this machine's real Modular `stdlib` tree (664
files, `std/` + `test/` + everything else) as of 2026-09-15 — real
false-positive classes were found and fixed this way (unhandled
`ComptimeIfStmt` branching, an unhandled `WalrusExpr` rebind, the
owned-parameter-implies-move mistake described above, a try/except handler
seeing post-body instead of pre-try state, and `x.type`/`type_of(x)`
compile-time-type-only accesses being misread as runtime uses of a moved
value). Re-run that sweep after any change to this file.
"""

import dataclasses
import fire_compiler as N


@dataclasses.dataclass
class Diagnostic:
    message: str
    line: int
    col: int
    name: str

    def __str__(self):
        return f"{self.line}:{self.col}: {self.message}"


# Member names that real Mojo resolves from a binding's STATIC TYPE at
# compile time (`x.type`, `x.origins`) rather than reading its runtime
# value — see the MemberExpr case in _walk_expr for why this matters.
_COMPTIME_TYPE_MEMBERS = {'type', 'origins'}

# Builtins whose argument is consulted for its STATIC TYPE only, at compile
# time (`type_of(x)` — real Mojo's compile-time analogue of Python's
# `type(x)`) — same reasoning as _COMPTIME_TYPE_MEMBERS, just spelled as a
# call instead of a member access. Found for real against Modular's actual
# `test/memory/test_arc.mojo`: `_ = p^; ...; var vec =
# List[type_of(p)]()` — `type_of(p)` here needs only `p`'s type (already
# known from its declaration), not its now-moved-from runtime value.
_COMPTIME_TYPE_FUNCS = {'type_of', '__type_of'}


def _is_node(x):
    return dataclasses.is_dataclass(x) and not isinstance(x, type)


def _bind_target(target, state):
    """Mark every plain-identifier leaf of an assignment/loop/with target
    as freshly live — handles bare names and tuple-unpack targets
    (`a, b = ...`, `for k, v in ...`). Non-identifier targets (subscript/
    member) are not bindings at all; the caller is responsible for
    visiting them as a use of their object instead."""
    if isinstance(target, N.IdentExpr):
        state[target.name] = 'live'
    elif isinstance(target, N.TupleExpr):
        for e in target.elements:
            _bind_target(e, state)
    elif isinstance(target, (list, tuple)):
        for e in target:
            _bind_target(e, state)


def _check_use(node, state, diags):
    name = node.name
    st = state.get(name)
    if st == 'moved':
        diags.append(Diagnostic(
            name=name, line=node.line, col=node.col,
            message=f"use of moved value '{name}'"))
    elif st == 'maybe_moved':
        diags.append(Diagnostic(
            name=name, line=node.line, col=node.col,
            message=f"use of possibly-moved value '{name}' "
                    f"(moved on some but not all preceding branches)"))


def _resolve_callee(func, funcs, methods):
    """Phase 2 ONLY (see module docstring for why this resolver is fine to
    reuse for borrow-conflict checking even though an earlier, differently
    -scoped version of it was wrong for Phase 1 move-tracking). Resolves
    only the two callee shapes knowable without a real type system: a
    bare-name call to a known module-level function, or `self.method(...)`
    against the CURRENT struct's own method table."""
    if isinstance(func, N.IdentExpr):
        return funcs.get(func.name)
    if (isinstance(func, N.MemberExpr) and isinstance(func.obj, N.IdentExpr)
            and func.obj.name == 'self'):
        return methods.get(func.member)
    return None


def _check_call_aliasing(node, funcs, methods, diags):
    """Phase 2: flag a call whose OWN argument list aliases the same
    binding through more than one parameter when at least one of those
    parameters is `mut` — e.g. `def swap(mut a: Int, mut b: Int): ...`
    called as `swap(x, x)`. See module docstring's "Phase 2" section for
    the exact scope (single-call only) and why that's the right boundary
    for what this codebase can express today."""
    callee = _resolve_callee(node.func, funcs, methods)
    if callee is None:
        return
    param_names = [p[0] for p in callee.params]
    offset = 1 if isinstance(node.func, N.MemberExpr) else 0  # implicit self
    occurrences = {}  # name -> [(conv, node), ...]
    for i, a in enumerate(node.args):
        if not isinstance(a, N.IdentExpr):
            continue
        idx = i + offset
        conv = (callee.param_convs.get(param_names[idx], 'read')
                if 0 <= idx < len(param_names) else 'read')
        occurrences.setdefault(a.name, []).append((conv, a))
    for kw_name, v in (node.kwargs or []):
        if not isinstance(v, N.IdentExpr):
            continue
        conv = callee.param_convs.get(kw_name, 'read')
        occurrences.setdefault(v.name, []).append((conv, v))
    for name, occs in occurrences.items():
        if len(occs) < 2 or not any(c == 'mut' for c, _ in occs):
            continue
        kinds = sorted({c for c, _ in occs})
        _, second = occs[1]
        diags.append(Diagnostic(
            name=name, line=second.line, col=second.col,
            message=f"cannot borrow '{name}' as {'/'.join(kinds)} more than "
                    f"once in the same call (at least one borrow is 'mut' "
                    f"— exclusivity violation)"))


def _walk_expr(node, state, diags, funcs, methods):
    """Recurse over an expression, checking/updating move state (Phase 1)
    and borrow conflicts (Phase 2) as it goes. Falls back to generic
    dataclass-field recursion for any node shape not specially handled, so
    adding a new expression AST node never silently stops being visited —
    see module docstring for the "absent from state -> never flagged"
    safety property this relies on."""
    if node is None:
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk_expr(item, state, diags, funcs, methods)
        return
    if not _is_node(node):
        return

    if isinstance(node, N.IdentExpr):
        _check_use(node, state, diags)
        return

    if isinstance(node, N.WalrusExpr):
        # `name := value` BINDS `name` fresh — it is never a use of any
        # prior `name`, so must not fall through to the generic recursion
        # below (which would otherwise leave a stale moved/maybe_moved
        # state from a previous loop iteration in place, since nothing
        # else marks it live again). Found for real against Modular's
        # actual `std/tempfile/tempfile.mojo`'s
        # `for env_var in ...: if dirname := os.getenv(...): dirlist.append(dirname^)`
        # — each loop iteration's walrus re-binds `dirname`, but without
        # this case the checker treated it as still carrying whatever
        # state `dirname^` left behind at the end of the PREVIOUS
        # iteration, flagging a "possibly-moved" false positive.
        _walk_expr(node.value, state, diags, funcs, methods)
        state[node.name] = 'live'
        return

    if isinstance(node, N.UnaryOp) and node.op == '^':
        operand = node.operand
        if isinstance(operand, N.IdentExpr) and operand.name in state:
            _check_use(operand, state, diags)   # error if ALREADY moved
            state[operand.name] = 'moved'        # this IS the move site
        else:
            _walk_expr(operand, state, diags, funcs, methods)
        return

    if isinstance(node, N.FunctionDef):
        # Nested def / closure: checked as its own independent scope (own
        # diagnostics), but never reads or mutates the enclosing
        # function's state — see module docstring's "known limitations".
        _check_function(node, diags, funcs, methods)
        return

    if isinstance(node, N.LambdaExpr):
        return  # see module docstring: closures are out of scope for Phase 1

    if (isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr)
            and node.func.name in _COMPTIME_TYPE_FUNCS):
        for a in node.args:
            if not isinstance(a, N.IdentExpr):
                _walk_expr(a, state, diags, funcs, methods)
        for _kw, v in (node.kwargs or []):
            if not isinstance(v, N.IdentExpr):
                _walk_expr(v, state, diags, funcs, methods)
        return

    if isinstance(node, N.MemberExpr) and node.member in _COMPTIME_TYPE_MEMBERS:
        # `x.type` / `x.origins` etc. are resolved from x's STATIC TYPE at
        # compile time, not its runtime value — real Mojo lets you read
        # these even on an already-moved-from binding (its type doesn't
        # change just because the value did). Treating this as an
        # ordinary member-read (which recurses into `.obj` as a normal
        # use) produced a real false positive against Modular's actual
        # `std/runtime/asyncrt.mojo`: `task = Task(handle^); _async_execute
        # [handle.type](...)` — `handle.type` here is a comptime type
        # parameter, not a read of the moved coroutine value. This is a
        # name-based heuristic (the two attribute names seen causing false
        # positives in practice), not a real static-type analysis — a
        # later phase with real type info could resolve this exactly
        # instead of guessing by attribute name.
        return

    if isinstance(node, N.MemberExpr):
        _walk_expr(node.obj, state, diags, funcs, methods)
        return

    if isinstance(node, N.CallExpr):
        # Phase 2 check is a pure side effect (diagnostics only, no state
        # mutation) — falls through to the generic recursion below so
        # func/args/kwargs still get Phase 1's move-checking exactly as
        # before this case existed.
        _check_call_aliasing(node, funcs, methods, diags)

    # Generic fallback: recurse over every dataclass field. This is also
    # what handles CallExpr's own func/args/kwargs (no move-tracking
    # special-casing needed there — see the module docstring's "IMPORTANT
    # correction" for why that's deliberate, not an omission).
    for f in dataclasses.fields(node):
        _walk_expr(getattr(node, f.name), state, diags, funcs, methods)


def _merge_states(states):
    """Join point for branches: a name only stays tracked if EVERY branch
    still has it tracked (a name first bound inside only one branch isn't
    meaningfully live outside it for this pass' purposes); its merged
    state is 'live'/'moved' only if every branch agrees, else
    'maybe_moved'."""
    if not states:
        return {}
    common = set(states[0].keys())
    for s in states[1:]:
        common &= set(s.keys())
    merged = {}
    for k in common:
        vals = {s[k] for s in states}
        if vals == {'live'}:
            merged[k] = 'live'
        elif vals == {'moved'}:
            merged[k] = 'moved'
        else:
            merged[k] = 'maybe_moved'
    return merged


def _terminates(stmt):
    """True if `stmt` unconditionally hands control OUT of the current
    block (return/raise/break/continue, or an if/else where every arm
    does). A branch that terminates must be excluded from the post-if
    state merge — it never reaches the join point at all, so treating its
    moves as "maybe happened" there is a false positive, not a
    conservative approximation. This was found for real: without it,
    Modular's actual `std/collections/dict.mojo` (`__setitem__`-adjacent
    insert path, ~line 910) and `linked_list.mojo` (~line 687) — both
    ordinary `if found: ...; return X` / fallthrough patterns — were
    flagged as using a "possibly-moved" value that in fact only gets
    moved on the branch that always returns."""
    if isinstance(stmt, (N.ReturnStmt, N.RaiseStmt, N.BreakStmt, N.ContinueStmt)):
        return True
    if isinstance(stmt, (N.IfStmt, N.ComptimeIfStmt)):
        if stmt.else_body is None:
            return False
        blocks = [stmt.then_body] + [b for _, b in (stmt.elifs or [])] + [stmt.else_body]
        return all(_block_terminates(b) for b in blocks)
    if isinstance(stmt, N.WithStmt):
        return _block_terminates(stmt.body)
    if isinstance(stmt, N.TryStmt):
        blocks = [stmt.body] + [getattr(h, 'body', []) for h in (stmt.handlers or [])]
        if stmt.else_body:
            blocks.append(stmt.else_body)
        return bool(blocks) and all(_block_terminates(b) for b in blocks)
    return False


def _block_terminates(body):
    return bool(body) and _terminates(body[-1])


def _branch_states(then_body, elifs, else_body, state, diags, funcs, methods):
    """Shared then/elifs/else branching logic for IfStmt and
    ComptimeIfStmt: check each arm against its own copy of `state`
    (elif/else conditions are evaluated against the ORIGINAL pre-if
    state — an approximation, since a real elif chain only evaluates a
    later condition when earlier ones were false, but conditions are
    just being walked for use-checking here, not branched on, so this is
    a minor precision loss, not a soundness one) and return a
    (state_after_branch, terminates) pair per arm, including a synthetic
    non-terminating arm for a missing `else`."""
    branches = []
    then_state = dict(state)
    _check_block(then_body, then_state, diags, funcs, methods)
    branches.append((then_state, _block_terminates(then_body)))
    for cond, body in (elifs or []):
        _walk_expr(cond, state, diags, funcs, methods)
        es = dict(state)
        _check_block(body, es, diags, funcs, methods)
        branches.append((es, _block_terminates(body)))
    if else_body is not None:
        else_state = dict(state)
        _check_block(else_body, else_state, diags, funcs, methods)
        branches.append((else_state, _block_terminates(else_body)))
    else:
        branches.append((dict(state), False))
    return branches


def _check_block(body, state, diags, funcs, methods):
    for stmt in body:
        _check_stmt(stmt, state, diags, funcs, methods)


def _check_stmt(stmt, state, diags, funcs, methods):
    if isinstance(stmt, N.FunctionDef):
        _check_function(stmt, diags, funcs, methods)
        return

    if isinstance(stmt, N.ExprStmt):
        _walk_expr(stmt.value, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.AssignStmt):
        _walk_expr(stmt.value, state, diags, funcs, methods)
        tgt = stmt.target
        if isinstance(tgt, (N.IdentExpr, N.TupleExpr)):
            _bind_target(tgt, state)
        else:
            _walk_expr(tgt, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.AugAssignStmt):
        _walk_expr(stmt.target, state, diags, funcs, methods)
        _walk_expr(stmt.value, state, diags, funcs, methods)
        if isinstance(stmt.target, N.IdentExpr):
            state[stmt.target.name] = 'live'
        return

    if isinstance(stmt, N.VarDecl):
        if stmt.value is not None:
            _walk_expr(stmt.value, state, diags, funcs, methods)
        state[stmt.name] = 'live'
        return

    if isinstance(stmt, N.MultiAssignStmt):
        _walk_expr(stmt.value, state, diags, funcs, methods)
        for t in stmt.targets:
            _bind_target(t, state)
        return

    if isinstance(stmt, N.ReturnStmt):
        if stmt.value is not None:
            _walk_expr(stmt.value, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.RaiseStmt):
        if stmt.value is not None:
            _walk_expr(stmt.value, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.AssertStmt):
        if stmt.value is not None:
            _walk_expr(stmt.value, state, diags, funcs, methods)
        if stmt.msg is not None:
            _walk_expr(stmt.msg, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.DelStmt):
        for t in stmt.targets:
            if isinstance(t, N.IdentExpr) and t.name in state:
                state[t.name] = 'moved'
            else:
                _walk_expr(t, state, diags, funcs, methods)
        return

    if isinstance(stmt, (N.IfStmt, N.ComptimeIfStmt)):
        # ComptimeIfStmt (`comptime if`/`elif`/`else`) has the identical
        # then/elifs/else shape as a regular IfStmt and the identical
        # exactly-one-arm-actually-runs semantics for this analysis's
        # purposes (real Mojo picks exactly one arm at compile time; even
        # if it didn't, this pass only needs "not necessarily all of
        # them" to be sound) — same branch+merge logic applies unchanged.
        # Missing this case once sent ComptimeIfStmt through the generic
        # dataclass-field fallback, which walks all three arms
        # SEQUENTIALLY against one shared state instead of branching them
        # — found for real against Modular's actual `std/os/fstat.mojo`
        # (`comptime if CompilationTarget.is_macos(): return f(fspath^)
        # elif ...: return g(fspath^) else: return h(fspath^)`), which
        # flagged `fspath` as already-moved in the second/third arms
        # purely from this bug, not any real issue in that code.
        _walk_expr(stmt.condition, state, diags, funcs, methods)
        branches = _branch_states(stmt.then_body, stmt.elifs, stmt.else_body,
                                   state, diags, funcs, methods)
        live = [s for s, term in branches if not term]
        if live:
            merged = _merge_states(live)
            state.clear()
            state.update(merged)
        # else: every arm diverges, so control never reaches here — leave
        # `state` as-is (whatever follows is unreachable code; not our
        # problem to diagnose in Phase 1).
        return

    if isinstance(stmt, (N.WhileStmt, N.ForStmt, N.ComptimeForStmt)):
        if isinstance(stmt, N.WhileStmt):
            _walk_expr(stmt.condition, state, diags, funcs, methods)
        elif isinstance(stmt, N.ForStmt):
            _walk_expr(stmt.iterable, state, diags, funcs, methods)
            _bind_target(stmt.target, state)
        else:  # ComptimeForStmt: target is a plain str, not an expr node
            _walk_expr(stmt.iterable, state, diags, funcs, methods)
            if stmt.target:
                state[stmt.target] = 'live'
        # Pass 1: silent — just discover the body's own exit state.
        probe_state = dict(state)
        _check_block(stmt.body, probe_state, [], funcs, methods)
        entry = _merge_states([state, probe_state])
        # Pass 2: real diagnostics, entering with the merged (fixed-point)
        # state so a top-of-body use that's only invalid because of a
        # move near the bottom of the PREVIOUS iteration is still caught.
        body_state = dict(entry)
        _check_block(stmt.body, body_state, diags, funcs, methods)
        if getattr(stmt, 'else_body', None):
            _check_block(stmt.else_body, body_state, diags, funcs, methods)
        after = _merge_states([state, body_state])
        state.clear()
        state.update(after)
        return

    if isinstance(stmt, N.WithStmt):
        for item in stmt.items:
            _walk_expr(item.expr, state, diags, funcs, methods)
            if isinstance(item.alias, N.IdentExpr):
                _bind_target(item.alias, state)
            elif isinstance(item.alias, str):
                state[item.alias] = 'live'
        _check_block(stmt.body, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.TryStmt):
        # A handler can run after an exception struck at ANY point in the
        # try body — including before it reached whatever move happened
        # near the body's end — so handlers must see the state from
        # BEFORE the try started, not the try body's own exit state.
        # Found for real against Modular's actual `std/iter/__init__.mojo`
        # (`try: ...; return res^ except StopIteration:
        # ...forget_deinit(res^)`): using the post-body state made the
        # `except` block's own `res^` look like a double-move of
        # something the (never-reached, on the exception path) `return
        # res^` had already consumed.
        pre_state = dict(state)
        _check_block(stmt.body, state, diags, funcs, methods)
        for h in (stmt.handlers or []):
            _check_block(getattr(h, 'body', []), dict(pre_state), diags, funcs, methods)
        if stmt.else_body:
            _check_block(stmt.else_body, state, diags, funcs, methods)
        if stmt.finally_body:
            _check_block(stmt.finally_body, state, diags, funcs, methods)
        return

    if isinstance(stmt, N.MatchStmt):
        _walk_expr(stmt.subject, state, diags, funcs, methods)
        branches = []
        for case in (stmt.cases or []):
            body = getattr(case, 'body', [])
            cs = dict(state)
            _check_block(body, cs, diags, funcs, methods)
            branches.append((cs, _block_terminates(body)))
        # No wildcard `case _:` means match may fall through untouched —
        # always include the pre-match state as a possible (non-diverging)
        # outcome, same reasoning as IfStmt's implicit empty else.
        branches.append((dict(state), False))
        live = [s for s, term in branches if not term]
        if live:
            merged = _merge_states(live)
            state.clear()
            state.update(merged)
        return

    if isinstance(stmt, (N.PassStmt, N.BreakStmt, N.ContinueStmt,
                          N.GlobalStmt, N.NonlocalStmt, N.ImportStmt, N.FromImportStmt)):
        return

    # Generic fallback (comptime-only statement shapes etc.) — visit any
    # nested expression/statement fields, tracked-name-absence keeps this
    # from producing false positives per the module docstring.
    for f in dataclasses.fields(stmt):
        val = getattr(stmt, f.name)
        if isinstance(val, list):
            for item in val:
                if _is_node(item):
                    _walk_expr(item, state, diags, funcs, methods)
        elif _is_node(val):
            _walk_expr(val, state, diags, funcs, methods)


def _check_function(fn, diags, funcs, methods):
    state = {}
    for pname, _ptype in fn.params:
        pname = pname.lstrip('*')
        if pname:
            state[pname] = 'live'
    _check_block(fn.body, state, diags, funcs, methods)


def check_module(stmts):
    """Run Phase 1 move-tracking + Phase 2 single-call borrow-exclusivity
    checking over every function and struct method in a parsed module's
    top-level statement list. Returns a list of Diagnostic, in the order
    encountered (module-level functions first, then each struct's methods
    in declaration order)."""
    diags = []
    funcs = {}
    structs = []
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            funcs[s.name] = s
        elif isinstance(s, N.StructDef):
            structs.append(s)

    for s in stmts:
        if isinstance(s, N.FunctionDef):
            _check_function(s, diags, funcs, {})

    for st in structs:
        method_table = {m.name: m for m in st.methods}
        for m in st.methods:
            _check_function(m, diags, funcs, method_table)

    return diags


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print("usage: python3 ownership_check.py <file.mojo>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    src = open(path).read()
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename(path).parse_module()
    diags = check_module(stmts)
    for d in diags:
        print(f"{path}:{d}")
    if diags:
        sys.exit(1)
    print(f"{path}: no ownership diagnostics")
