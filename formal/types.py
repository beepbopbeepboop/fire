"""Fixed-width integer type support for the formal arm64 codegen.

Adapted from the toy formal compiler's types.py to work directly on
fire_compiler's AST (the real, complete AST — fire_compiler.py is the
single source of truth).

Int8/Int16/Int32/Int64 and UInt8/UInt16/UInt32/UInt64 wrap modulo 2^w.
Values live in 64-bit registers: signed types sign-extended, unsigned
zero-extended. The unannotated `int` is UInt64.
"""

from dataclasses import dataclass

import fire_compiler as F


@dataclass(frozen=True)
class IntType:
    """A fixed-width integer type (wrapping arithmetic).

    width: 8, 16, 32 or 64.  signed: True for IntN, False for UIntN.
    The legacy unannotated `int` is UInt64.
    """
    width: int
    signed: bool

    @property
    def name(self) -> str:
        return ("Int" if self.signed else "UInt") + str(self.width)


DEFAULT_INT_TYPE = IntType(64, False)

TYPE_NAMES = {
    "int": IntType(64, False),   # legacy unannotated type (unsigned 64-bit)
    "Int": IntType(64, True),    # Mojo `Int` = Int64
    "Int8": IntType(8, True),
    "Int16": IntType(16, True),
    "Int32": IntType(32, True),
    "Int64": IntType(64, True),
    "UInt8": IntType(8, False),
    "UInt16": IntType(16, False),
    "UInt32": IntType(32, False),
    "UInt64": IntType(64, False),
}


def parse_type_name(s):
    """Parse a fire_compiler type-annotation string; None if unknown/None."""
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    return TYPE_NAMES.get(s)


def resolve(t) -> IntType:
    """Map a flexible (None) type to the default."""
    return t if t is not None else DEFAULT_INT_TYPE


def common_type(a, b):
    """C-style promotion: the wider of the two types; signed only when both
    are signed (mixed signed/unsigned is unsigned).  Flex (None) is neutral."""
    if a is None:
        return b
    if b is None:
        return a
    if a == b:
        return a
    return IntType(max(a.width, b.width), a.signed and b.signed)


def infer_expr(e, vtypes: dict, call_types: dict = None):
    """Infer the type of a fire_compiler expression.

    Returns an IntType, or None for a flexible expression (a bare literal
    that takes the type of its context)."""
    if isinstance(e, F.IdentExpr):
        return vtypes.get(e.name) or DEFAULT_INT_TYPE
    if isinstance(e, (F.IntLiteral, F.BoolLiteral)):
        return None
    if isinstance(e, F.StringLiteral):
        # A string expression evaluates to its address (pointer-sized).
        return DEFAULT_INT_TYPE
    if isinstance(e, F.UnaryOp):
        return infer_expr(e.operand, vtypes, call_types)
    if isinstance(e, F.BinaryOp):
        return common_type(infer_expr(e.left, vtypes, call_types),
                           infer_expr(e.right, vtypes, call_types))
    if isinstance(e, F.CompareChain):
        # The chain's result is a boolean; operands share the common type
        # only insofar as each link needs it — report default.
        return DEFAULT_INT_TYPE
    if isinstance(e, F.CallExpr):
        if isinstance(e.func, F.IdentExpr):
            return (call_types or {}).get(e.func.name) or DEFAULT_INT_TYPE
        return DEFAULT_INT_TYPE
    return DEFAULT_INT_TYPE


def _range_args(iterable):
    """range(...) arguments from a fire ForStmt iterable, or None if the
    iterable is not a plain range() call."""
    if (isinstance(iterable, F.CallExpr)
            and isinstance(iterable.func, F.IdentExpr)
            and iterable.func.name == "range"):
        return list(iterable.args)
    return None


