"""Phase 3 GROUNDWORK ONLY (doc/OWNERSHIP_MODEL.md) — identifies, per
function, which local container bindings are PROVABLY that function's
sole, permanent owner for their entire lifetime: candidates for a future
`mojo_*_free` call at every point the binding is still live at function
exit.

This module does NOT touch codegen, and nothing calls it from `fire.py`'s
build pipeline. It is a pure analysis/reporting layer, deliberately kept
separate from actually emitting any free — see doc/OWNERSHIP_MODEL.md's
"Codegen integration in general" cross-cutting section for why that's a
distinct, later step, and its "Effort and risk, honestly" section for why
Phase 3 is where a WRONG answer stops being a cosmetic bug (a missed free
is just today's existing leak, unchanged) and starts being memory
corruption (a wrong free is a double-free/use-after-free). Every rule
below exists to rule out a SPECIFIC corruption shape, not to maximize how
much it finds — this is deliberately a low-recall, zero-(intended)-false-
positive analysis, same discipline as ownership_check.py's Phases 1-2.

A local `x` is a DESTROY CANDIDATE only if ALL of the following hold,
checked over the whole function body (not flow-sensitively — see "Known
simplifications" below):

  1. Every assignment to `x` (there must be at least one) has a container-
     constructor RHS (`{}`, `[]`, `{1, 2}`, or a bare `dict()`/`list()`/
     `set()` call) — never a bare-name RHS (`x = y`), which would make `x`
     an ALIAS of whatever `y` already owns, not a fresh allocation. This
     is the single most important rule: aliasing is exactly how the
     existing `mojo_dict_clear` double-free war story
     (`runtime/fire_runtime.c:2441-2449`, cited in doc/OWNERSHIP_MODEL.md)
     happened, and this analysis must not reproduce that class of bug.
  2. `x` is assigned EXACTLY ONCE, statically, in the whole function.
     (Multiple constructor-assignments to the same name, e.g. inside a
     loop or across branches, would need real per-assignment lifetime
     tracking to free correctly between them — not attempted here.)
  3. `x` is never returned (a returned value's ownership transfers to the
     caller — freeing it here would hand back a dangling pointer).
  4. `x` is never `^`-transferred (an actual move — same reasoning as 3).
  5. `x` is never assigned to anything else (`y = x`, `self.field = x`,
     appended into another container, etc.) — any of these could make
     another binding believe it shares ownership.
  6. `x` never appears as a call ARGUMENT (positional or keyword) unless
     the call is PROVABLY non-retaining:
       - a small whitelisted builtin known not to store its argument
         beyond the call (`len`, `print`, `str`, `repr`, `bool`, `hash`,
         `id` — read the value, never keep it), or
       - a call this module can resolve (same narrow resolver as Phase 2:
         a bare-name free function, or `self.method(...)`) whose matching
         parameter's convention is canonically `read` — a `read`
         parameter is BY DEFINITION a borrow the callee cannot store past
         the call's own lifetime, which is exactly the guarantee needed
         here. An unresolved call, or a resolved one where the matching
         parameter is `mut`/`owned`/unannotated, downgrades `x` — being
         used only via ITS OWN methods (`x.append(...)`, `x["k"] = v`) is
         fine and does NOT count as a call-argument use, since `x` there
         is the method's receiver (`.obj`), not one of `args`/`kwargs`.
  7. `x` never appears inside a nested `def`/`LambdaExpr` in the same
     function (a possible closure capture) — conservative exclusion,
     since this module (like ownership_check.py's Phase 1) does not
     analyze closures.
  8. `x` is never the target of `del`.

Known simplifications (by design, matching ownership_check.py's own
documented tradeoffs):
  - Not flow-sensitive: rule 1/2 requires a single static assignment
    covering the WHOLE function, so a loop-body-scoped container (like
    the `leak_check.mojo` repro in `bugs/CODEGEN_container_no_
    deallocation_unbounded_growth.md`, which assigns fresh inside a
    `for` loop) is intentionally NOT a candidate under this v0 — real
    per-iteration freeing needs the loop-scoped, flow-sensitive treatment
    doc/OWNERSHIP_MODEL.md's Phase 3 section describes, not this
    simplified whole-function static check. This module is groundwork,
    not the finished Phase 3.
  - Ignores Phase 1's flow-sensitive move state entirely for simplicity:
    if `x` is EVER `^`-transferred anywhere in the function (rule 4), it
    is excluded as a candidate outright, even on paths where the transfer
    doesn't happen. A full implementation would reuse Phase 1's per-path
    "moved"/"maybe_moved" state to free `x` only on the paths where it
    wasn't moved.
  - NOT a definite-assignment analysis: "assigned exactly once, statically"
    counts a SINGLE `AssignStmt` node textually, which by itself says
    nothing about whether every path to a free point actually executed
    it (e.g. `if cond: x = {}` with nothing in the `else`, then `x` used
    after the `if`, on the path where `cond` was false). Freeing an
    uninitialized/never-constructed binding would read garbage as a
    pointer and corrupt memory, not just leak — so rules 1-8's escape
    analysis is composed with a SEPARATE definite-assignment pass
    (`_definitely_assigned`, run at the end of `analyze_function`) that
    intersects "assigned on this path" across every branch/loop/try arm
    and only keeps a candidate that's assigned on EVERY path reaching
    EVERY point the function can exit. `raise` is deliberately NOT treated
    as a function-exit point for this purpose — the exception-unwinding
    gap (a `longjmp` skips any inserted free entirely) is a separate,
    still-unresolved problem covered in the cross-cutting section below,
    not something this module can paper over.
"""

