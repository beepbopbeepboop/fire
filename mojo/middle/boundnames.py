"""Shared local bound-name collection for all codegen backends.

ONE copy of the name-binding walk: assignment targets, with-aliases,
control-flow bodies. GIMPLE (`_locally_bound_names`) and the formal
arm64 path (`formal.arm64_codegen._collect_var_names`) both call this;
future architecture backends must too. Do not fork a private walk.

Light module: imports only `fire_compiler` (no `gimple_codegen`, no
`mojo.middle.types` star-imports) so formal can use it without pulling
the C/GIMPLE emission stack — same constraint as `mojo.middle.closures`.
"""
from __future__ import annotations

from fire_compiler import (
    AssignStmt, AugAssignStmt, Comprehension, ComptimeForStmt,
    ComptimeIfStmt, ForStmt, GlobalStmt,
    NonlocalStmt,
    IdentExpr, IfStmt, ListExpr, MultiAssignStmt, TryStmt, TupleExpr,
    VarDecl, WhileStmt, WithStmt, _as_str,
    _split_top_level_commas as _fc_split_top_level_commas,
    is_tuple_target as _fc_is_tuple_target,
    for_target_slots as _fc_for_target_slots,
)


def _with_item_alias_name(alias) -> str:
    """Bare name a `with ... as <alias>` binds. `WithItem.alias` is typed
    `object`, so the self-hosted backend erases it to int64_t and
    `isinstance(alias, str)` (the stub) reports False for a real `char *` —
    `alias.name` on the bare string then raises AttributeError and silently
    truncates the enclosing function. Check the node case explicitly."""
    if isinstance(alias, IdentExpr):
        return alias.name
    return _as_str(alias)


class _OrderedNames:
    """Set membership + first-assignment iteration order.

    Plain `set` iteration follows string hashes (PYTHONHASHSEED) — formal
    register allocation must be stable across runs, so names are kept in
    an append-ordered list alongside the membership set."""

    __slots__ = ("_set", "_list")

    def __init__(self):
        self._set = set()
        self._list = []

    def add(self, name):
        if name not in self._set:
            self._set.add(name)
            self._list.append(name)

    def update(self, names):
        for n in names:
            self.add(n)

    def __contains__(self, name):
        return name in self._set

    def __iter__(self):
        return iter(self._list)

    def __len__(self):
        return len(self._list)


def _lbn_split_commas(s: str) -> list:
    """Split on top-level commas only (paren depth 0), dropping empty parts.

    A naive `.split(',')` tore nested tuple-target slots into paren-
    carrying fragments (`'(_n, (_mod, _sem))'` → `'_n'`, `'(_mod'`,
    `'_sem)'`). Shared by `_lbn_target_names` and formal's for-target
    emit.

    A thin wrapper over the tree's ONE bracket-aware splitter
    (`fire_compiler._split_top_level_commas`, re-exported here as
    `_fc_split_top_level_commas`) — this used to be a fourth copy with its
    own paren-only depth tracking, which meant it disagreed with the other
    three about bracket characters they each handled differently. Only the
    empty-part drop is local: a trailing comma is the only thing that can
    produce one."""
    return [p for p in _fc_split_top_level_commas(s) if p]


