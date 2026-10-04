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
       parameter is PROVABLY non-escaping, decided from the CALLEE'S OWN
       BODY by `_summarize_params` — not from a `read` convention keyword.
       In real Mojo a `read` parameter cannot be stored, but this compiler
       lowers a copy (`var y = param`) as the SAME pointer, so a callee that
       copied its `read` parameter into a field would leave the caller's
       container aliased (see `_summarize_params`'s docstring for the real
       crash that motivated this). An unresolved call, or a resolved one whose
       matching parameter may escape, downgrades `x` — being used only via ITS
       OWN methods (`x.append(...)`, `x["k"] = v`) is fine and does NOT count as
       a call-argument use, since `x` there is the method's receiver (`.obj`),
       not one of `args`/`kwargs`.
  7. `x` never appears inside a nested `def`/`LambdaExpr` in the same
     function (a possible closure capture) — conservative exclusion,
     since this module (like ownership_check.py's Phase 1) does not
     analyze closures.
     Deliberately still blanket, even though the parser now records an
     explicit capture list (`FunctionDef.captures` /
     `has_capture_list`) that would in principle say exactly which names
     a nested scope can capture. `_nested_capture_names` already computes
     that set and `analyze_returns_fresh` uses it, so the information
     exists — but this rule rests on the module's core soundness default
     ("a bare IdentExpr reached through generic recursion always
     disqualifies that name... if a future change needs a new safe
     pattern, it must be added as its own branch here, never by weakening
     the default"), and rule 7 has no such branch. Narrowing it would buy
     recall on a rare shape (a nested def rebinding a name that is also
     an enclosing container candidate) at the cost of the one failure
     mode this analysis is built to have none of: a wrong free. Left
     alone deliberately, not overlooked.
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


# `str` is deliberately NOT here. For a container it builds a new string, but for
# a string it is the identity (`x = str(s)` lowers to `x = s`), so a call on a
# name that might be a string can return its own argument: an alias. The rest
# either return a number or a freshly built string.
_NONRETAINING_BUILTINS = {'len', 'print', 'repr', 'bool', 'hash', 'id'}

# Binary operators whose result is a NEW value (a concatenation, a repeat, a
# formatted string, a bool): the operands are read, never handed on. Comparisons
# with a single `==`/`<`/... parse as a plain BinaryOp, not a CompareChain.
# `and`/`or` are deliberately absent: their result IS one of their operands.
_READ_ONLY_BINOPS = ('+', '*', '%', '==', '!=', '<', '>', '<=', '>=')


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
    # `List[T]()` / `Dict[K, V]()` / `Set[T]()` with nothing in the parentheses:
    # the typed spelling of an empty container, lowered to a brand-new one.
    if (isinstance(node, N.CallExpr) and isinstance(node.func, N.SubscriptExpr)
            and isinstance(node.func.obj, N.IdentExpr)
            and _as_str(node.func.obj.name) in ('List', 'Dict', 'Set')
            and not node.args and len(node.kwargs or []) == 0):
        return True
    return False


def _is_fresh_string_expr(node) -> bool:
    """True iff `node` is an EXPRESSION whose value is a brand-new heap
    allocation the receiver/caller can never name — so a callee that returns it
    hands its caller sole ownership, exactly as `analyze_returns_fresh` already
    concludes for a container display.

    Every form here was read in the lowering, not inferred from a type:
      - `a + b` — `mojo_str_cat` always copies (doc/MEMORY.html §4.2), and on
        a list the same spelling is `mojo_list_concat`, a fresh list. Either
        way the result is not an alias of an operand. A non-container `+` (two
        ints) is an `int64_t`, which the declaration gate never frees, so
        accepting it is inert rather than wrong.
      - an f-string — its accumulator is built by `_emit_str_cat` and is fresh
        by the same argument.
      - `s[a:b]` — `mojo_cstr_slice` is on the runtime's fresh-string list and
        `mojo_list_slice` on its fresh-container one.

    Deliberately NOT accepted, each because it can return its own argument and a
    `free()` of that is a crash: `str(s)`/`String(s)` (the identity for a
    string — emit_calls.py's `fname_raw == 'str'` branch returns `ev`
    unchanged), a bare string method call (the receiver rules in
    `receiver_results_consumed` decide those, per call site, and the receiver
    may not even be a string), and any other call (whether it is fresh is
    exactly the question being asked)."""
    if isinstance(node, (N.TstringLiteral, N.SliceExpr)):
        return True
    return isinstance(node, N.BinaryOp) and node.op == '+'


def _is_maybe_fresh_expr(node) -> bool:
    """A right-hand side that MAY build a brand-new container the assigned name
    would solely own: a call (a runtime function such as `.split()`/`.keys()`,
    or a user function), a slice, a comprehension, or a `+` (list concat).
    "May" is the point — the analysis cannot tell `x = s.split(" ")` (a fresh
    list) from `x = self.items` reached through a call (a stored one). It
    credits the name as a candidate, and CODEGEN, which knows what the value
    really is, keeps ownership only when it can prove the value fresh at the
    declaration (emit_infra.maybe_push_owned_local); otherwise the name is
    dropped from the candidates right there."""
    if isinstance(node, (N.CallExpr, N.SliceExpr, N.Comprehension, N.TstringLiteral)):
        return True
    if isinstance(node, N.BinaryOp) and node.op == '+':
        return True
    return False


class _FuncFacts:
    """Accumulated, whole-function facts about every plain-identifier local
    — see module docstring for exactly what each disqualifies."""

    def __init__(self):
        self.assign_count = {}       # name -> int
        self.all_ctor_assigns = {}   # name -> bool (True until proven False)
        self.disqualified = set()    # names ruled out by rules 3-8
        # Callee parameter summaries (see `_summarize_params`): memo maps a
        # callee's name to the '|'-joined names of its non-escaping
        # parameters (a string, not a set, on purpose — a set read out of a
        # dict value is the self-hosting trap this module documents
        # elsewhere); `visiting` is the chain of callees being summarised
        # right now, so a recursive call is treated as escaping.
        self.memo = {}
        self.visiting = []
        # analyze_returns_fresh scans a callee with a bare `return name` allowed
        # (recorded, not an escape) and needs to know which names were built
        # ONLY by container displays, not merely by "maybe fresh" calls.
        self.allow_return = False
        self.all_display = {}        # name -> bool: every assignment a display
        # Struct instances. `structs` maps a struct name to {method name:
        # FunctionDef} for the module's structs whose constructor the caller has
        # vetted (see infra_infer._build_analysis_structs); `struct_bound` maps
        # a local to the struct name it was constructed as. A struct local is
        # a candidate only while every use is a field access or a call to one of
        # its methods that provably does not retain `self`.
        self.structs = {}
        self.struct_bound = {}

    def note_assign(self, name: str, is_ctor: bool, is_display: bool = False):
        self.assign_count[name] = self.assign_count.get(name, 0) + 1
        prev = self.all_ctor_assigns.get(name, True)
        self.all_ctor_assigns[name] = prev and is_ctor
        prev_d = self.all_display.get(name, True)
        self.all_display[name] = prev_d and is_display

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


    def ctor_names(self) -> set:
        """Names every one of whose assignments is a container constructor
        and that no rule disqualified, whatever the assignment COUNT —
        the input to the block-scoped analysis, which decides ownership per
        declaration site instead of per function (so the same name declared
        in two sibling loop bodies can qualify, `candidates()` requires one).
        Keys only, for the same self-hosting reason as `candidates()`."""
        out = set()
        for name in self.assign_count:
            if self.all_ctor_assigns.get(name) and name not in self.disqualified:
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


def _summarize_params(callee, funcs, methods, memo: dict, visiting: list, structs=None) -> str:
    """'|'-joined names of `callee`'s parameters that PROVABLY do not escape
    it, by the same escape rules this module applies to a local: analysing
    the callee's own body with its parameters treated as ordinary names, a
    parameter that is never returned, stored, aliased, captured, moved or
    handed to something that might keep it does not outlive the call.

    This replaces trusting a `read` convention keyword. In real Mojo a `read`
    parameter cannot be stored, but this compiler lowers a copy of a value
    (`var y = param`) as the SAME pointer, so a callee that copies its
    `read` parameter into a field would leave the caller's container
    reachable after the caller frees it. The body analysis has no such gap:
    an alias (`y = param`) disqualifies `param` exactly as it would a local.

    Conservative by construction: '' (nothing proven) for a callee that is
    async/a generator (its parameters live in a frame that outlives the
    call) or decorated (a wrapper may keep them), for a recursive call, and
    once two callees are already being summarised (bounds the work per call
    site to a small constant instead of the whole call graph)."""
    key = callee.name
    if key in memo:
        return memo[key]
    if key in visiting or len(visiting) >= 2:
        return ''
    if callee.is_async or callee.is_generator or callee.decorators:
        memo[key] = ''
        return ''
    sub = _FuncFacts()
    sub.memo = memo
    sub.visiting = visiting + [key]
    sub.structs = structs or {}
    _prescan_struct_binds(callee.body, sub)
    for stmt in callee.body:
        _scan_stmt(stmt, sub, funcs, methods)
    out = ''
    for pname, _ in callee.params:
        p = pname.lstrip('*')
        if p not in sub.disqualified:
            out = out + p + '|'
    memo[key] = out
    return out


def _struct_ctor_name(node, facts: _FuncFacts) -> str:
    """The struct a call constructs (`Pt(...)` for a struct the caller vetted),
    or ''."""
    if (isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr)
            and node.func.name in facts.structs):
        return _as_str(node.func.name)
    return ''


def _prescan_struct_binds(node, facts: _FuncFacts) -> None:
    """Record every `name = Struct(...)` / `var name = Struct(...)` in `node`
    BEFORE the escape scan runs. The scan is a single forward walk, and a use of
    `name.method()` that appears lexically before the binding (a loop body, a
    branch) would otherwise be judged as a plain container receiver, i.e. safe.
    A name bound as two different structs is disqualified."""
    if not facts.structs:
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _prescan_struct_binds(item, facts)
        return
    if not _is_node(node):
        return
    nm = ''
    if isinstance(node, N.VarDecl):
        nm = _as_str(node.name)
    elif isinstance(node, N.AssignStmt) and isinstance(node.target, N.IdentExpr):
        nm = _as_str(node.target.name)
    if nm != '':
        sname = _struct_ctor_name(node.value, facts)
        if sname != '':
            prev = facts.struct_bound.get(nm, '')
            if prev != '' and prev != sname:
                facts.disqualify(nm)
            facts.struct_bound[nm] = sname
    for f in dataclasses.fields(node):
        _prescan_struct_binds(getattr(node, f.name), facts)


def _scan_operand(op, read_only_position: bool, facts: _FuncFacts, funcs, methods) -> None:
    """One operand of an operator/condition: a bare identifier in a position that
    only reads it is not an escape (unless it is a struct instance, whose
    operators run user code); anything else is scanned normally."""
    if (isinstance(op, N.IdentExpr) and read_only_position
            and facts.struct_bound.get(_as_str(op.name), '') == ''):
        return
    _scan_expr(op, facts, funcs, methods)


def _param_is_nonescaping(callee, pname: str, funcs, methods, facts: _FuncFacts) -> bool:
    summary = _summarize_params(callee, funcs, methods, facts.memo, facts.visiting, facts.structs)
    return pname in summary.split('|')


def _call_arg_is_safe(idx: int, in_closure: bool, is_whitelisted_builtin: bool, callee,
                      param_names: list, offset: int, funcs, methods,
                      facts: _FuncFacts) -> bool:
    """Is the `idx`th positional argument of a call safe to pass a bare local to?

    A module-level function taking everything it reads as a parameter, not a
    closure nested in `_scan_expr` (which is what this used to be). Self-hosted,
    the nested form's captured-variable environment was laid out in a different
    order where it was built than where it was read, so `len(param_names)` read
    the `is_whitelisted_builtin` slot (`True`, i.e. 1) as a list and
    `mojoc --dump-full fire.py` died in `mojo_list_len(0x1)` while analysing the
    compiler's own sources."""
    if in_closure:
        return False
    if is_whitelisted_builtin:
        return True
    if callee is None:
        return False
    real_idx = idx + offset
    if not (0 <= real_idx < len(param_names)):
        return False
    return _param_is_nonescaping(callee, param_names[real_idx], funcs, methods, facts)


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
        if (callee is not None and isinstance(node.func, N.IdentExpr)
                and (node.func.name in facts.assign_count
                     or node.func.name in facts.disqualified)):
            # The caller assigns or receives a local of this name (a function
            # pointer, a parameter): it is not the module-level function.
            callee = None
        # `p.method(...)` where `p` is a struct instance this function
        # constructed: the call is safe for `p` only if that method provably
        # does not retain `self`; the method then also supplies the parameter
        # conventions for the remaining arguments.
        struct_recv = ''
        if (callee is None and not in_closure and isinstance(node.func, N.MemberExpr)
                and isinstance(node.func.obj, N.IdentExpr)):
            _rn = _as_str(node.func.obj.name)
            _sn = facts.struct_bound.get(_rn, '')
            if _sn != '':
                struct_recv = _rn
                _m = facts.structs.get(_sn, {}).get(node.func.member)
                # Explicit nested tests, NOT `_m is not None and _m.params and
                # ...`: self-hosted, a bool operand followed by a list operand in
                # one `and` chain feeds the BOOL's raw value (1) into the later
                # `mojo_list_len` truthiness check -- `mojo_list_len(0x1)`, the
                # SIGSEGV that ended `mojoc --dump-full fire.py` here (the same
                # class as emit_infra._reset_func's `params or ()`, e7fc3ec).
                _callee_ok = False
                if _m is not None:
                    if len(_m.params) > 0:
                        _callee_ok = _param_is_nonescaping(_m, _m.params[0][0], funcs, methods, facts)
                if _callee_ok:
                    callee = _m
                else:
                    facts.disqualify(_rn)
        is_whitelisted_builtin = (not in_closure and isinstance(node.func, N.IdentExpr)
                                   and node.func.name in _NONRETAINING_BUILTINS)
        param_names = [p[0] for p in callee.params] if callee else []
        offset = 1 if (callee and isinstance(node.func, N.MemberExpr)) else 0

        for i, a in enumerate(node.args):
            if isinstance(a, N.IdentExpr):
                if not _call_arg_is_safe(i, in_closure, is_whitelisted_builtin, callee,
                                         param_names, offset, funcs, methods, facts):
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
                    and _param_is_nonescaping(callee, kw_name, funcs, methods, facts)))
                if not safe:
                    facts.disqualify(v.name)
            else:
                _scan_expr(v, facts, funcs, methods, in_closure)
        # `node.func`: for `obj.method(...)`, `obj` is a safe receiver
        # (see docstring) — scanning `node.func` generically would hit
        # the MemberExpr case below, which already carries that same
        # safe-receiver logic, so no special-casing is needed here. A struct
        # receiver was fully decided above (and would look like a bound-method
        # VALUE to the MemberExpr rule).
        if struct_recv == '':
            _scan_expr(node.func, facts, funcs, methods, in_closure)
        return

    if isinstance(node, N.MemberExpr):
        if not isinstance(node.obj, N.IdentExpr):
            _scan_expr(node.obj, facts, funcs, methods, in_closure)
        else:
            _rn2 = _as_str(node.obj.name)
            _sn2 = facts.struct_bound.get(_rn2, '')
            if _sn2 != '' and node.member in facts.structs.get(_sn2, {}):
                # `p.method` NOT in call position (a call is handled in the
                # CallExpr case): a bound method captures `self`, so `p` now
                # lives wherever that value goes.
                facts.disqualify(_rn2)
        # else: bare-identifier receiver of `.member` — safe (see docstring)
        return

    if isinstance(node, N.SliceExpr):
        # `name[a:b]` READS `name` and builds a new container from it (the
        # runtime copies the elements), exactly like `name[i]`: a bare
        # identifier receiver is safe, the bounds are scanned normally.
        if not isinstance(node.obj, N.IdentExpr):
            _scan_expr(node.obj, facts, funcs, methods, in_closure)
        _scan_expr(node.start, facts, funcs, methods, in_closure)
        _scan_expr(node.stop, facts, funcs, methods, in_closure)
        _scan_expr(node.step, facts, funcs, methods, in_closure)
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

    # Operators and conditions that only READ a bare local. Left operand of `+`,
    # `*`, `%` and the first operand of a comparison: the runtime copies (concat,
    # repeat) or compares, and never keeps the operand. A RIGHT operand is only
    # safe when the left one is a string literal (`"n=" + s`): otherwise the
    # left operand may be a user type whose `__add__`/`__eq__` receives it and
    # can keep it. Never for `and`/`or` (the result IS one of the operands) and
    # never for a struct instance (its operators run user code).
    if isinstance(node, N.BinaryOp) and node.op in _READ_ONLY_BINOPS and not in_closure:
        _lit_left = isinstance(node.left, (N.StringLiteral, N.TstringLiteral))
        _scan_operand(node.left, True, facts, funcs, methods)
        _scan_operand(node.right, _lit_left, facts, funcs, methods)
        return
    if isinstance(node, N.CompareChain) and not in_closure:
        _prev_lit = False
        for _op in node.operands:
            _scan_operand(_op, _prev_lit or _op is node.operands[0], facts, funcs, methods)
            _prev_lit = isinstance(_op, (N.StringLiteral, N.TstringLiteral))
        return
    if isinstance(node, N.UnaryOp) and node.op == 'not' and not in_closure:
        _scan_operand(node.operand, True, facts, funcs, methods)
        return
    if isinstance(node, N.TernaryExpr) and not in_closure:
        _scan_operand(node.condition, True, facts, funcs, methods)
        _scan_expr(node.then_val, facts, funcs, methods, in_closure)
        _scan_expr(node.else_val, facts, funcs, methods, in_closure)
        return

    if isinstance(node, N.Generator):
        # A comprehension clause `for x in <name>`: the comprehension is
        # lowered inline as a loop over the container, which reads it and
        # never keeps it past the clause — the same non-retaining read as a
        # `for` statement over a bare local (see `_scan_stmt`'s ForStmt
        # case). Inside a closure the usual rule (disqualify) still applies.
        if isinstance(node.iterable, N.IdentExpr) and not in_closure:
            pass
        else:
            _scan_expr(node.iterable, facts, funcs, methods, in_closure)
        _scan_expr(node.conditions, facts, funcs, methods, in_closure)
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
            is_ctor = _is_constructor_expr(value) or _is_maybe_fresh_expr(value)
            _sname = _struct_ctor_name(value, facts)
            if _sname != '':
                # The constructor runs user code with `self`: a struct whose
                # `__init__` keeps `self` (registers it, stores it) is not owned
                # by this name.
                _init = facts.structs[_sname].get('__init__')
                if _init is not None and (not _init.params or not _param_is_nonescaping(
                        _init, _init.params[0][0], funcs, methods, facts)):
                    facts.disqualify(name)
            if not is_ctor and isinstance(value, N.IdentExpr):
                # `x = y`: y is now aliased by x — a value with more than
                # one believed owner. Disqualify the ALIASED name (y) too:
                # even if y itself was otherwise a clean single-assignment
                # constructor, x now holds the same pointer.
                facts.disqualify(value.name)
            facts.note_assign(name, is_ctor,
                               _is_constructor_expr(value) or _is_fresh_string_expr(value))
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
            if not facts.allow_return:
                facts.disqualify(stmt.value.name)  # rule 3
        elif isinstance(stmt.value, N.TupleExpr):
            for e in stmt.value.elements:
                if isinstance(e, N.IdentExpr):
                    facts.disqualify(e.name)
        if facts.allow_return and (isinstance(stmt.value, N.IdentExpr)
                                   or _moved_name(stmt.value) != ''):
            # `return name` (or `return name^`, the move that is how Mojo code
            # returns a local) is recorded, not an escape, in a callee scan for
            # analyze_returns_fresh; the generic scan below would disqualify
            # the bare identifier all the same.
            return
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

    if isinstance(stmt, N.ForStmt):
        # `for x in <name>:` READS the container (an index/iterator loop that
        # is torn down when the loop ends) and never keeps it, so a bare
        # local iterable is not an escape — exactly like the receiver of
        # `name[i]` or `name.method()`. Anything else as the iterable
        # (a call result, an expression) is scanned normally.
        if not isinstance(stmt.iterable, N.IdentExpr):
            _scan_expr(stmt.iterable, facts, funcs, methods)
        for b in stmt.body:
            _scan_stmt(b, facts, funcs, methods)
        if stmt.else_body:
            for b in stmt.else_body:
                _scan_stmt(b, facts, funcs, methods)
        return

    for f in dataclasses.fields(stmt):
        val = getattr(stmt, f.name)
        if (f.name == 'condition' and isinstance(stmt, (N.IfStmt, N.WhileStmt))
                and isinstance(val, N.IdentExpr)
                and facts.struct_bound.get(_as_str(val.name), '') == ''):
            continue   # `if s:` / `while s:` reads the value; it does not keep it
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