import dataclasses
import fire_compiler as N
from ownership_check import _terminates, _block_terminates


_NONRETAINING_BUILTINS = {'len', 'print', 'str', 'repr', 'bool', 'hash', 'id'}


def _as_str(x: str) -> str:
    """Identity, but with an explicitly `str`-annotated PARAMETER and
    return type — force a call site to coerce a dynamically-typed value
    (e.g. `stmt.target.name`, a `.name` field read off an untyped `stmt`
    parameter via runtime dynamic dispatch) to a real `char *` BEFORE it
    reaches a call that can't do that coercion itself.

    LOAD-BEARING, not a style nicety: a *builtin* method call like `set.
    add(x)`/`dict.get(x)` decides str-vs-int purely from `x`'s own
    inferred STATIC type at that exact call site (gimple_gen_methods.py),
    with no parameter annotation of its own to force a coercion — unlike
    a call into one of THIS module's own functions/methods, which DOES
    coerce its argument because ITS parameter is explicitly annotated
    (confirmed via a real, minimal test: `facts.note(stmt.name)` with
    `note(self, key: str)` correctly emits `mojo_set_add_str`, but
    `assigned.add(stmt.target.name)` — no intervening annotated
    parameter — emits `mojo_set_add_int`, silently storing a real string
    under the WRONG runtime hash scheme). Route any dynamically-typed
    field through `_as_str(...)` before handing it to a builtin
    container method, and the call boundary this function's OWN
    annotated parameter/return provides supplies the coercion the
    builtin method can't."""
    return x


def _set_view(x: set) -> set:
    """Set-typed twin of `_as_str`: identity in CPython, but an explicitly
    `set`-annotated parameter/return so a value read out of an untyped
    `list` (whose elements the self-hosted backend otherwise erases to
    `int64_t`) is recovered as a real `MojoSet *` BEFORE an operator
    inspects it. `_intersect_all` needs exactly this: `sets[0] & sets[i]`
    on `int64_t` elements emits a BITWISE AND of the two pointers
    (`_t9 & _t11` in the generated C — every set here is a heap pointer, so
    that is silent garbage, not a flagged type error), which then reached
    `mojo_set_update` as a bogus `MojoSet *` and heap-overflowed. Routing
    each element through `_set_view` makes `&` lower to
    `mojo_set_intersection` as intended."""
    return x


def _is_node(x):
    return dataclasses.is_dataclass(x) and not isinstance(x, type)


def _is_constructor_expr(node):
    if isinstance(node, (N.DictExpr, N.ListExpr, N.SetExpr)):
        return True
    if (isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr)
            and node.func.name in ('dict', 'list', 'set')):
        return True
    return False


class _FuncFacts:
    """Accumulated, whole-function facts about every plain-identifier local
    — see module docstring for exactly what each disqualifies."""

    def __init__(self):
        self.assign_count = {}       # name -> int
        self.all_ctor_assigns = {}   # name -> bool (True until proven False)
        self.disqualified = set()    # names ruled out by rules 3-8

    def note_assign(self, name: str, is_ctor: bool):
        self.assign_count[name] = self.assign_count.get(name, 0) + 1
        prev = self.all_ctor_assigns.get(name, True)
        self.all_ctor_assigns[name] = prev and is_ctor

    def disqualify(self, name: str):
        self.disqualified.add(name)

    def candidates(self) -> set:
        out = set()
        # Iterate KEYS ONLY (`for name in self.assign_count:`), never
        # `for name, count in self.assign_count.items():` — even with
        # `.items()`'s result stored in a named local first (`_items`,
        # the fix this comment used to describe), self-hosted codegen's
        # tuple-unpacking of a dict-`.items()`-derived pair silently
        # produced a `name` that DID look up correctly by hand via lldb
        # (`self.all_ctor_assigns.get("items")` external to the loop
        # answered True, `"items" not in self.disqualified` answered
        # True) but FAILED every single one of these same checks INSIDE
        # the loop body, leaving `out` permanently empty — confirmed via
        # gdbtool on `list_ops`/`t_list.mojo`-shaped input (`var items =
        # [...]`, never reassigned) 2026-09-20, the NINTH bug in this
        # chain and the reason `make bootstrap`'s per-file A/B sweep
        # (`_ab.py`) still showed 6/27 built-in tests diverging even
        # after the whole-program crash (bugs 1-8) was fully fixed.
        # Looking each value up separately by the (correctly-typed,
        # dict-key-derived) `name` sidesteps whatever `.items()`-pair
        # unpacking loses.
        for name in self.assign_count:
            count = self.assign_count.get(name)
            if (count == 1 and self.all_ctor_assigns.get(name)
                    and name not in self.disqualified):
                out.add(name)
        return out


def _resolve_callee(func, funcs, methods):
    """Same narrow resolver as ownership_check.py's Phase 2 (bare-name
    free function, or `self.method(...)` against the current struct) —
    duplicated rather than imported to keep this groundwork module
    independently readable and because the two modules may diverge once
    Phase 3 proper starts (this one may need finer-grained per-call-site
    info Phase 2 never needed)."""
    if isinstance(func, N.IdentExpr):
        return funcs.get(func.name)
    if (isinstance(func, N.MemberExpr) and isinstance(func.obj, N.IdentExpr)
            and func.obj.name == 'self'):
        return methods.get(func.member)
    return None


