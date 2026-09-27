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
    AssignStmt, AugAssignStmt, Comprehension, ForStmt, GlobalStmt,
    NonlocalStmt,
    IdentExpr, IfStmt, ListExpr, MultiAssignStmt, TryStmt, TupleExpr,
    VarDecl, WhileStmt, WithStmt, _as_str,
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
    """Split on top-level commas only (paren depth 0).

    A naive `.split(',')` tore nested tuple-target slots into paren-
    carrying fragments (`'(_n, (_mod, _sem))'` → `'_n'`, `'(_mod'`,
    `'_sem)'`). Shared by `_lbn_target_names` and formal's for-target
    emit."""
    parts = []
    depth = 0
    cur = []
    for ch in s:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            part = "".join(cur).strip()
            if part:
                parts.append(part)
            cur = []
        else:
            cur.append(ch)
    part = "".join(cur).strip()
    if part:
        parts.append(part)
    return parts


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
        if name.startswith("(") and name.endswith(")"):
            names = []
            for part in _lbn_split_commas(name[1:-1]):
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


def _lbn_walk(bound, global_declared: set, nodes) -> None:
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
    order matters for register allocation)."""
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


def _lbn_compr_targets(bound, expr) -> None:
    """Bind Comprehension generator targets found anywhere in an expression.

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
