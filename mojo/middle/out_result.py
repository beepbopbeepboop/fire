"""A pointer-typed `out` result, lowered to an ordinary pointer return.

`def f(out result: Pointer[T, ...])` hands the caller a pointer RESULT, not an
object to fill: the body assigns the pointer and the caller uses the value.
Lowered here to `def f() -> Pointer[T, ...]` whose `result = e` statements are
`return e`, so the definer, its importers and every call site agree on one
shape (no out parameter, so no overload suffix to hash).

Applied in place to a parsed module's top-level statements; idempotent (a
lowered function has no out parameter left). A function this does not handle
(two out parameters, the name read in an expression, a method) is left alone.
"""
import dataclasses

from fire_compiler import AssignStmt, FunctionDef, IdentExpr, ReturnStmt

_POINTER_HEADS = ('Pointer[', 'UnsafePointer[')


def _is_pointer_annotation(t) -> bool:
    return isinstance(t, str) and t.strip().startswith(_POINTER_HEADS)


def _reads_name(node, name: str) -> bool:
    """True when NAME is read anywhere in NODE other than as a plain assignment target."""
    if isinstance(node, IdentExpr):
        return str(node.name) == name
    if isinstance(node, AssignStmt) and isinstance(node.target, IdentExpr) \
            and str(node.target.name) == name:
        return _reads_name(node.value, name)
    if isinstance(node, list):
        return any(_reads_name(x, name) for x in node)
    if isinstance(node, tuple):
        return any(_reads_name(x, name) for x in node)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(_reads_name(getattr(node, f.name), name) for f in dataclasses.fields(node))
    return False


def _to_returns(stmts, name: str):
    """Rewrite `name = e` to `return e` in a statement list, in place."""
    for i, st in enumerate(stmts):
        if isinstance(st, AssignStmt) and isinstance(st.target, IdentExpr) \
                and str(st.target.name) == name:
            stmts[i] = ReturnStmt(value=st.value, line=getattr(st, 'line', 0),
                                  col=getattr(st, 'col', 0))
        elif isinstance(st, list):
            _to_returns(st, name)
        elif dataclasses.is_dataclass(st) and not isinstance(st, type):
            for f in dataclasses.fields(st):
                v = getattr(st, f.name)
                if isinstance(v, list):
                    _to_returns(v, name)
                elif dataclasses.is_dataclass(v) and not isinstance(v, type):
                    _to_returns([v], name)


def _pointee(annotation: str) -> str:
    """`Pointer[T, ...]` / `UnsafePointer[T]` -> `T` (text, no origin/space args)."""
    inner = annotation.split('[', 1)[1].rsplit(']', 1)[0]
    return inner.split(',', 1)[0].strip()


def lower_pointer_out_results(stmts) -> None:
    # A struct value and a pointer to one are the same C pointer here, so a
    # pointee that is a plain struct defined in this module is returned AS that
    # struct: the importer then resolves the name and registers its layout, which
    # a `Pointer[T]` annotation does not trigger. Non-struct pointees keep the
    # pointer annotation.
    _structs = {str(st.name) for st in stmts or []
                if type(st).__name__ == 'StructDef' and not getattr(st, 'bracket_params', None)}
    for fs in stmts or []:
        if not isinstance(fs, FunctionDef) or fs.return_type is not None:
            continue
        convs = fs.param_convs or {}
        outs = [(i, p) for i, p in enumerate(fs.params or [])
                if convs.get(str(p[0])) == 'out']
        if len(outs) != 1:
            continue
        i, (pname, ptype) = outs[0]
        if not _is_pointer_annotation(ptype):
            continue
        name = str(pname)
        if _reads_name(fs.body, name):
            continue
        fs.params = [p for j, p in enumerate(fs.params) if j != i]
        fs.param_convs = {k: v for k, v in convs.items() if k != name}
        _inner = _pointee(ptype)
        fs.return_type = _inner if _inner in _structs else ptype
        _to_returns(fs.body, name)
        # The walk memo caches each node's walk: a rewritten function must be dropped
        # from it, or a later walk sees the pre-rewrite body.
        from mojo.middle.exprtypes import _walk_ast_invalidate
        _walk_ast_invalidate(fs)