def _scan_expr(node, facts: _FuncFacts, funcs, methods, in_closure=False):
    """Visits every expression node reachable from `node`. THE CORE
    SOUNDNESS RULE (fixed 2026-09-15 after a real, reproducible self-host
    crash — see the "IMPORTANT correctness fix" note in the module
    docstring's history for the full story): a bare `IdentExpr` reached
    through GENERIC recursion always disqualifies that name. Escaping
    that default requires one of the specific, deliberately-reasoned-
    through safe patterns below to consume the identifier WITHOUT ever
    handing it to the generic recursion at all — each one is a distinct
    `isinstance` branch here, not a flag threaded through. There is no
    other mechanism that keeps a name a candidate; if a future change
    needs a new safe pattern, it must be added as its own branch here,
    never by weakening the default.

    Current safe patterns (everything else disqualifies):
      - The RECEIVER of a member access or subscript (`x.field`, `x[0]`,
        `x.method(...)`) when it's a bare identifier — reading through or
        calling a method on a container doesn't hand its pointer away.
      - A call argument resolved as providably non-retaining (a
        whitelisted builtin, or a resolved callee's `read` parameter).
      - `x^` (a transfer) is its own disqualifying event (rule 4), not a
        "read" at all — handled before the generic default would apply.
    """
    if node is None:
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _scan_expr(item, facts, funcs, methods, in_closure)
        return
    if not _is_node(node):
        return

    if isinstance(node, N.IdentExpr):
        facts.disqualify(node.name)  # the default — see docstring above
        return

    if isinstance(node, N.UnaryOp) and node.op == '^':
        if isinstance(node.operand, N.IdentExpr):
            facts.disqualify(node.operand.name)  # rule 4
            return
        _scan_expr(node.operand, facts, funcs, methods, in_closure)
        return

    if isinstance(node, (N.FunctionDef, N.LambdaExpr)):
        # Don't recurse with move/call-argument semantics inside a nested
        # scope — just disqualify anything it touches (rule 7) via the
        # in_closure flag. (Already covered by the new default too, since
        # a bare identifier disqualifies unconditionally now — in_closure
        # is kept for clarity/documentation of WHY, not because it still
        # changes behavior here.)
        for f in dataclasses.fields(node):
            _scan_expr(getattr(node, f.name), facts, funcs, methods, True)
        return

    if isinstance(node, N.CallExpr):
        callee = None if in_closure else _resolve_callee(node.func, funcs, methods)
        is_whitelisted_builtin = (not in_closure and isinstance(node.func, N.IdentExpr)
                                   and node.func.name in _NONRETAINING_BUILTINS)
        param_names = [p[0] for p in callee.params] if callee else []
        offset = 1 if (callee and isinstance(node.func, N.MemberExpr)) else 0

        def _arg_is_safe(idx):
            if in_closure:
                return False
            if is_whitelisted_builtin:
                return True
            if callee is None:
                return False
            real_idx = idx + offset
            if not (0 <= real_idx < len(param_names)):
                return False
            return callee.param_convs.get(param_names[real_idx]) == 'read'

        for i, a in enumerate(node.args):
            if isinstance(a, N.IdentExpr):
                if not _arg_is_safe(i):
                    facts.disqualify(a.name)
                # else: a bare identifier has no further substructure to
                # scan, and it's already been proven safe — do NOT also
                # route it through the generic IdentExpr default below.
            else:
                _scan_expr(a, facts, funcs, methods, in_closure)
        for kw_name, v in (node.kwargs or []):
            if isinstance(v, N.IdentExpr):
                safe = (not in_closure) and (is_whitelisted_builtin or (
                    callee is not None
                    and callee.param_convs.get(kw_name) == 'read'))
                if not safe:
                    facts.disqualify(v.name)
            else:
                _scan_expr(v, facts, funcs, methods, in_closure)
        # `node.func`: for `obj.method(...)`, `obj` is a safe receiver
        # (see docstring) — scanning `node.func` generically would hit
        # the MemberExpr case below, which already carries that same
        # safe-receiver logic, so no special-casing is needed here.
        _scan_expr(node.func, facts, funcs, methods, in_closure)
        return

    if isinstance(node, N.MemberExpr):
        if not isinstance(node.obj, N.IdentExpr):
            _scan_expr(node.obj, facts, funcs, methods, in_closure)
        # else: bare-identifier receiver of `.member` — safe (see docstring)
        return

    if isinstance(node, N.SubscriptExpr):
        if not isinstance(node.obj, N.IdentExpr):
            _scan_expr(node.obj, facts, funcs, methods, in_closure)
        # else: bare-identifier receiver of `[...]` — safe (see docstring),
        # same reasoning as MemberExpr — found for real via this exact
        # fix: without this case, `d["a"] = 1` (this module's single most
        # common validated pattern) would disqualify `d` merely for being
        # subscripted, since indexing has no dedicated carve-out otherwise.
        _scan_expr(node.index, facts, funcs, methods, in_closure)
        _scan_expr(getattr(node, 'attrs', None), facts, funcs, methods, in_closure)
        return

    for f in dataclasses.fields(node):
        _scan_expr(getattr(node, f.name), facts, funcs, methods, in_closure)