def _lbn_target_names(t) -> list:
    """Hoisted out of `_locally_bound_names` (module-level, not a nested
    closure) — see `_lbn_walk`'s docstring for why.

    Handles every target shape the parser produces: IdentExpr / nested
    TupleExpr|ListExpr nodes, AND the bare-string forms — `ForStmt.target`
    is always a plain `str` (`"i"` or the tuple-target spelling `"(a, b)"`,
    including nested `"(a, (b, c))"`), never an IdentExpr. Missing the str
    case dropped every for-loop variable from the shared bound set (formal
    register allocation then aliased the loop counter onto the X19
    fallback). Returns LEAF names only (nested groups flattened)."""
    if isinstance(t, str):
        name = t.strip()
        if _fc_is_tuple_target(name):
            names = []
            for part in _fc_for_target_slots(name):
                names.extend(_lbn_target_names(part))
            return names
        # Bare comma form: comprehension Generator.target is the parser's
        # `"(a, b)"` spelling WITHOUT the surrounding parens (`"a, b"`).
        if "," in name:
            names = []
            for part in _lbn_split_commas(name):
                names.extend(_lbn_target_names(part))
            if names:
                return names
        if name.startswith("*"):
            # Starred leaf (`*_` / `*rest`): bind the name after `*`.
            name = name[1:].strip()
        return [name] if name else []
    if isinstance(t, IdentExpr):
        return [t.name]
    if isinstance(t, (TupleExpr, ListExpr)):
        names = []
        for e in t.elements:
            names.extend(_lbn_target_names(e))
        return names
    return []