def function_var_types(fn: F.FunctionDef, call_types: dict = None) -> dict:
    """Type of every variable in a function: parameters first, then locals in
    first-assignment order (matching the codegen register allocation)."""
    vtypes: dict = {}
    for pname, ptype in fn.params:
        vtypes[pname] = parse_type_name(ptype) or DEFAULT_INT_TYPE

    def assign_type(name, ann, value_expr):
        if name in vtypes:
            return
        t = parse_type_name(ann)
        if t is None and ann is not None:
            # Non-int annotation (or opaque type string) — fall back to
            # inference from the value rather than failing the whole walk.
            t = infer_expr(value_expr, vtypes, call_types) if value_expr is not None else None
        elif t is None and value_expr is not None:
            t = infer_expr(value_expr, vtypes, call_types)
        vtypes[name] = resolve(t)

    def walk(stmts):
        for s in stmts or []:
            if isinstance(s, F.AssignStmt):
                if isinstance(s.target, F.IdentExpr):
                    assign_type(s.target.name, s.type_ann, s.value)
            elif isinstance(s, F.VarDecl):
                assign_type(s.name, s.type_ann, s.value)
            elif isinstance(s, F.AugAssignStmt):
                if isinstance(s.target, F.IdentExpr) and s.target.name not in vtypes:
                    vtypes[s.target.name] = resolve(
                        infer_expr(s.value, vtypes, call_types))
            elif isinstance(s, F.IfStmt):
                walk(s.then_body)
                for _c, body in (s.elifs or []):
                    walk(body)
                walk(s.else_body)
            elif isinstance(s, F.WhileStmt):
                walk(s.body)
                walk(s.else_body)
            elif isinstance(s, F.ForStmt):
                if isinstance(s.target, str) and s.target not in vtypes:
                    rt = DEFAULT_INT_TYPE
                    rargs = _range_args(s.iterable) or []
                    for a in rargs:
                        rt = common_type(rt, infer_expr(a, vtypes, call_types))
                    vtypes[s.target] = resolve(rt)
                walk(s.body)
                walk(s.else_body)

    walk(fn.body)
    return vtypes


def fits_type(t: IntType, value: int) -> bool:
    """Whether a literal value fits exactly in type t (no wrapping)."""
    t = resolve(t)
    if t.width == 64:
        return True  # 64-bit literals wrap, never rejected
    if t.signed:
        return -(2 ** (t.width - 1)) <= value < 2 ** (t.width - 1)
    return 0 <= value < 2 ** t.width


def mask_of(t: IntType) -> int:
    return (1 << t.width) - 1


def needs_trunc(t) -> bool:
    """Whether a result of type t must be truncated after 64-bit arithmetic."""
    return t is not None and t.width < 64


def cmp_signed(t) -> bool:
    """Whether comparisons of type t use signed condition codes."""
    return t is not None and t.signed


def used_narrow_types(fn: F.FunctionDef) -> set:
    """The set of <64-bit types used by a function's parameters, locals and
    expressions (for emitting only the truncator helpers that are needed)."""
    call_types = None
    vtypes = function_var_types(fn, call_types)
    used = {t for t in vtypes.values() if t.width < 64}

    def walk_expr(e):
        if isinstance(e, F.BinaryOp):
            t = infer_expr(e, vtypes, call_types)
            if t is not None and t.width < 64:
                used.add(t)
            walk_expr(e.left)
            walk_expr(e.right)
        elif isinstance(e, F.UnaryOp):
            walk_expr(e.operand)
        elif isinstance(e, F.CallExpr):
            for a in e.args:
                walk_expr(a)

    def walk_stmts(stmts):
        for s in stmts or []:
            if isinstance(s, F.ReturnStmt):
                walk_expr(s.value)
            elif isinstance(s, F.AssignStmt):
                walk_expr(s.value)
            elif isinstance(s, F.VarDecl):
                walk_expr(s.value)
            elif isinstance(s, F.ExprStmt):
                walk_expr(s.value)
            elif isinstance(s, F.IfStmt):
                walk_expr(s.condition)
                walk_stmts(s.then_body)
                for _c, body in (s.elifs or []):
                    walk_expr(_c)
                    walk_stmts(body)
                walk_stmts(s.else_body)
            elif isinstance(s, F.WhileStmt):
                walk_expr(s.condition)
                walk_stmts(s.body)
                walk_stmts(s.else_body)

    walk_stmts(fn.body)
    return used


def lean_trunc_name(t) -> str | None:
    """Lean helper name for the truncator of type t (None for 64-bit)."""
    if not needs_trunc(t):
        return None
    return f"t{t.width}{'s' if t.signed else 'u'}"


def lean_trunc_defs(types: set) -> str:
    """Emit the truncator helper defs for the given set of IntTypes.

    t{w}u: zero-extend (mask the low w bits of a 64-bit value).
    t{w}s: sign-extend the low w bits of a 64-bit value."""
    lines = []
    for w in sorted({t.width for t in types if t.width < 64}):
        mask = mask_of(IntType(w, False))
        inv = (1 << 64) - (1 << w)
        lines.append(
            f"def t{w}u (x : UInt64) : UInt64 := x &&& 0x{mask:x}\n")
        lines.append(
            f"def t{w}s (x : UInt64) : UInt64 :=\n"
            f"  let b := x &&& 0x{mask:x}\n"
            f"  if (b >>> {w - 1}) = 1 then b ||| (0x{inv:016x} : UInt64) else b\n")
    return "\n".join(lines)