def _scan_assign_target_escape(target, facts: _FuncFacts):
    """Rule 5: a target that ISN'T the simple `name = ...` shape (a
    subscript/member target, e.g. `d[k] = x` or `self.f = x`) means
    whatever's on the RHS may now be reachable from somewhere else —
    handled by the caller checking the RHS separately; this only flags
    the non-identifier target's OWN object as a used receiver, not a
    disqualification by itself (see _scan_stmt's AssignStmt case)."""
    return isinstance(target, N.IdentExpr)


def _is_stmt_node(x) -> bool:
    """True for a node `_scan_stmt` (not `_scan_expr`) must visit when it is
    nested inside another statement's body. `VarDecl` is a statement whose
    class name does not end in `Stmt`, so the old `endswith('Stmt')` test
    sent every NESTED `var x = ...` to the expression scanner, which never
    records an assignment: a `var` inside a loop/if/try was invisible to
    the single-assignment rule (rule 2), and a redeclaration of a name
    inside a nested block did not count against it."""
    if isinstance(x, (N.FunctionDef, N.VarDecl)):
        return True
    return type(x).__name__.endswith('Stmt')


def _scan_stmt(stmt, facts: _FuncFacts, funcs, methods):
    if isinstance(stmt, (N.FunctionDef,)):
        for f in dataclasses.fields(stmt):
            _scan_expr(getattr(stmt, f.name), facts, funcs, methods, True)
        return

    if isinstance(stmt, (N.AssignStmt, N.VarDecl)):
        name = stmt.target.name if isinstance(stmt, N.AssignStmt) and isinstance(stmt.target, N.IdentExpr) \
            else (stmt.name if isinstance(stmt, N.VarDecl) else None)
        value = stmt.value
        is_simple_target = (isinstance(stmt, N.VarDecl)
                             or _scan_assign_target_escape(stmt.target, facts))
        if is_simple_target and name is not None:
            is_ctor = _is_constructor_expr(value)
            if not is_ctor and isinstance(value, N.IdentExpr):
                # `x = y`: y is now aliased by x — a value with more than
                # one believed owner. Disqualify the ALIASED name (y) too:
                # even if y itself was otherwise a clean single-assignment
                # constructor, x now holds the same pointer.
                facts.disqualify(value.name)
            facts.note_assign(name, is_ctor)
            _scan_expr(value, facts, funcs, methods)
        else:
            # Non-identifier target (subscript/member): its RHS is now
            # reachable from that container/object — disqualify a bare
            # identifier RHS as escaped, and still scan for nested uses.
            if isinstance(value, N.IdentExpr):
                facts.disqualify(value.name)
            _scan_expr(value, facts, funcs, methods)
            _scan_expr(stmt.target, facts, funcs, methods)
        return

    if isinstance(stmt, N.ReturnStmt):
        if isinstance(stmt.value, N.IdentExpr):
            facts.disqualify(stmt.value.name)  # rule 3
        elif isinstance(stmt.value, N.TupleExpr):
            for e in stmt.value.elements:
                if isinstance(e, N.IdentExpr):
                    facts.disqualify(e.name)
        _scan_expr(stmt.value, facts, funcs, methods)
        return

    if isinstance(stmt, N.DelStmt):
        for t in stmt.targets:
            if isinstance(t, N.IdentExpr):
                facts.disqualify(t.name)  # rule 8
            else:
                _scan_expr(t, facts, funcs, methods)
        return

    if isinstance(stmt, (N.GlobalStmt, N.NonlocalStmt)):
        for n in (stmt.names or []):
            facts.disqualify(n)
        return

    if isinstance(stmt, (N.PassStmt, N.BreakStmt, N.ContinueStmt,
                          N.ImportStmt, N.FromImportStmt)):
        return

    for f in dataclasses.fields(stmt):
        val = getattr(stmt, f.name)
        if isinstance(val, list):
            for item in val:
                if _is_node(item):
                    if _is_stmt_node(item):
                        _scan_stmt(item, facts, funcs, methods)
                    else:
                        _scan_expr(item, facts, funcs, methods)
        elif _is_node(val):
            if _is_stmt_node(val):
                _scan_stmt(val, facts, funcs, methods)
            else:
                _scan_expr(val, facts, funcs, methods)