def _lbn_walk(bound: set, global_declared: set, nodes) -> None:
    """Hoisted out of `_locally_bound_names` (module-level, not a nested,
    RECURSIVE closure mutating two captured sets) — a real --dump-full
    fire.py crash (SIGSEGV in mojo_set_update -> mojo_set_add_str ->
    _set_slot_str -> _str_hash, address 0x1) traced here via lldb: the
    lifted-closure env carrying `bound`/`global_declared` across this
    closure's OWN recursive self-calls wasn't reliably allocated/valid at
    every recursion depth. Threading both sets as explicit parameters
    (mutated in place, same as any ordinary Python call) sidesteps the
    lifted-closure machinery entirely.

    `bound` is any object with `.add`/`.update` (a plain `set` for
    GIMPLE membership tests, or `_OrderedNames` when first-assignment
    order matters for register allocation).

    `bound: set` is the annotation that keeps this compiling, and it is
    the SAME shape `global_declared` beside it has always carried — see
    the note on `_lbn_compr_targets` below for the full mechanism, since
    both parameters were miscompiled the same way and for the same
    reason. One caller does pass an `_OrderedNames`:
    `bound_names_in_order` below, which exists for formal's register
    allocator. That caller is INTERPRETED-ONLY — `formal/` is not in
    the self-host closure (`cas.selfhost_closure_is_complete('fire.py')`
    reports it absent), and Python ignores annotations at runtime, so
    the duck-typing `bound_names_in_order` relies on is untouched. The
    only compiled call site, `emit_resolve._locally_bound_names`, passes
    a real `set`."""
    for node in nodes or []:
        if isinstance(node, GlobalStmt):
            global_declared.update(node.names)
        elif isinstance(node, AssignStmt):
            bound.update(_lbn_target_names(node.target))
            _lbn_compr_targets(bound, node.value)
        elif isinstance(node, MultiAssignStmt):
            for t in node.targets:
                bound.update(_lbn_target_names(t))
            _lbn_compr_targets(bound, node.value)
        elif isinstance(node, AugAssignStmt):
            bound.update(_lbn_target_names(node.target))
            _lbn_compr_targets(bound, node.value)
        elif isinstance(node, VarDecl):
            bound.add(node.name)
            _lbn_compr_targets(bound, node.value)
        elif isinstance(node, ForStmt):
            bound.update(_lbn_target_names(node.target))
            _lbn_compr_targets(bound, node.iterable)
            _lbn_walk(bound, global_declared, node.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
        elif isinstance(node, WhileStmt):
            _lbn_compr_targets(bound, node.condition)
            _lbn_walk(bound, global_declared, node.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
        elif isinstance(node, IfStmt):
            _lbn_compr_targets(bound, node.condition)
            for _c, _b in (node.elifs or []):
                _lbn_compr_targets(bound, _c)
            _lbn_walk(bound, global_declared, node.then_body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
            for _, elif_body in (node.elifs or []):
                _lbn_walk(bound, global_declared, elif_body)
        elif isinstance(node, ComptimeIfStmt):
            # A `comptime if` is a DISTINCT NODE (`fire_compiler.ComptimeIfStmt`),
            # not an `IfStmt` with a flag, so the arm above never saw it — and a
            # name bound in a comptime branch got no home at all. The symptom is
            # a refusal that names the allocator rather than the construct:
            #
            #     pick: 'a' has no home: the register allocator collected no home
            #     for it, so the emitter and the allocation walk disagree about
            #     this function's locals
            #
            # measured 2026-10-02, arm64 and x86-64 identically, on
            # `comptime if T == 1: var a = k + 1 ... else: var b = k + 2` and
            # on `std/testing/prop/random.mojo`'s `Rng.rand_scalar`, whose
            # `comptime if dtype == .bool: … elif dtype.is_integral():` arms
            # declare `offset`, `a`, `b`, `diff` and `uint64`.
            #
            # The arms below are the `IfStmt` arm verbatim, because the two nodes
            # have the same four fields (`condition`, `then_body`, `elifs` as
            # `(condition, body)` PAIRS, `else_body`) and one implementation of
            # a shape is the whole reason the shape is not re-derived per node
            # type. Only ONE arm is emitted for a statically decidable condition
            # (`formal/model.py`'s comptime decision), so a name bound in a dead
            # arm is given a register nothing writes — which costs one callee-
            # saved register, and is the same trade `formal/arm64_codegen.py`'s
            # `_allocation_order` already makes for every unused local.
            _lbn_compr_targets(bound, node.condition)
            for _c, _b in (node.elifs or []):
                _lbn_compr_targets(bound, _c)
            _lbn_walk(bound, global_declared, node.then_body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
            for _, elif_body in (node.elifs or []):
                _lbn_walk(bound, global_declared, elif_body)
        elif isinstance(node, ComptimeForStmt):
            # The same gap one loop deeper, and the same shape as the `ForStmt`
            # arm: the loop's own target is a local, and a `VarDecl` in its body
            # is a local. Both were invisible here, for the same reason as above.
            bound.update(_lbn_target_names(node.target))
            _lbn_compr_targets(bound, node.iterable)
            _lbn_walk(bound, global_declared, node.body)
        elif isinstance(node, TryStmt):
            _lbn_walk(bound, global_declared, node.body)
            for h in (node.handlers or []):
                _lbn_walk(bound, global_declared, h.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
            if node.finally_body:
                _lbn_walk(bound, global_declared, node.finally_body)
        elif isinstance(node, WithStmt):
            for item in (node.items or []):
                _al = item.alias
                if _al is not None:
                    # `isinstance(_al, str)` is unreliable in the
                    # self-hosted backend (WithItem.alias is typed
                    # `object` -> int64_t -> the isinstance stub says
                    # False for a real `char *`, then `_al.name` on the
                    # bare string "f" raises AttributeError). Check for
                    # the node case explicitly; everything else is the
                    # string alias.
                    if isinstance(_al, IdentExpr):
                        bound.add(_al.name)
                    else:
                        bound.add(_as_str(_al))
            _lbn_walk(bound, global_declared, node.body)


def _lbn_compr_targets(bound: set, expr) -> None:
    """Bind Comprehension generator targets found anywhere in an expression.

    `bound: set` for the same reason, and with the same blast radius, as
    `_lbn_walk`'s — see its docstring. The mechanism, recorded here
    because it is a general hole rather than a local mistake:

    an unannotated parameter that is used as a METHOD RECEIVER gets its C
    type from the cross-call struct contract in
    `mojo/backend_gimple/module_gen.py` (`_arg_struct_ptr_type` and the
    `_struct_obs` application loop), which observes the types passed at
    the call sites **visible in the same module** and requires them to be
    unanimous. For this function that set is `{_OrderedNames *}` — the
    single `bound_names_in_order` call below — so the contract settled on
    `_OrderedNames *` and emitted

        void _lbn_compr_targets_6b945a (_OrderedNames *, int64_t);
        void _lbn_walk_f9dd53 (_OrderedNames *, MojoSet *, int64_t);

    `bound`'s other caller, `emit_resolve._locally_bound_names`, lives in
    ANOTHER module and so is not in the observation set, and it passes a
    genuine `set` (`bound = set()`). Both the call and the definition
    compiled; the mismatch is two pointer types, so GCC had nothing to
    say. At runtime `_OrderedNames_add` read `self._set` at struct offset
    0 — which on a freshly `mojo_set_new()`ed empty set is the `used`
    counter, i.e. 0 — and handed that to `mojo_set_add_int`, which
    dereferenced NULL. That killed the self-hosted compiler on its FIRST
    statement of a two-line program: `./mojoc --dump-full` on
    `x = 1 / print(x)` crashed in `mojo_set_add_int` with `s == NULL`,
    reached from `_reset_func` -> `GimpleGen._locally_bound_names` ->
    `_lbn_walk` -> `OrderedNames_add`.

    The contract's own `if ann.get(pname) is not None: continue  # respect
    explicit annotation` makes the annotation the supported way to opt
    out, which is why both parameters here carry one. The underlying
    limitation is real and NOT closed by this: a free function's full
    caller set is invisible to the contract (its sibling
    `prefer_refined_param` docstring in the same file says as much), so
    any unannotated struct-typed receiver parameter that is called from
    two modules with two different types will still be miscompiled
    silently.

    Comprehension targets live in expression positions (AssignStmt value,
    ReturnStmt, conditions, …), not as statement-level ForStmt nodes, so
    `_lbn_walk` never sees them. Mirrors `eval_Comprehension`'s
    current-scope leak: `x` in `[x for x in xs]` becomes a real local."""
    if expr is None:
        return
    if isinstance(expr, Comprehension):
        for g in expr.generators or []:
            bound.update(_lbn_target_names(g.target))
            _lbn_compr_targets(bound, g.iterable)
            for c in g.conditions or []:
                _lbn_compr_targets(bound, c)
        _lbn_compr_targets(bound, expr.element)
        if expr.key is not None:
            _lbn_compr_targets(bound, expr.key)
        return
    if isinstance(expr, (str, int, float, bool)):
        return
    # A plain list/tuple container: recurse into each element. Written as a
    # SINGLE flat loop rather than the original list-then-nested-tuple form.
    # The nested `for x in item:` bound `x` to `item`'s element type, and the
    # self-hosted inference mis-typed `item` as `char *` (a str) — so `x`
    # became a plain `char` and its use as an int64_t recursion argument
    # emitted `x = (char *)_mojo_dict_iter_key(...)`, a real
    # `-Wint-conversion` HARD ERROR ("assignment to 'char' from 'char *'")
    # that aborted the compiled build. Flattening removes the misleading
    # inner loop; recursing into a tuple element still descends, because a
    # tuple lands in this same branch on the next call.
    if isinstance(expr, (list, tuple)):
        for _elt in expr:
            _lbn_compr_targets(bound, _elt)
        return
    if hasattr(expr, "__dataclass_fields__"):
        for fname in expr.__dataclass_fields__:
            if fname in ("line", "col"):
                continue
            val = getattr(expr, fname, None)
            _lbn_compr_targets(bound, val)


def bound_names_in_order(body, params=None) -> list:
    """Parameters first (verbatim names), then locals in first-assignment
    order. Used by formal register allocation; GIMPLE's set-based
    `_locally_bound_names` shares the same `_lbn_walk` structure walk."""
    bound = _OrderedNames()
    for pname, _ptype in (params or []):
        bound.add(pname)
    _lbn_walk(bound, set(), body)
    # Expression-position comprehensions (ReturnStmt/ExprStmt and any
    # we missed in nested structures) — full recursive sweep.
    for stmt in body or []:
        _lbn_compr_targets(bound, stmt)
    return list(bound)