def _scan_function(fn, funcs, methods, structs=None) -> _FuncFacts:
    """The whole-function escape scan shared by `analyze_function` and
    `analyze_scoped_locals`: every fact the module docstring's rules 1-8
    need, accumulated over `fn`'s body. `facts` is explicitly typed
    `_FuncFacts` for the same self-hosting reason `analyze_function`'s
    docstring gives — an untyped receiver makes `facts.note_assign(...)`
    an auto-stubbed no-op."""
    facts = _FuncFacts()
    facts.structs = structs or {}
    _prescan_struct_binds(fn.body, facts)
    for pname, _ in fn.params:
        # Parameters are out of scope for v0 (see module docstring) —
        # mark them disqualified outright so a same-named local shadow
        # can't accidentally get credited with the parameter's uses.
        facts.disqualify(pname.lstrip('*'))
    for stmt in fn.body:
        _scan_stmt(stmt, facts, funcs, methods)
    return facts


def analyze_function(fn, funcs, methods, structs=None) -> set:
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
    facts = _scan_function(fn, funcs, methods, structs)
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
    the unsafe direction.

    An f-string / t-string is one string leaf here: its `{expr}` interpolations
    are parsed only later, at codegen, so a use of `name` inside one is
    invisible as an identifier. A string containing `{` and the name as a
    substring is therefore counted as an occurrence. Without this, a loop-local
    container that is read after the loop ONLY inside an f-string
    (`print(f"{len(l)}")`) looked unused there, was credited to its loop body
    and freed before that read."""
    if isinstance(node, str):
        if node == name:
            return 1
        if '{' in node and name in node:
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


def analyze_scoped_locals(fn, funcs, methods, whole: set, structs=None) -> set:
    """Block-scoped twin of `analyze_function`: the locals that are a
    destroy candidate for THEIR LOOP BODY rather than for the whole
    function, i.e. exactly the ones `analyze_function` cannot credit
    because a loop may run zero times (so they are never "definitely
    assigned at every function exit") — `whole` is `analyze_function`'s
    result and is excluded, so each candidate is owned at exactly one level.

    A name qualifies iff ALL of:
      - every assignment to it is a container constructor and it never
        escapes (the module docstring's rules 1, 3-8; rule 2, "assigned
        once", is replaced by the next two conditions, applied per loop
        body);
      - each of its assignments is a DIRECT child statement of a distinct
        `for`/`while` body with no `else:`, exactly one per body (so every
        path that reaches the end of the body, or any `break`/`continue`/
        `return` lexically after the declaration, has executed it — no
        definite-assignment analysis is needed because straight-line order
        within one block is the proof). The same name in two sibling loops
        therefore qualifies in both;
      - the name occurs NOWHERE outside those declarations and the rest of
        their bodies (`_count_name` over the whole function equals the sum
        over each `body[idx:]`). This is what makes the free at the end of the
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
            if _decl_name(st) != '' and (_is_constructor_expr(st.value)
                                         or _is_maybe_fresh_expr(st.value)):
                have_ctor_decl = True
    if not have_ctor_decl:
        return out
    facts = _scan_function(fn, funcs, methods, structs)
    _cands = facts.ctor_names()
    for nm in sorted(_cands):
        if nm in whole:
            continue
        decls = 0     # loop bodies that declare `nm` (each exactly once)
        region = 0    # occurrences of `nm` from each declaration to its body's end
        ok = True
        for body in bodies:
            first = -1
            in_body = 0
            for idx in range(len(body)):
                if _decl_name(body[idx]) == nm:
                    in_body += 1
                    if first < 0:
                        first = idx
            if in_body > 1:
                ok = False   # a rebinding inside one block: the first value would leak
            if first >= 0:
                decls += 1
                for j in range(first, len(body)):
                    region += _count_name(body[j], nm)
        # Every assignment must be one of those direct-child declarations, and
        # the name must occur nowhere else: nested same-name declarations
        # count twice (inside the outer region and their own), so they fail
        # the equality below and stay unfreed rather than shadow each other.
        if ok and decls >= 1 and decls == facts.assign_count.get(nm) \
                and _count_name(fn.body, nm) == region:
            out.add(nm)
    return out


def _moved_name(node) -> str:
    """`name^` (a transfer of a local) -> `name`, else ''."""
    if (isinstance(node, N.UnaryOp) and node.op == '^'
            and isinstance(node.operand, N.IdentExpr)):
        return _as_str(node.operand.name)
    return ''


def _collect_returns(node, out: list) -> None:
    """Appends every `return` statement under `node`, not descending into a
    nested `def`/`lambda` (their returns are their own)."""
    if isinstance(node, (list, tuple)):
        for item in node:
            _collect_returns(item, out)
        return
    if not _is_node(node) or isinstance(node, (N.FunctionDef, N.LambdaExpr)):
        return
    if isinstance(node, N.ReturnStmt):
        out.append(node)
        return
    for f in dataclasses.fields(node):
        _collect_returns(getattr(node, f.name), out)


def _has_nested_scope(node) -> bool:
    """True if a nested `def`/`lambda` appears anywhere under `node`: a closure
    could capture a container the function goes on to return."""
    if isinstance(node, (list, tuple)):
        for item in node:
            if _has_nested_scope(item):
                return True
        return False
    if not _is_node(node):
        return False
    if isinstance(node, (N.FunctionDef, N.LambdaExpr)):
        return True
    for f in dataclasses.fields(node):
        if _has_nested_scope(getattr(node, f.name)):
            return True
    return False


# Every name a nested scope under `node` could capture, and whether that set is
# COMPLETE. `(True, names)` means every nested `def` wrote an explicit capture
# list naming specific names, so `names` is the exact capture set and a name
# outside it provably is not captured. `(False, names)` means at least one
# nested scope is UNKNOWN — no capture list at all (so captures are inferred
# from its body), a `{mut}`/`{var}` bare-convention entry (which by definition
# captures whatever the body references), or a `lambda` (whose capture list is
# not parsed into names). Callers must keep their conservative behaviour then.
def _nested_capture_names(node) -> tuple:
    complete = True
    names: set = set()
    if isinstance(node, (list, tuple)):
        for item in node:
            c, n = _nested_capture_names(item)
            complete = complete and c
            names |= n
        return complete, names
    if not _is_node(node):
        return True, names
    if isinstance(node, N.LambdaExpr):
        # A lambda's `captures` field is the raw `{ref}` / `{imm key}` TEXT
        # (LambdaExpr's own docstring), not a name list, so there is nothing to
        # extract and the set stays unknown.
        return False, names
    if isinstance(node, N.FunctionDef):
        if not getattr(node, 'has_capture_list', False):
            return False, names        # captures inferred from the body
        for entry in (getattr(node, 'captures', None) or []):
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                return False, names
            cap_name = entry[0]
            if cap_name is None:
                return False, names    # `{mut}` — captures whatever is referenced
            names.add(_as_str(cap_name))
        # Do NOT descend into the nested body: its own nested scopes are
        # separate closures with their own capture sets, already visited when
        # the walk reached them from the enclosing statement lists.
        return complete, names
    for f in dataclasses.fields(node):
        c, n = _nested_capture_names(getattr(node, f.name))
        complete = complete and c
        names |= n
    return complete, names


def analyze_returns_fresh(fn, funcs, methods, structs=None) -> bool:
    """True iff EVERY call to `fn` provably returns a brand-new container that
    nothing else references, so the caller may own it (and free it).

    Every condition below closes a specific way that a caller's `mojo_*_free`
    of the result would be a crash or a use-after-free:
      - `fn` is a plain function (not async/a generator/decorated: a
        coroutine/generator returns a frame object, a decorator may wrap or
        cache the result) whose nested `def`/`lambda` scopes do NOT capture
        anything it returns. Refined from "contains any nested scope at all":
        a nested `def` with an explicit capture list naming specific names
        cannot capture a returned name outside that list, and `{}` captures
        nothing, so either may be ignored — but a nested scope with no list, a
        bare `{mut}`/`{var}`, or any `lambda` leaves the set unknown and the
        refusal stands;
      - EVERY path returns a value: the body ends in a terminator and no
        `return` is bare. A path that falls off the end or returns None hands
        the caller a NULL pointer, and freeing that crashes;
      - each returned value is a container DISPLAY (`return []`,
        `return [a, b]`), or a bare local that (i) is assigned exactly once,
        from a display, (ii) is definitely assigned on every path to every
        exit (else the return reads an uninitialised pointer) and (iii) never
        escapes any way OTHER than this return — the module docstring's
        rules, with `return name` recorded instead of disqualifying. A
        returned call result is deliberately NOT accepted: whether it is
        fresh is exactly the question being asked.
    """
    if fn.is_async or fn.is_generator or fn.decorators:
        return False
    if not fn.body or not _block_terminates(fn.body):
        return False
    rets = []
    _collect_returns(fn.body, rets)
    if not rets:
        return False
    facts = _FuncFacts()
    facts.allow_return = True
    facts.structs = structs or {}
    _prescan_struct_binds(fn.body, facts)
    for pname, _ in fn.params:
        facts.disqualify(pname.lstrip('*'))
    for stmt in fn.body:
        _scan_stmt(stmt, facts, funcs, methods)
    names = set()
    for r in rets:
        v = r.value
        if v is None:
            return False
        if _is_constructor_expr(v) or _is_fresh_string_expr(v):
            continue
        nm = _moved_name(v)
        if nm == '':
            if not isinstance(v, N.IdentExpr):
                return False
            nm = _as_str(v.name)
        if nm in facts.disqualified:
            return False
        if facts.assign_count.get(nm) != 1 or not facts.all_display.get(nm):
            return False
        names.add(nm)
    if names:
        _da = _definitely_assigned(fn, names)
        for nm in names:
            if nm not in _da:
                return False
    # The closure veto, applied to the NAMES this function actually returns
    # rather than to the mere existence of a nested scope.
    #
    # It used to be an unconditional `or _has_nested_scope(fn.body)`, which
    # refused the whole question for any function containing a `def` or
    # `lambda` anywhere — including one whose closures provably capture
    # nothing from this scope, and including the very common shape of a helper
    # that defines a callback and then returns a container the callback never
    # sees. Each refusal costs the CALLER a free it could have owned
    # (doc/MEMORY.html §3.B, "user functions proven to return fresh
    # containers"), so the veto was buying safety with a real leak.
    #
    # Now: if every nested scope wrote an explicit capture list naming specific
    # names, the capture set is known and a returned name outside it cannot be
    # captured. If any nested scope is unknown — no list (captures inferred from
    # its body), a bare `{mut}`/`{var}` (captures whatever it references), or a
    # `lambda` — the old veto stands in full. `{}` counts as KNOWN and captures
    # nothing, which is what it asserts; `has_capture_list` is what tells the
    # two apart, since both leave `captures == []`.
    _caps_complete, _captured = _nested_capture_names(fn.body)
    if _caps_complete:
        if names & _captured:
            return False
    elif _has_nested_scope(fn.body):
        return False
    return True


_CONSUMING_BUILTINS = ('len', 'print', 'bool')

# String methods whose lowering for a `char *` receiver always returns a NEW
# heap string, never the receiver or a pointer into it (emit_methods.py's
# `_CSTR_METHODS`, `_char_replace_impl`, `mojo_str_join`, `mojo_str_expandtabs`;
# runtime `_str_fresh_copy`). A call to one of these cannot make its result an
# alias of the receiver, so it needs no "consumed on the spot" condition.
_FRESH_RESULT_STR_METHODS = frozenset([
    'upper', 'lower', 'strip', 'lstrip', 'rstrip', 'replace', 'join', 'expandtabs',
])


def receiver_results_consumed(node, name: str, consumed: bool = False) -> bool:
    """True iff EVERY use of `name` as the receiver of a method call under `node`
    has its result consumed on the spot, so it cannot become an alias of `name`.

    Why this exists (strings only; the container rules never needed it): many
    string methods return their own receiver when there is nothing to change
    (`strip`, `lstrip`, `replace`, `ljust`, ...), so `t = s.strip()` may make `t`
    the very same pointer as `s`. If `s` is a local the function owns and frees at
    scope exit, `t` then dangles the moment it outlives that exit. A method call
    on `name` is therefore acceptable only where the result is read immediately:
    a bare statement, an argument of `len`/`print`/`bool`, an operand of a
    read-only operator or comparison, or a condition. Assigned, returned, passed
    to another function, subscripted, or stored — all rejected. A bound method
    taken as a value (`f = s.strip`) captures the receiver and is rejected too.
    (Text inside an f-string is invisible here; an interpolation consumes its
    value immediately, so that is fine.)"""
    if isinstance(node, (list, tuple)):
        for item in node:
            if not receiver_results_consumed(item, name, False):
                return False
        return True
    if not _is_node(node):
        return True
    if isinstance(node, N.CallExpr):
        is_recv = (isinstance(node.func, N.MemberExpr)
                   and isinstance(node.func.obj, N.IdentExpr)
                   and _as_str(node.func.obj.name) == name)
        if (is_recv and not consumed
                and _as_str(node.func.member) not in _FRESH_RESULT_STR_METHODS):
            return False
        arg_consumed = (isinstance(node.func, N.IdentExpr)
                        and _as_str(node.func.name) in _CONSUMING_BUILTINS)
        for a in node.args:
            if not receiver_results_consumed(a, name, arg_consumed):
                return False
        for kw in (node.kwargs or []):
            if not receiver_results_consumed(kw[1], name, arg_consumed):
                return False
        if not is_recv:
            return receiver_results_consumed(node.func, name, False)
        return True
    if isinstance(node, N.MemberExpr):
        if isinstance(node.obj, N.IdentExpr) and _as_str(node.obj.name) == name:
            return False        # `s.method` not in call position: a bound method
        return receiver_results_consumed(node.obj, name, False)
    if isinstance(node, N.ExprStmt):
        return receiver_results_consumed(node.value, name, True)
    if isinstance(node, N.BinaryOp) and node.op in _READ_ONLY_BINOPS:
        return (receiver_results_consumed(node.left, name, True)
                and receiver_results_consumed(node.right, name, True))
    if isinstance(node, N.CompareChain):
        for _op in node.operands:
            if not receiver_results_consumed(_op, name, True):
                return False
        return True
    if isinstance(node, N.UnaryOp) and node.op == 'not':
        return receiver_results_consumed(node.operand, name, True)
    if isinstance(node, (N.IfStmt, N.WhileStmt, N.TernaryExpr)):
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if not receiver_results_consumed(v, name, f.name == 'condition'):
                return False
        return True
    for f in dataclasses.fields(node):
        if not receiver_results_consumed(getattr(node, f.name), name, False):
            return False
    return True



def _name_uses_consumed(node, name: str, consumed: bool = False) -> bool:
    """True iff EVERY use of the identifier `name` under `node` is a read whose
    result cannot outlive the statement it is in: an operand of a read-only
    operator or comparison, a condition, an argument of `len`/`print`/`bool`, an
    index (`x[name]`), a statement of its own, or a receiver whose method result is
    consumed at once (or a method that always returns a new string). Anything else
    — assigned, returned, appended, passed to a call, stored in a tuple/list —
    could keep the pointer alive and is rejected. The sibling of
    `receiver_results_consumed`, which only vets the receiver position."""
    if isinstance(node, (list, tuple)):
        for item in node:
            if not _name_uses_consumed(item, name, False):
                return False
        return True
    if not _is_node(node):
        return True
    if isinstance(node, N.IdentExpr):
        return consumed or _as_str(node.name) != name
    if isinstance(node, N.CallExpr):
        is_recv = (isinstance(node.func, N.MemberExpr)
                   and isinstance(node.func.obj, N.IdentExpr)
                   and _as_str(node.func.obj.name) == name)
        if is_recv and not consumed and _as_str(node.func.member) not in _FRESH_RESULT_STR_METHODS:
            return False
        arg_consumed = (isinstance(node.func, N.IdentExpr)
                        and _as_str(node.func.name) in _CONSUMING_BUILTINS)
        for a in node.args:
            if not _name_uses_consumed(a, name, arg_consumed):
                return False
        for kw in (node.kwargs or []):
            if not _name_uses_consumed(kw[1], name, arg_consumed):
                return False
        if not is_recv:
            return _name_uses_consumed(node.func, name, False)
        return True
    if isinstance(node, N.MemberExpr):
        if isinstance(node.obj, N.IdentExpr) and _as_str(node.obj.name) == name:
            return False        # a bound method taken as a value
        return _name_uses_consumed(node.obj, name, False)
    if isinstance(node, N.SubscriptExpr):
        # the element read out of `name` is `name`'s own memory when `name` is a pair
        return (_name_uses_consumed(node.obj, name, consumed)
                and _name_uses_consumed(node.index, name, True))
    if isinstance(node, N.ExprStmt):
        return _name_uses_consumed(node.value, name, True)
    if isinstance(node, N.BinaryOp) and node.op in _READ_ONLY_BINOPS:
        return (_name_uses_consumed(node.left, name, True)
                and _name_uses_consumed(node.right, name, True))
    if isinstance(node, N.CompareChain):
        for _op in node.operands:
            if not _name_uses_consumed(_op, name, True):
                return False
        return True
    if isinstance(node, N.UnaryOp) and node.op == 'not':
        return _name_uses_consumed(node.operand, name, True)
    if isinstance(node, (N.IfStmt, N.WhileStmt, N.TernaryExpr)):
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if not _name_uses_consumed(v, name, f.name == 'condition'):
                return False
        return True
    for f in dataclasses.fields(node):
        if not _name_uses_consumed(getattr(node, f.name), name, False):
            return False
    return True


def list_elements_owned(fn_body, name: str) -> bool:
    """True iff a list local `name` that owns its own string ELEMENTS
    (`mojo_str_split`/`mojo_str_splitlines`, whose every element is a fresh
    allocation made by the function that built the list) may be torn down with
    the element strings included, without leaving a dangling pointer anywhere.

    The list is the only owner of the allocations, but the PROGRAM can still
    hand an element pointer out, and then the list is no longer the owner of
    that element's lifetime: `kept.append(parts[0])` stores a pointer the free
    then invalidates, and the read comes back as the pointer's bits. So this
    asks a strictly narrower question than the container analyses do — may any
    ELEMENT of `name` be named at all? — and the answer is deliberately the
    smallest one that is still useful:

      - the declaration's own target (`var name = ...`, `name = ...`) is not a
        use;
      - `len(name)`, `repr/str/print/bool/hash/id(name)` read the list's
        length or its contents and hand nothing back;
      - `name` as a statement of its own, and as an operand of `==`/`!=`/`<`/
        `>`/`<=`/`>=` (which compare, and build no new list);
      - `not name` and a condition.

    Everything else is rejected, which is the fail-closed direction: a missed
    free leaks a few bytes, a wrong one is a use-after-free. So `parts[0]`,
    `for p in parts:`, `list(parts)`, `parts[:]`, `parts + other`, `sorted
    (parts)`, `kept.extend(parts)` and every method call on `parts` all keep
    the plain `mojo_list_free` and the pre-existing leak. That is the same
    trade doc/MEMORY.html section 7 records for nested list literals ("Left
    leaking on purpose") and for a dict/set's `key_views_consumed` above; this
    is the LIST-element counterpart, and the leak it does close — the
    ~48 B/iteration of `String("a b c").split(" ")` measured over 100k and
    400k iterations in CODEGEN_call_result_container_never_freed — is
    the `len()`-and-drop shape, which is the common one."""
    return _list_str_uses_ok(fn_body, name)


# Read-only builtins that read a container without handing any of its contents
# back. `str` is here (unlike `_NONRETAINING_BUILTINS`, where it is not): for a
# LIST `str(x)` is `repr(x)`, which builds a new string from the contents; the
# string-identity case that excluded it there is a different question.
_LIST_READ_BUILTINS = frozenset(['len', 'repr', 'str', 'print', 'bool',
                                 'hash', 'id'])
# Comparison operators only. `+`/`*` are absent on purpose: `parts + other`
# builds a list that SHARES the element pointers.
_LIST_SAFE_CMP = frozenset(['==', '!=', '<', '>', '<=', '>='])


def _list_str_uses_ok(node, name: str, seen: bool = False) -> bool:
    """`seen` is True when this subtree has already been accepted by a
    recognised read-only parent (the argument of `len(name)`, an operand of a
    comparison), so a bare `name` inside it is a use that is fine rather than
    one that hands an element out."""
    if isinstance(node, (list, tuple)):
        for item in node:
            if not _list_str_uses_ok(item, name, False):
                return False
        return True
    if not _is_node(node):
        return True
    # The binding itself: the target is not a use of the value.
    if isinstance(node, N.VarDecl) and _as_str(node.name) == name:
        return _list_str_uses_ok(node.value, name, False)
    if (isinstance(node, (N.AssignStmt, N.AugAssignStmt))
            and isinstance(node.target, N.IdentExpr)
            and _as_str(node.target.name) == name):
        return _list_str_uses_ok(node.value, name, False)
    if isinstance(node, N.CallExpr) and isinstance(node.func, N.IdentExpr) \
            and _as_str(node.func.name) in _LIST_READ_BUILTINS:
        for a in node.args:
            if not _list_str_uses_ok(a, name, True):
                return False
        for kw in (node.kwargs or []):
            if not _list_str_uses_ok(kw[1], name, True):
                return False
        return True
    if isinstance(node, N.ExprStmt):
        return _list_str_uses_ok(node.value, name, True)
    if isinstance(node, N.BinaryOp) and node.op in _LIST_SAFE_CMP:
        return (_list_str_uses_ok(node.left, name, True)
                and _list_str_uses_ok(node.right, name, False))
    if isinstance(node, N.CompareChain):
        for o in node.operands:
            if not _list_str_uses_ok(o, name, True):
                return False
        for op in (node.ops or []):
            if op not in _LIST_SAFE_CMP:
                return False
        return True
    if isinstance(node, N.UnaryOp) and node.op == 'not':
        return _list_str_uses_ok(node.operand, name, True)
    if isinstance(node, (N.IfStmt, N.WhileStmt, N.TernaryExpr)):
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if not _list_str_uses_ok(v, name, f.name == 'condition'):
                return False
        return True
    if isinstance(node, N.IdentExpr):
        return seen or _as_str(node.name) != name
    for f in dataclasses.fields(node):
        v = getattr(node, f.name)
        if v is None:
            continue
        if not _list_str_uses_ok(v, name, False):
            return False
    return True


def lambda_value_owned(fn_body, name: str) -> bool:
    """True iff the callable local `name` may be freed at scope exit TOGETHER
    with the environment it captured, i.e. nothing can name it except the call
    it is written for.

    A capturing lambda's value is a `MojoBoundMethod` wrapping a `malloc`'d
    environment: two allocations and a `_reg_bound_method` entry per creation,
    ~74 B/iteration measured over 100k and 400k iterations
    (bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md). That object dies
    with the scope that made it only if the scope is its last holder, and
    "holder" here is narrow: the ONLY acceptable mention of `name` after its
    binding is as the CALLEE of a call (`f(x)`). Everything else can keep the
    pointer past the free —
      `g = f`, `return f`, `kept.append(f)`, `f` in a list/tuple display,
      `f` captured by another `lambda`/`def`, `f.attr`, `f[0]`, or a call
      through a container it was put into — and is rejected.

    The binding itself must be a `lambda` expression and there must be exactly
    one: a second assignment is a second value with an independent lifetime,
    and a non-lambda RHS is some other callable whose allocation the free does
    not know the shape of (a bare function pointer, or a bound method whose
    `self` is somebody's receiver — that one is `mojo_bound_method_free`, not
    this, see runtime/fire_runtime.c).

    Deliberately separate from the container candidate analysis rather than
    folded into it: a function containing a `lambda` is excluded from that one
    outright (`_is_free_eligible_function`), because inside a closure the
    receiver rules that make `d[k]`/`d.x`/`d[a:b]`/`for x in d` safe are not
    safe, and lifting that exclusion is a separate piece of work. This rule
    asks nothing about containers, so it holds on a body the container analysis
    refuses to look at."""
    return _lambda_uses_ok(fn_body, name)


def nested_def_env_owned(fn_body, name: str) -> bool:
    """True iff the environment `_alloc_<name>_env()` allocated for a nested
    `def name` may be freed when the enclosing function returns.

    The same rule `lambda_value_owned` applies to a capturing lambda's value,
    and for the same reason: the environment dies with the scope that made it
    only if that scope is its last holder, and "holder" is narrow — the ONLY
    acceptable mention of `name` is as the CALLEE of a call. `return inner(1)
    + inner(2)` (one env, two calls, the shape
    bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md's OPEN 1 measured
    at +16 B/iteration) qualifies; `g = inner`, `kept.append(inner)`,
    `return inner`, `inner.attr` and a mention inside any nested
    `lambda`/`def` (whose own environment can outlive this scope) do not.

    What is DIFFERENT from a capturing lambda, and why this is its own name
    rather than a second rule:

    * a capturing lambda's value is a `MojoBoundMethod *` PLUS the env, one
      allocation unit freed by `mojo_closure_free` (which also drops the
      `_reg_bound_method` entry — freeing the object without it makes
      `mojo_is_bound_method` report whatever the allocator hands back next);
    * a nested `def` produces NO bound method at all. Its call sites are
      DIRECT (`helper_inner (_env_inner, 1)`), the env var is
      function-scoped, and the value is a plain `malloc` block — so the
      teardown is a bare `free` and the unwind entry is `MOJO_CLEANUP_PTR` /
      `mojo_cleanup_push_ptr` ("a plain malloc/calloc block: a struct
      instance"). `mojo_closure_free` would be WRONG here: it would treat a
      `helper_inner_env *` as a `MojoBoundMethod` and free two words of it.

    So it is the same question with a different teardown, which is exactly
    what `lambda_value_owned`'s own docstring means by "This rule asks
    nothing about containers, so it holds on a body the container analysis
    refuses to look at" — this one asks nothing about a callable VALUE,
    because there is none.
    """
    return _lambda_uses_ok(fn_body, name)


def _lambda_uses_ok(node, name: str, as_callee: bool = False) -> bool:
    if isinstance(node, (list, tuple)):
        for item in node:
            if not _lambda_uses_ok(item, name, False):
                return False
        return True
    if not _is_node(node):
        return True
    if isinstance(node, N.VarDecl) and _as_str(node.name) == name:
        return isinstance(node.value, N.LambdaExpr)
    if (isinstance(node, (N.AssignStmt, N.AugAssignStmt))
            and isinstance(node.target, N.IdentExpr)
            and _as_str(node.target.name) == name):
        return False        # a rebinding: a second value, independently owned
    if isinstance(node, N.CallExpr):
        if not _lambda_uses_ok(node.func, name, True):
            return False
        for a in node.args:
            if not _lambda_uses_ok(a, name, False):
                return False
        for kw in (node.kwargs or []):
            if not _lambda_uses_ok(kw[1], name, False):
                return False
        return True
    if isinstance(node, N.IdentExpr):
        return as_callee or _as_str(node.name) != name
    if isinstance(node, (N.FunctionDef, N.LambdaExpr)):
        # A nested scope that MENTIONS `name` captures it into its environment,
        # and that environment can outlive this scope — the exact hazard this
        # rule exists to prevent. Reject on the mention, whatever shape it has
        # inside (a call position included).
        return not _mentions_name(node, name)
    for f in dataclasses.fields(node):
        v = getattr(node, f.name)
        if v is None:
            continue
        if not _lambda_uses_ok(v, name, False):
            return False
    return True


def _mentions_name(node, name: str) -> bool:
    if isinstance(node, (list, tuple)):
        for item in node:
            if _mentions_name(item, name):
                return True
        return False
    if not _is_node(node):
        return False
    if isinstance(node, N.IdentExpr):
        return _as_str(node.name) == name
    for f in dataclasses.fields(node):
        if _mentions_name(getattr(node, f.name), name):
            return True
    return False


def _key_view_source(it, name: str) -> str:
    """'keys' when the iterable `it` walks `name`'s keys/elements (`name` or
    `name.keys()`), 'items' for `name.items()`, else ''."""
    if isinstance(it, N.IdentExpr) and _as_str(it.name) == name:
        return 'keys'
    if (isinstance(it, N.CallExpr) and isinstance(it.func, N.MemberExpr)
            and isinstance(it.func.obj, N.IdentExpr) and _as_str(it.func.obj.name) == name
            and not it.args and _as_str(it.func.member) in ('keys', 'items')):
        return _as_str(it.func.member)
    return ''


def _target_key_names(target, source: str) -> list:
    """The loop variables that hold a KEY view of the dict (all of them for
    `keys`; the first slot, or a lone pair variable, for `items`)."""
    t = _as_str(target).strip()
    if t.startswith('(') and t.endswith(')'):
        t = t[1:-1]
    names = [p.strip() for p in t.split(',') if p.strip()]
    if source == 'items' and len(names) > 1:
        return names[:1]
    return names


def key_views_consumed(fn_body, name: str) -> bool:
    """True iff a dict or set local `name` may be freed at scope exit without
    leaving a dangling key. A dict OWNS its key strings and a set OWNS its string
    elements: `for k in d`, `d.keys()` and `d.items()` hand out pointers into
    them, so a loop variable that is appended, returned or stored would outlive
    the free. Every such variable must therefore be `_name_uses_consumed`
    throughout the function; iterating `name` any other way (a comprehension,
    `.keys()` outside a `for`, `.popitem()`) is rejected outright."""
    keyvars = []
    if not _collect_key_views(fn_body, name, keyvars):
        return False
    for kv in keyvars:
        if not _name_uses_consumed(fn_body, kv, False):
            return False
    return True


def _collect_key_views(node, name: str, keyvars: list) -> bool:
    if isinstance(node, (list, tuple)):
        for item in node:
            if not _collect_key_views(item, name, keyvars):
                return False
        return True
    if not _is_node(node):
        return True
    if isinstance(node, N.ForStmt):
        src = _key_view_source(node.iterable, name)
        if src != '':
            for kn in _target_key_names(node.target, src):
                keyvars.append(kn)
            return (_collect_key_views(node.body, name, keyvars)
                    and _collect_key_views(node.else_body, name, keyvars))
    if isinstance(node, N.Generator) and _key_view_source(node.iterable, name) != '':
        return False
    if (isinstance(node, N.CallExpr) and isinstance(node.func, N.MemberExpr)
            and isinstance(node.func.obj, N.IdentExpr) and _as_str(node.func.obj.name) == name
            and _as_str(node.func.member) in ('keys', 'items', 'popitem', '__iter__')):
        return False        # a key view outside a `for` header
    for f in dataclasses.fields(node):
        if not _collect_key_views(getattr(node, f.name), name, keyvars):
            return False
    return True


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