def _intersect_all(sets: list) -> set:
    """Plain-loop replacement for `set.intersection(*sets)` (the unbound-
    method-called-with-star-unpacking idiom) — self-hosted codegen has no
    lowering for that shape at all: a real, reproducible test (`set.
    intersection(*[a, b, c])` on plain non-empty sets) returns an empty/
    wrong result under a compiled binary, and iterating it even trips the
    generic `mojo_unsupported_iter` fallback. Every one of this module's
    4 original call sites fed straight into `set` mutation/comparison, so
    this silently corrupted the whole definite-assignment pass under
    self-hosting (found via the same `make bootstrap` t_list.mojo
    divergence `analyze_function`'s own docstring documents — this was
    the SECOND, independent bug in that one chain, not a duplicate of
    the `facts`-typing fix).

    NOTE: `out = sets[0] & sets[0]` below (an `&` self-intersection), never
    a bare `out = sets[0]` subscript read and never `set(sets[0])` — a
    FOURTH, independent bug in this same chain, found 2026-09-20 via ASan
    (heap-buffer-overflow, `mojo_set_update` reading 8 bytes past the
    24-byte `MojoList *` `branch_sets_if`/`branch_sets_match`/`all_sets_try`
    itself — `_ia_if`/`_ia_match`/`_ia_try` held the enclosing LIST's own
    pointer, not one of its `MojoSet *` elements, whenever `live_if`/
    `live_match`/`all_sets_try` had exactly ONE surviving element, i.e. no
    loop iteration of `out = out & sets[i]` ever ran to invoke `&`'s type
    resolution). A bare `out = sets[0]` is a bare subscript read with no
    further operation forcing element-type recovery at all, and — per the
    THIRD bug this docstring already documents just below — `sets` (a
    plain `list` parameter with no element-type annotation the parser
    recognizes) loses its "elements are MojoSet*" tracking at the function
    boundary, so a bare `sets[0]` can come back typed as the LIST itself
    rather than the set at index 0. `set(sets[0])` has its own separate
    failure mode (documented below): self-hosted `set(<value read from an
    untyped list>)` silently degrades to `mojo_set_new()` (a fresh EMPTY
    set, `/* TODO: comprehension over int64_t */` in the generated C), not
    an error. `sets[0] & sets[i]` (a genuine `&`, even self-intersection)
    doesn't hit either failure: the `&` operator's own type resolution
    (unlike a bare subscript read OR `set()`'s constructor dispatch)
    correctly recovers the real MojoSet* regardless. Since `&` (not `&=`)
    always allocates a fresh result set, `out` is never the same object as
    `sets[0]`, so this doesn't alias/mutate any of the caller's original
    sets either — true for the self-intersection base case too."""
    if not sets:
        return set()
    # `_set_view(...)` on every element, NOT a bare `sets[i]`: see `_set_view`'s
    # own docstring — untyped-list elements erase to int64_t, so
    # `sets[0] & sets[i]` was a bitwise AND of two heap pointers (the
    # `&`-type-resolution claim this docstring used to make only held when
    # the elements were already statically MojoSet*). A real ASan
    # heap-buffer-overflow in `mojo_set_update` (called from `_dfa_stmt`'s
    # loop-arm `assigned.update(_new_assigned)` with TWO elements) was this
    # exact bug; the one-element case got lucky because `p & p == p`.
    _first = _set_view(sets[0])
    out = _first & _first
    for i in range(1, len(sets)):
        out = out & _set_view(sets[i])
    return out


def _dfa_if(stmt, assigned: set, terminals: list) -> None:
    """The `_dfa_stmt` IfStmt/ComptimeIfStmt case, extracted into its own
    function (2026-09-20). Was inlined directly in `_dfa_stmt`'s own body
    alongside the TryStmt/MatchStmt cases — even after two independent
    fixes (flat lists instead of `(set, bool)` tuples; every local given
    a branch-unique `_if`/`_try`/`_match` suffix), `make bootstrap`/native
    `--dump-full fire.py` still crashed `mojo_set_update` intermittently
    (confirmed via AddressSanitizer, not just lldb: `_ia_if`'s VALUE
    equaled `branch_sets_if`'s own `MojoList *` pointer — the wrong
    OBJECT entirely, not merely a wrong TYPE tag — even though every
    individual step of the generated GIMPLE, read line by line, was
    verified structurally correct). Root cause never fully pinned down
    at the instruction level (GCC's `-fgimple -O0` register/stack-slot
    allocation for `_dfa_stmt` as ONE ~820-local function was the leading
    suspect, not a logic bug in this module), but extracting each branch
    into its OWN function — this project's own documented fix pattern
    for this exact bug class, see `gimple_module_gen.py`'s
    `_emit_reflection_dispatch` history — shrinks each branch to a small,
    independent stack frame and is the standard remedy here. If this
    ever regresses again, suspect this function specifically rather than
    re-inlining it."""
    branch_sets_if: list = []
    branch_terms_if: list = []
    a1_if = set(assigned)
    _dfa_walk_block(stmt.then_body, a1_if, terminals)
    branch_sets_if.append(a1_if)
    branch_terms_if.append(_block_terminates(stmt.then_body))
    for cond_if, body_if in (stmt.elifs or []):
        a_if = set(assigned)
        _dfa_walk_block(body_if, a_if, terminals)
        branch_sets_if.append(a_if)
        branch_terms_if.append(_block_terminates(body_if))
    if stmt.else_body is not None:
        a_if = set(assigned)
        _dfa_walk_block(stmt.else_body, a_if, terminals)
        branch_sets_if.append(a_if)
        branch_terms_if.append(_block_terminates(stmt.else_body))
    else:
        branch_sets_if.append(set(assigned))
        branch_terms_if.append(False)
    live_if: list = []
    for i_if in range(len(branch_sets_if)):
        if not branch_terms_if[i_if]:
            live_if.append(branch_sets_if[i_if])
    assigned.clear()
    if live_if:
        # `_ia_if` as its own local, NOT `assigned.update(
        # _intersect_all(live_if))` inline — see this same note
        # elsewhere in this module: a `-> set`-returning call's
        # result must be stored into a local before being handed to
        # another method call as an argument, not passed through
        # directly.
        _ia_if = _intersect_all(live_if)
        assigned.update(_ia_if)


