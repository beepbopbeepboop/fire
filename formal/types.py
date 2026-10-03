"""Fixed-width integer type support for the formal arm64 codegen.

Adapted from the toy formal compiler's types.py to work directly on
fire_compiler's AST (the real, complete AST — fire_compiler.py is the
single source of truth).

Int8/Int16/Int32/Int64 and UInt8/UInt16/UInt32/UInt64 wrap modulo 2^w.
Values live in 64-bit registers: signed types sign-extended, unsigned
zero-extended. The unannotated `int` is Int64 — Python and Mojo integers are
signed, and modelling them as unsigned is a silent miscompile rather than a
conservative choice (see `DEFAULT_INT_TYPE`).
"""

from dataclasses import dataclass

import fire_compiler as F
from mojo.middle.boundnames import _with_item_alias_name, _lbn_target_names


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


# The unannotated `int`, i.e. the type of every local, parameter and bare
# literal in a source that does not say. It is SIGNED, because that is what
# the language means: `-3` is negative, not `0xFFFFFFFFFFFFFFFD`, and a
# comparison of a negative quantity against a variable has to come out the way
# Python says it does. It was `IntType(64, False)` — a "legacy" unsigned 64 —
# which made every such comparison wrong, and wrong *silently*: the emitted
# condition code was correct for the type it was given, and the type was a lie
# (`a = 0 - 3; if a < 2:` was false, because the counter read as a huge
# unsigned number). Nothing downstream could notice, which is why the model
# has to agree with the language here rather than with C.
#
# Changing it moves the truncator helpers, the CSET width, the shift mnemonics
# and the comparison mnemonics at once, so it is one line with a full gate
# behind it, not a spot fix.
DEFAULT_INT_TYPE = IntType(64, True)