def _dfa_try(stmt, assigned: set, terminals: list) -> None:
    """The `_dfa_stmt` TryStmt case, extracted into its own function —
    see `_dfa_if`'s docstring for why."""
    pre_try = set(assigned)
    try_assigned_try = set(assigned)
    _dfa_walk_block(stmt.body, try_assigned_try, terminals)
    all_sets_try = [try_assigned_try]
    for h_try in (stmt.handlers or []):
        # Same reasoning as ownership_check.py's TryStmt case: a
        # handler can run after an exception struck at ANY point in
        # the try body, so it must not be credited with anything the
        # try body itself assigned — start from the PRE-try state.
        ha_try = set(pre_try)
        # Direct attribute access, NOT `getattr(h_try, 'body', [])`:
        # `ExceptHandler.body` is a plain always-present `list` field
        # (fire_compiler.py's ExceptHandler dataclass), but a
        # `getattr(..., default)` read on a self-hosted struct goes
        # through the generic dynamic-dispatch path, which returns an
        # opaque value with NO element-type metadata even when the
        # field is guaranteed to exist — corrupting every set this
        # value's elements later flow into. Root-caused 2026-09-20
        # while chasing the whole-program `--dump-full` mojo_set_update
        # EXC_BAD_ACCESS crash.
        _htb = h_try.body
        _dfa_walk_block(_htb if _htb else [], ha_try, terminals)
        all_sets_try.append(ha_try)
    assigned.clear()
    _ia_try = _intersect_all(all_sets_try)
    assigned.update(_ia_try)
    if stmt.else_body:
        _dfa_walk_block(stmt.else_body, assigned, terminals)
    if stmt.finally_body:
        _dfa_walk_block(stmt.finally_body, assigned, terminals)


def _dfa_match(stmt, assigned: set, terminals: list) -> None:
    """The `_dfa_stmt` MatchStmt case, extracted into its own function —
    see `_dfa_if`'s docstring for why."""
    branch_sets_match: list = []
    branch_terms_match: list = []
    for case_match in (stmt.cases or []):
        a_match = set(assigned)
        # Direct attribute access, NOT `getattr(case_match, 'body', [])`
        # — see the TryStmt handler-body note above for why: `MatchCase.
        # body` is a plain always-present `list` field, but `getattr`
        # with a default goes through the generic dynamic-dispatch path
        # and loses element-type metadata even so.
        body_match = case_match.body
        _dfa_walk_block(body_match if body_match else [], a_match, terminals)
        branch_sets_match.append(a_match)
        branch_terms_match.append(_block_terminates(body_match))
    branch_sets_match.append(set(assigned))  # no wildcard case: may fall through
    branch_terms_match.append(False)
    live_match: list = []
    for i_match in range(len(branch_sets_match)):
        if not branch_terms_match[i_match]:
            live_match.append(branch_sets_match[i_match])
    assigned.clear()
    if live_match:
        _ia_match = _intersect_all(live_match)
        assigned.update(_ia_match)


def _dfa_stmt(stmt, assigned: set, terminals: list) -> None:
    """Mutates `assigned` in place to reflect what's definitely assigned
    immediately AFTER `stmt`, given it was the set immediately before.
    Appends a snapshot to `terminals` at every point control could leave
    the function (a `return`, or falling off the end of a block that
    doesn't itself terminate — the latter is handled by the caller after
    the top-level walk, matching `_block_terminates`'s own convention).

    The IfStmt/TryStmt/MatchStmt cases are each their own top-level
    function (`_dfa_if`/`_dfa_try`/`_dfa_match`) rather than inlined
    here — see `_dfa_if`'s docstring for why (a real, AddressSanitizer-
    confirmed `mojo_set_update` memory-corruption bug tied to this
    dispatch being one enormous function, not fixed by giving every
    branch's locals unique names alone)."""
    if isinstance(stmt, N.AssignStmt) and isinstance(stmt.target, N.IdentExpr):
        assigned.add(_as_str(stmt.target.name))
        return
    if isinstance(stmt, N.VarDecl):
        assigned.add(_as_str(stmt.name))
        return
    if isinstance(stmt, N.ReturnStmt):
        terminals.append(set(assigned))
        return
    if isinstance(stmt, (N.RaiseStmt, N.BreakStmt, N.ContinueStmt)):
        # These terminate the CURRENT block but aren't "the function
        # exits here with this binding needing to be freed" points under
        # this whole-function model (a `raise` unwinds to a handler or
        # the caller — see doc/OWNERSHIP_MODEL.md's exception-handling
        # cross-cutting section for why that's its own unresolved
        # problem, not something this module should paper over by
        # treating `raise` as a normal exit point).
        return
    if isinstance(stmt, (N.IfStmt, N.ComptimeIfStmt)):
        _dfa_if(stmt, assigned, terminals)
        return
    if isinstance(stmt, (N.WhileStmt, N.ForStmt, N.ComptimeForStmt)):
        # A loop may run zero times, so anything only assigned INSIDE the
        # body is not definitely assigned after it — intersect the body's
        # own exit state with the pre-loop state (the "0 iterations" case)
        # exactly like an if with an implicit empty else.
        body_assigned = set(assigned)
        _dfa_walk_block(stmt.body, body_assigned, terminals)
        # `_intersect_all` + reassign, NOT `assigned.intersection_update
        # (body_assigned)` — self-hosted codegen for `set.intersection_
        # update()` was found to silently give a WRONG result (a real,
        # reproducible test: {"x","y","z"}.intersection_update({"y","z",
        # "w"}) left the receiver at length 3, not the correct 2), the
        # same underlying gap `_intersect_all` (see its own docstring)
        # already exists to route around for `set.intersection(*args)`.
        _new_assigned = _intersect_all([assigned, body_assigned])
        assigned.clear()
        assigned.update(_new_assigned)
        return
    if isinstance(stmt, N.TryStmt):
        _dfa_try(stmt, assigned, terminals)
        return
    if isinstance(stmt, N.WithStmt):
        _dfa_walk_block(stmt.body, assigned, terminals)
        return
    if isinstance(stmt, N.MatchStmt):
        _dfa_match(stmt, assigned, terminals)
        return
    if isinstance(stmt, N.FunctionDef):
        return  # nested def: its own body's assignments don't count here
    # Everything else (pass, expr-stmt, del, assert, global, import, ...)
    # has no effect on which candidate names are definitely assigned.


def _dfa_walk_block(body, assigned: set, terminals: list) -> None:
    for stmt in body:
        _dfa_stmt(stmt, assigned, terminals)


def _definitely_assigned(fn, candidates: set) -> set:
    """Of `candidates` (names already cleared by the escape analysis
    above), returns only those provably assigned on EVERY path from
    function entry to EVERY point control can leave the function — see
    the module docstring's "NOT a definite-assignment analysis" limitation
    this closes. A candidate assigned inside only one arm of a branch,
    with a free point reachable without ever taking that arm, is excluded
    here rather than risk freeing an uninitialized/never-constructed
    binding."""
    if not candidates:
        return set()
    assigned = set()
    terminals = []
    _dfa_walk_block(fn.body, assigned, terminals)
    if not _block_terminates(fn.body):
        terminals.append(assigned)  # falls off the end: implicit return
    if not terminals:
        return set()
    # `_ia_term` as its own local — same rule as `_ia_if`/`_ia_try`/
    # `_ia_match`/`analyze_function`'s `_candidates` elsewhere in this
    # module: store a `-> set`-returning call's result before using it,
    # rather than folding it directly into another expression that's
    # itself immediately returned.
    _ia_term = _intersect_all(terminals)
    return candidates & _ia_term


def _scan_function(fn, funcs, methods) -> _FuncFacts:
    """The whole-function escape scan shared by `analyze_function` and
    `analyze_scoped_locals`: every fact the module docstring's rules 1-8
    need, accumulated over `fn`'s body. `facts` is explicitly typed
    `_FuncFacts` for the same self-hosting reason `analyze_function`'s
    docstring gives — an untyped receiver makes `facts.note_assign(...)`
    an auto-stubbed no-op."""
    facts = _FuncFacts()
    for pname, _ in fn.params:
        # Parameters are out of scope for v0 (see module docstring) —
        # mark them disqualified outright so a same-named local shadow
        # can't accidentally get credited with the parameter's uses.
        facts.disqualify(pname.lstrip('*'))
    for stmt in fn.body:
        _scan_stmt(stmt, facts, funcs, methods)
    return facts


def analyze_function(fn, funcs, methods) -> set:
    """Returns the set of local names in `fn` that are destroy candidates
    per the module docstring's rules 1-8, AND are definitely assigned on
    every path to every point the function can exit (see
    `_definitely_assigned`).

    `facts` below is explicitly typed `_FuncFacts` (as are the `facts`
    parameters of every helper this calls transitively — `_scan_expr`/
    `_scan_stmt`/`_scan_assign_target_escape`) — this is LOAD-BEARING,
    not stylistic. Self-hosted: an untyped (bare Python, no annotation)
    parameter that later has a user-defined-class method called on it
    (`facts.note_assign(...)`, `facts.disqualify(...)`) can't be resolved
    to a real struct method at that call site, so the self-hosted
    compiler silently AUTO-STUBS the call (`int64_t.note_assign() ...
    stubbed` — a no-op, not an error) instead of raising or falling back
    to dynamic dispatch. Found via a real, reproducible `make bootstrap`
    stage1-vs-stage2 divergence (t_list.mojo's `.ci` missing `mojo_
    cleanup_push_list`/`mojo_list_free`): self-hosted `analyze_function`
    ran to completion, `_scan_stmt` was called the right number of times,
    but every `facts.note_assign`/`facts.disqualify` call inside it was
    silently a no-op, so `facts.assign_count` stayed empty end to end —
    python3 (which runs this module as plain, uncompiled CPython even
    when compiling something else) was correct throughout and never hit
    this at all, which is why it was invisible until the C runtime's
    python3-subprocess fallback was removed."""
    facts = _scan_function(fn, funcs, methods)
    # `_candidates` as its own local, NOT `_definitely_assigned(fn, facts.
    # candidates())` inline — this file's own repeatedly-documented rule
    # (see `_ia_if`/`_ia_try`/`_ia_match`'s identical notes): a `-> set`-
    # returning call's result must be stored into a local before being
    # handed to another call as an argument, never passed through
    # directly. This exact line was the one place in the whole module
    # that still broke that rule — found via AddressSanitizer 2026-09-20
    # (heap-buffer-overflow in `mojo_set_update`, `src` aliasing a
    # `MojoList *` built by `mojo_dict_items` inside `_FuncFacts.
    # candidates()` itself, i.e. `_definitely_assigned`'s second
    # parameter wasn't reliably typed `MojoSet *` at this call site).
    _candidates = facts.candidates()
    return _definitely_assigned(fn, _candidates)