TYPE_NAMES = {
    "int": IntType(64, True),    # the unannotated type: Python's signed int
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

# Annotations that name a STRING. A formal string is a bare `char *` with no
# header, so it has no IntType and `parse_type_name` deliberately returns None
# for it — but "not an integer" is not the same claim as "is a string", and the
# callers that have to tell (print()'s formatting, above all) need the second
# one. Kept beside TYPE_NAMES so the two lists of "what does this annotation
# mean" cannot drift apart.
#
# The pointer types are deliberately NOT here even though model.
# IDENTITY_TYPE_CTORS lists them as identity conversions: a `Pointer[Int]` is a
# word, not a string, and printing one as `%s` would hand printf an address to
# dereference. An unclassifiable pointer is a refusal; a mislabeled one is a
# segfault with a plausible-looking format.
STRING_TYPE_NAMES = frozenset({"String", "str", "StringLiteral", "StringSlice"})

# Annotations that name a DICT, and the third member of the same vocabulary
# beside the two above. Kept here rather than in `model.py` because the same
# discipline applies: a name that means "a string" and a name that means "a
# dict" are the only two answers a use site can act on differently, and two
# hand-kept lists are two lists that drift.
#
# Why a dict needs its OWN set when `model.BLOB_TYPE_CTORS` already names
# `Dict`: the blob set answers "is this a container at all", which is what
# `declared_type_kind`'s kind is, and a kind cannot say WHICH container —
# `List[Int]`, `Tuple[Int, Int]`, `Set[Int]` and `Dict[String, Int]` are all one
# word on this path and all classify as the bare list prefix. A SUBSCRIPT is
# the one consumer that must tell them apart, because a pair blob indexed with
# a key is a SCAN and a sequence's is an address computation, and asking one
# for the other is a load from a nonsense address rather than a refusal. See
# `model.global_slot_is_dict`, whose own docstring carries the measurement.
DICT_TYPE_NAMES = frozenset({"Dict", "dict"})


# Annotations that name a BOOL, and why they are a SET rather than two rows of
# `TYPE_NAMES`. A Bool's KIND on this path is an integer — a word holding 0 or
# 1 — and `model._kind_of_simple` already says exactly that about a
# `BoolLiteral`, so putting `Bool` in `TYPE_NAMES` would be true and useless:
# every consumer of a kind would read it as the integer it is, and nothing could
# tell a Bool from an Int afterwards. What the dialect `pop.select` lowering
# needs is the narrower question "does this annotation say the word holds 0 or
# 1", because that is what makes `x != 0` the right answer for `x.__mlir_bool__()`
# rather than a `char *`'s "is this address non-zero". One vocabulary, read by
# one predicate, so the two cannot drift apart — and so a Bool is NOT removed
# from `TYPE_NAMES`' half of the story: `declared_type_kind` maps this set to
# `INT_KIND`, which is correct, and this set is the extra fact on top.
#
# `bool` is here beside `Bool` for the same reason `STRING_TYPE_NAMES` carries
# both `String` and `str` and `TYPE_NAMES` carries both `int` and `Int`: they are
# two spellings of one declaration, and a table that recognised one of them is a
# table that answers differently for two spellings of the same program.
BOOL_TYPE_NAMES = frozenset({"Bool", "bool"})


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
    """Promotion: the wider of the two types, and SIGNED if either is.

    C resolves a mixed signed/unsigned pair to unsigned, and this used to copy
    that. It is the wrong rule here, and wrong in the same direction as the
    default above: this language has no unsigned integer type that "wins" a
    mix — `int` is signed, and Python promotes a mixed expression to a signed
    type too. Under the C rule, one `UInt32` in an expression was enough to make
    every operand of it read as unsigned, so a negative value anywhere in the
    expression compared wrong. Signed-wins is also the rule that makes the two
    halves of the model agree: `infer_expr` reports a negative literal as
    signed because a negative value cannot be unsigned, and under C promotion
    that fact was immediately thrown away again by the promotion with its
    unsigned context.

    Flex (None) is neutral, which is what lets a bare literal take the type of
    its context without deciding anything.
    """
    if a is None:
        return b
    if b is None:
        return a
    if a == b:
        return a
    return IntType(max(a.width, b.width), a.signed or b.signed)


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
        # A negated literal is the one case where "no type yet" is not good
        # enough. The bare-literal rule below returns None so a literal takes
        # the type of its context, but a NEGATIVE value cannot be an unsigned
        # one: with both operands typeless, `common_type` is None,
        # `cmp_signed(None)` is False, and the comparison was emitted with
        # unsigned condition codes -- so `if -3 < 2` was false, because -3 is
        # 0xFFFF...FD as a UInt64. Reporting it signed is what Python and Mojo
        # mean, and `common_type` treats None as neutral, so the signedness
        # survives promotion against a typeless literal.
        #
        # Narrow on purpose: `0 - 3` is a BinaryOp and stays typeless, and a
        # negation of a *variable* still recurses, so only a literal negative
        # changes behaviour. Both the CSET value path and the B.cond branch
        # path read this one function, so they cannot disagree.
        if (e.op == "-" and isinstance(e.operand, F.IntLiteral)
                and e.operand.value != 0):
            return IntType(64, True)
        return infer_expr(e.operand, vtypes, call_types)
    if isinstance(e, F.BinaryOp):
        return common_type(infer_expr(e.left, vtypes, call_types),
                           infer_expr(e.right, vtypes, call_types))
    if isinstance(e, F.CompareChain):
        # The chain's result is a boolean; operands share the common type
        # only insofar as each link needs it — report default.
        return DEFAULT_INT_TYPE
    if isinstance(e, F.Comprehension):
        # list/set/dict/genexpr result is a blob pointer (or set/dict blob).
        return DEFAULT_INT_TYPE
    if isinstance(e, F.SliceExpr):
        return DEFAULT_INT_TYPE
    if isinstance(e, F.SetExpr):
        return DEFAULT_INT_TYPE
    if isinstance(e, F.FloatLiteral):
        # formal is int-only; floats truncate toward zero on emit.
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


def uses_typed_model(fn: F.FunctionDef, call_types: dict = None) -> bool:
    """Whether `fn`'s Lean model is the FIXED-WIDTH one rather than the
    word-at-64-bits one.  THE decision, in one place, for both generators.

    **WHAT THE FLAG IS FOR**, since it was a proxy for a long time and the
    proxy's own docstring said so: the fixed-width model (`_expr_go_t` /
    `_stmts_go_t`, with the `t8u`/`t8s`/… truncators) is the only one that
    models a DECLARED width, so it is needed exactly when some type this
    function declares or infers is not the default 64-bit signed word. That is
    the whole question, and this function asks it.

    **IT IS NOT VACUOUS, and it was thought to be for six months.**
    `DEFAULT_INT_TYPE` became signed `IntType(64, True)` (`19bc0dd`), so every
    name whose type is inferred from an `int` literal now RESOLVES to the
    default — which made the old spelling `any(t != DEFAULT_INT_TYPE for t in
    vtypes.values() ∪ {rt})` true for a function only if some type is narrower
    or differently signed. That is not the same as true for nothing:
    `n: UInt8` still resolves to `IntType(8, False)`, so a function that
    declares one still gets the model that can prove things about it.

    Measured over `formal/examples/` on this tree — 45 functions, and this is
    what settled the question the flag's own docstring kept re-asking
    (`bugs/FORMAL_default_int_type_typed_flag_collapse.md`, item 1):

    | source | functions | `uses_typed_model` |
    |---|---|---|
    | no annotation at all | 38 | False |
    | `-> Int` only (`ret42`, `subscript_var`, `wide_recv`) | 3 | False — `Int` IS the default type |
    | `n: UInt8` / `Int8` and the return type (`n8`, `sgt8`, `sle8`, `ug8`) | 4 | **True** |

    So the answer is True for exactly the four functions that declare a
    non-default width, which is what the flag is FOR, and the alternative
    spelling the same document proposed — "compute it from the presence of a
    type ANNOTATION in the source" — would answer identically on every one of
    the 45 (measured: 0 changes), because an unannotated name cannot
    contribute a non-default type and a default-width annotation cannot either.
    It is also the WEAKER rule: it would ignore an INFERRED non-default type,
    which is the half that can move when `infer_expr` learns something. So the
    annotation rule was not adopted, and this predicate is the flag's single
    definition rather than five lines copied into each generator — two copies
    of a decision is two chances for the two architectures to prove different
    programs.

    Forcing it True for everything (the same document's option (b)) was measured
    and is not viable: `test_formal.py` went from 1.2 GB to a 32 GB kill across
    37 processes, because the fixed-width model is the expensive one — which is
    presumably why the flag exists.
    """
    call_types = call_types or {}
    for t in function_var_types(fn, call_types).values():
        if t != DEFAULT_INT_TYPE:
            return True
    return resolve(parse_type_name(getattr(fn, "return_type", None))) \
        != DEFAULT_INT_TYPE


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
            elif isinstance(s, F.MultiAssignStmt):
                for t in s.targets:
                    if isinstance(t, F.IdentExpr):
                        assign_type(t.name, None, s.value)
            elif isinstance(s, F.IfStmt):
                walk(s.then_body)
                for _c, body in (s.elifs or []):
                    walk(body)
                walk(s.else_body)
            elif isinstance(s, F.WhileStmt):
                walk(s.body)
                walk(s.else_body)
            elif isinstance(s, F.ForStmt):
                # Target may be `"i"` or the tuple spelling `"(a, b)"` —
                # split via the shared walk so each slot gets its own type
                # (matches bound_names / register allocation). `for x in`
                # list elements are int64 in formal's current surface.
                for _tn in (_lbn_target_names(s.target)
                            if isinstance(s.target, str) else []):
                    if _tn not in vtypes:
                        rargs = _range_args(s.iterable)
                        if rargs:
                            # Seed with None, NOT DEFAULT_INT_TYPE. The seed
                            # was unsigned, and `common_type` resolves mixed
                            # signed/unsigned to unsigned, so the counter came
                            # out unsigned for EVERY range -- `range(-3, 2)`
                            # emitted an unsigned loop test, compared -3 as
                            # 0xFFFF...FD, and did not run at all. None is
                            # neutral in `common_type`, so a range whose
                            # bounds are all typeless literals still resolves
                            # to the default exactly as before, and a negative
                            # bound now makes the counter signed.
                            rt = None
                            for a in rargs:
                                rt = common_type(
                                    rt, infer_expr(a, vtypes, call_types))
                            vtypes[_tn] = resolve(rt)
                        else:
                            vtypes[_tn] = resolve(DEFAULT_INT_TYPE)
                walk(s.body)
                walk(s.else_body)
            elif isinstance(s, F.WithStmt):
                for it in s.items or []:
                    if it.alias is not None:
                        name = _with_item_alias_name(it.alias)
                        if name not in vtypes:
                            vtypes[name] = resolve(
                                infer_expr(it.expr, vtypes, call_types))
                walk(s.body)
            elif isinstance(s, F.TryStmt):
                walk(s.body)
                for h in (s.handlers or []):
                    walk(h.body)
                walk(s.else_body)
                walk(s.finally_body)

    def walk_compr(expr):
        if expr is None:
            return
        if isinstance(expr, F.Comprehension):
            for g in expr.generators or []:
                for _tn in (_lbn_target_names(g.target)
                            if isinstance(g.target, str) else []):
                    if _tn not in vtypes:
                        vtypes[_tn] = resolve(DEFAULT_INT_TYPE)
                walk_compr(g.iterable)
                for c in g.conditions or []:
                    walk_compr(c)
            walk_compr(expr.element)
            if expr.key is not None:
                walk_compr(expr.key)
            return
        if isinstance(expr, (str, int, float, bool)):
            return
        if hasattr(expr, "__dataclass_fields__"):
            for fname in expr.__dataclass_fields__:
                if fname in ("line", "col"):
                    continue
                val = getattr(expr, fname, None)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, tuple):
                            for x in item:
                                walk_compr(x)
                        else:
                            walk_compr(item)
                elif isinstance(val, tuple):
                    for x in val:
                        walk_compr(x)
                else:
                    walk_compr(val)

    for st in fn.body or []:
        walk_compr(st)
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
        elif isinstance(e, F.SubscriptExpr):
            walk_expr(e.obj)
            walk_expr(e.index)
        elif isinstance(e, F.MemberExpr):
            walk_expr(e.obj)
        elif isinstance(e, F.Comprehension):
            walk_expr(e.element)
            if e.key is not None:
                walk_expr(e.key)
            for g in e.generators or []:
                walk_expr(g.iterable)
                for c in g.conditions or []:
                    walk_expr(c)
        elif isinstance(e, F.SliceExpr):
            walk_expr(e.obj)
            walk_expr(e.start)
            walk_expr(e.stop)
            walk_expr(e.step)

    def walk_stmts(stmts):
        for s in stmts or []:
            if isinstance(s, F.ReturnStmt):
                walk_expr(s.value)
            elif isinstance(s, F.AssignStmt):
                walk_expr(s.value)
            elif isinstance(s, F.MultiAssignStmt):
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
            elif isinstance(s, F.ForStmt):
                walk_expr(s.iterable)
                walk_stmts(s.body)
                walk_stmts(s.else_body)
            elif isinstance(s, F.ReturnStmt):
                walk_expr(s.value)

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