def _count_name(node, name: str) -> int:
    """How many times the identifier `name` occurs anywhere under `node`,
    as ANY string-valued field (an `IdentExpr.name`, a `VarDecl.name`, a
    loop/with/except target, a parameter, ...). Counting every string leaf
    that equals `name`, rather than only `IdentExpr`, is deliberately
    over-inclusive: an occurrence this counts that is not really a use can
    only make a name look MORE widely used, which disqualifies it — never
    the unsafe direction."""
    if isinstance(node, str):
        if node == name:
            return 1
        return 0
    n = 0
    if isinstance(node, (list, tuple)):
        for item in node:
            n += _count_name(item, name)
        return n
    if _is_node(node):
        for f in dataclasses.fields(node):
            n += _count_name(getattr(node, f.name), name)
    return n


def _collect_loop_bodies(node, out: list) -> None:
    """Appends the body (statement list) of every `for`/`while` under `node`
    that has no `else:` clause. A loop with an `else` is skipped: `break`
    bypasses it, so its exits are not the plain "end of body / break /
    continue" set the block-scoped free is built for."""
    if isinstance(node, (list, tuple)):
        for item in node:
            _collect_loop_bodies(item, out)
        return
    if not _is_node(node):
        return
    if isinstance(node, (N.ForStmt, N.WhileStmt)) and not node.else_body:
        out.append(node.body)
    for f in dataclasses.fields(node):
        _collect_loop_bodies(getattr(node, f.name), out)


def _decl_name(stmt) -> str:
    """The local a plain single-target declaration/assignment statement
    binds, or '' if `stmt` is not one."""
    if isinstance(stmt, N.VarDecl):
        return _as_str(stmt.name)
    if isinstance(stmt, N.AssignStmt) and isinstance(stmt.target, N.IdentExpr):
        return _as_str(stmt.target.name)
    return ''


def analyze_scoped_locals(fn, funcs, methods, whole: set) -> set:
    """Block-scoped twin of `analyze_function`: the locals that are a
    destroy candidate for THEIR LOOP BODY rather than for the whole
    function, i.e. exactly the ones `analyze_function` cannot credit
    because a loop may run zero times (so they are never "definitely
    assigned at every function exit") — `whole` is `analyze_function`'s
    result and is excluded, so each candidate is owned at exactly one level.

    A name qualifies iff ALL of:
      - it is a candidate by the module docstring's rules 1-8 (assigned
        exactly once, from a container constructor, never escaping);
      - that one assignment is a DIRECT child statement of a `for`/`while`
        body with no `else:` (so every path that reaches the end of the
        body, or any `break`/`continue`/`return` lexically after the
        declaration, has executed it — no definite-assignment analysis is
        needed because straight-line order within one block is the proof);
      - the name occurs NOWHERE outside that declaration and the rest of
        that body (`_count_name` over the whole function equals the count
        over `body[idx:]`). This is what makes the free at the end of the
        body safe for plain-Python source, where a loop-body local stays
        visible after the loop: any later read would be a use-after-free.
    The free itself is emitted per iteration at the end of the body and
    before each `break`/`continue`/`return` that leaves it (codegen side:
    mojo/backend_gimple/emit_infra.py's block-scope section)."""
    out = set()
    bodies = []
    _collect_loop_bodies(fn.body, bodies)
    if not bodies:
        return out
    # Cheap pre-check before the full escape scan: is there any loop-body
    # direct-child constructor declaration at all?
    have_ctor_decl = False
    for body in bodies:
        for st in body:
            if _decl_name(st) != '' and _is_constructor_expr(st.value):
                have_ctor_decl = True
    if not have_ctor_decl:
        return out
    facts = _scan_function(fn, funcs, methods)
    _cands = facts.candidates()
    for body in bodies:
        for idx in range(len(body)):
            st = body[idx]
            nm = _decl_name(st)
            if nm == '' or nm not in _cands or nm in whole:
                continue
            region = 0
            for j in range(idx, len(body)):
                region += _count_name(body[j], nm)
            if _count_name(fn.body, nm) == region:
                out.add(nm)
    return out


def analyze_module(stmts):
    """Returns {qualified_name: set(candidate_local_names)} for every
    function and struct method in a parsed module, where qualified_name
    is the bare function name or "Struct.method"."""
    result = {}
    funcs = {}
    structs = []
    for s in stmts:
        if isinstance(s, N.FunctionDef):
            funcs[s.name] = s
        elif isinstance(s, N.StructDef):
            structs.append(s)

    for s in stmts:
        if isinstance(s, N.FunctionDef):
            cands = analyze_function(s, funcs, {})
            if cands:
                result[s.name] = cands

    for st in structs:
        method_table = {m.name: m for m in st.methods}
        for m in st.methods:
            cands = analyze_function(m, funcs, method_table)
            if cands:
                result[f"{st.name}.{m.name}"] = cands

    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print("usage: python3 ownership_destruct.py <file.mojo>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    src = open(path).read()
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).with_filename(path).parse_module()
    result = analyze_module(stmts)
    if not result:
        print(f"{path}: no destroy candidates found")
    for qname, names in result.items():
        print(f"{path}: {qname}: {sorted(names)}")
