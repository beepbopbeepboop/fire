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

4. `Alias[args]` over a GENERIC `comptime Alias[params]: T = <rhs>` binds
   `params` to `args` and folds `<rhs>` at the APPLICATION (see
   `_eval_alias_application`). Such an alias has no value of its own — its
   RHS names its parameters — so recording only a folded value left it an
   undeclared name, and a `comptime if` over it took rule 2's runtime branch
   on that name's zero placeholder (a NULL boxed-list read for
   `std.traits.IsTriviallyDeinitable[T]`). The declaration is kept in the
   binding table (a `ComptimeVarStmt` with `comptime_params`) by both the
   importing walk and the module prefold.
"""


import sys
import platform

import fire_compiler as _fc
from mojo.middle.builtin_types import (
    TRIVIAL_REGISTER_PASSABLE_TRAITS,
    TRIVIAL_REGISTER_PASSABLE_TYPES,
)

# The AST node classes are imported by name (the way every other module in
# mojo/middle/ does it) rather than off a namespace, so `isinstance` checks
# here are the same checks the backends make.
BoolLiteral = _fc.BoolLiteral
IntLiteral = _fc.IntLiteral
FloatLiteral = _fc.FloatLiteral
StringLiteral = _fc.StringLiteral
IdentExpr = _fc.IdentExpr
MemberExpr = _fc.MemberExpr
UnaryOp = _fc.UnaryOp
BinaryOp = _fc.BinaryOp
CompareChain = _fc.CompareChain
CallExpr = _fc.CallExpr
TupleExpr = getattr(_fc, 'TupleExpr', None)
ListExpr = getattr(_fc, 'ListExpr', None)
DictExpr = getattr(_fc, 'DictExpr', None)
DottedLiteral = getattr(_fc, 'DottedLiteral', None)
SubscriptExpr = getattr(_fc, 'SubscriptExpr', None)
SliceExpr = getattr(_fc, 'SliceExpr', None)
Comprehension = getattr(_fc, 'Comprehension', None)
ComptimeVarStmt = _fc.ComptimeVarStmt
# Static ComptimeVarStmt view of a boxed handle, for the same reason
# fire_compiler._as_comptimevar_node exists: a field read straight off a
# boxed value lowers to runtime dispatch, which does not reliably carry this
# struct (it turned `s.target` into the pointer's decimal address elsewhere).
_as_comptimevar_node = _fc._as_comptimevar_node

# Most elements a folded list comprehension may produce. Past this the value is
# not folded (None), so the comptime-for it feeds falls back to the runtime
# loop, which is the right answer for a comprehension that large anyway.
COMPREHENSION_FOLD_CAP = 4096

# Marker key in the binding table that an in-progress generic-alias expansion
# inserts, so a self-referential alias body cannot re-enter forever. A NUL
# prefix cannot collide with a source identifier or any other binding key.
_ALIAS_EXPANDING_PREFIX = '\x00comptime-alias:'


def _is_dtype_value(v) -> bool:
    """A value that is a DType: a bound `DType.x` / `dtype.x` spelling, or the
    `('DType', x)` marker. A bare `('.', x)` is an ENUM variant reference in
    general and only a DType when the other operand is one."""
    if isinstance(v, str):
        return v.startswith('DType.') or v.startswith('dtype.')
    return isinstance(v, tuple) and len(v) == 2 and v[0] in ('DType', 'dtype')


def _dtype_operand_name(v):
    """The lowercase DType name a comparison operand denotes, or None. Accepts
    the bound DType spellings and the dot-relative `('.', x)` marker, so
    `dtype == .float32` and `dtype == DType.float32` decide the same way."""
    if _is_dtype_value(v):
        return _dtype_name_from_value(v)
    if isinstance(v, tuple) and len(v) == 2 and v[0] == '.' and isinstance(v[1], str):
        return v[1].lower()
    return None


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
    # DType operands compare by NAME. A bound `dtype` is `DType.float32` (or
    # the `('DType', x)` marker) while a dot-relative `.float32` is the
    # `('.', x)` marker; plain equality of the two spellings is always False,
    # which folded `dtype == .float32` to a false branch. Only when both sides
    # resolve to a dtype this evaluator KNOWS is the answer decided; an
    # unknown spelling keeps the ordinary fold below rather than becoming a
    # false one.
    if op in ('==', '!=') and (_is_dtype_value(left) or _is_dtype_value(right)):
        _ln, _rn = _dtype_operand_name(left), _dtype_operand_name(right)
        if _ln in _KNOWN_DTYPE_NAMES and _rn in _KNOWN_DTYPE_NAMES:
            return (_ln == _rn) if op == '==' else (_ln != _rn)
    if op in ('in', 'not in') and _is_dtype_value(left) and isinstance(right, (tuple, list)):
        _ln = _dtype_operand_name(left)
        _names = [_dtype_operand_name(x) for x in right]
        if (_ln in _KNOWN_DTYPE_NAMES
                and all(_n in _KNOWN_DTYPE_NAMES for _n in _names)):
            return (_ln in _names) if op == 'in' else (_ln not in _names)
    if op == '==':  return left == right
    if op == '!=':  return left != right
    if op == '<':   return left < right
    if op == '<=':  return left <= right
    if op == '>':   return left > right
    if op == '>=':  return left >= right
    if op == 'in':
        try:
            return left in right
        except Exception:
            return None
    if op == 'not in':
        try:
            return left not in right
        except Exception:
            return None
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
    included (`True + True` is 2 either way).

    `//` is here because the RUNTIME already lowers it on every compiled path
    (arm64 UDIV/SDIV through `_emit_div_shift_pow`, x86-64 IDIV through
    `_emit_div_mod`, and both spell it as integer division — the same
    instruction sequence `/` gets), and because the reference interpreter
    folds it (`myinterpreter.py`'s binary-op table: `elif op == '//': return
    left // right`). Its absence here was a three-way divergence for one
    source: `comptime c = 7 // 2` printed `3` under `python3 fire.py run`,
    ran at RUNTIME as `3` when the same `//` sat outside the `comptime`, and
    was REFUSED by every compiled backend as "does not fold to a compile-time
    constant". A folder that declines an operator the same build emits for it
    is not being conservative, it is answering a different question from the
    one it is asked.

    The DIVISION-BY-ZERO guard is the other half of the same repair and was
    already missing for `/`: `left // right` with a literal-zero divisor raised
    out of here, out of `eval_const`, and out of the backend — measured, and it
    is a CRASH rather than a refusal, which is the worst of the three answers
    because a crash has no message to act on:

        $ python3 fire.py build --formal --no-prove -o t t.mojo   # comptime c = 1 / 0
        build: division by zero
        ZeroDivisionError: division by zero

    Returning None is what every other unanswerable shape here returns, and
    the caller turns it into `comptime_fold_refusal` — the honest answer,
    naming the construct. `formal/arm64_codegen.py`'s runtime division traps
    the same case at RUN time (`_emit_div_shift_pow`'s div0 arm exits with
    `SHIFT_TRAP_STATUS`), so folding it is not what decides whether the
    program divides by zero; only whether the BUILD does."""
    if op == '+':   return left + right
    if op == '-':   return left - right
    if op == '*':   return left * right
    if op in ('/', '//'):
        if right == 0:
            return None
        return left // right
    if op == 'and': return left and right
    if op == 'or':  return left or right
    return None


def fold_arith_float(op: str, left: float, right: float):
    """Fold one arithmetic operator on two FLOATS, or None.

    The float half of `fold_arith`, and a separate function for the same
    reason `fold_arith` is one: its annotated `int` parameters are what the
    statically compiled backend types the arithmetic on, so a local that can
    hold a `char *` must never reach that body. A caller enters here only
    when an operand really is a float.

    `eval_const_int` can never answer a float expression, so without this
    fold the whole condition was declined and `eval_const_bool_state` read
    the decline as CONST_FALSE: a module-level `if 1.5 * 2:` — and even
    `if not -0.0:` — deleted its then-arm before emission. The operators are
    `eval_const_int`'s own arithmetic set plus `/` (true division on floats),
    and the result is checked to be a real number (`(-2.0) ** 0.5` is a
    `complex`, not a condition) and a raising fold answers None, like every
    other unanswerable shape here.
    """
    try:
        l = float(left)
        r = float(right)
        if op == '+':   return l + r
        if op == '-':   return l - r
        if op == '*':   return l * r
        if op == '/':   return l / r if r else None
        if op == '//':  return l // r if r else None
        if op == '%':   return l % r if r else None
        if op == '**':
            result = l ** r
            return result if isinstance(result, float) else None
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return None


# The unary operators `fold_unary_sign` knows, as a membership set so a caller
# can ask the question without doing the arithmetic on an operator it does not
# have. `formal/model.py`'s `_FOLD_UNARY` is the same three keys spelled as a
# table of the folds themselves; see `fold_unary_sign`.
FOLD_UNARY_OPS = ('-', '+', '~')


def fold_unary_sign(op: str, value: int):
    """Apply the unary SIGN operator `op` to a folded integer, or None.

    The unary half of `fold_arith`'s rule, and a plain if/elif chain rather than
    a dict of lambdas for the reason `compare_op` is one (self-hosting
    gimple_codegen.py could not link a dict-of-lambdas at self-host link time).

    `+` and `~` are here because every backend's RUNTIME already lowers them and
    no compile-time folder did: `comptime c = +3` and `comptime c = ~3` were both
    REFUSED while the emitted code for the same expression is a pass-through
    (`+`) and one MVN/NOT (`~`), so the folder and the code generator answered
    different questions about the same line. `~n` is exact for every integer and
    CPython agrees on the value (`~3` is `-4`).

    This table and `formal/model.py`'s `_FOLD_UNARY` are ONE rule in two
    places, the same way `fold_arith` and `_FOLD_BINOPS` are, and for the same
    reason: the first decides what a function's own `comptime NAME = …` binds,
    the second what a module-level or class-level one binds, and
    `comptime_fold_refusal`'s text speaks for both ("an expression of literals
    and other `comptime` names"). `not` is NOT here — it is a bool-valued
    operator rather than a sign, and it is in `eval_const` alone."""
    if op == '-': return -value
    if op == '+': return value
    if op == '~': return ~value
    return None


# Fixed-width integer constructors `eval_const` can fold: name -> (bits, signed).
_SCALAR_CTOR_BITS = {
    'Int': (64, True), 'Int8': (8, True), 'Int16': (16, True),
    'Int32': (32, True), 'Int64': (64, True),
    'UInt': (64, False), 'UInt8': (8, False), 'UInt16': (16, False),
    'UInt32': (32, False), 'UInt64': (64, False), 'Byte': (8, False),
}


# ── DType compile-time predicates ─────────────────────────────────────────
# `comptime assert` / `constrained` conditions frequently test DType
# properties (e.g. `dtype.is_integral()`). Folding these in the
# backend-neutral evaluator lets both the comptime-assert diagnostic path
# and comptime-if resolution reject provably-false cases, including when
# `dtype` is an instantiated generic parameter bound in `_comptime_vals`.

_DTYPE_INTEGRAL = {
    'int', 'int8', 'int16', 'int32', 'int64', 'int128', 'int256',
    'uint', 'uint8', 'uint16', 'uint32', 'uint64', 'uint128', 'uint256',
    'index',
}
_DTYPE_FLOATING = {
    'float4_e2m1fn', 'float8_e3m4', 'float8_e4m3', 'float8_e4m3fn',
    'float8_e4m3fnuz', 'float8_e4m3b11fnuz',
    'float8_e5m2', 'float8_e5m2fnuz', 'float8_e8m0fnu',
    'bfloat16', 'float16', 'float32', 'float64',
}
_DTYPE_SIGNED_INT = {
    'int', 'int8', 'int16', 'int32', 'int64', 'int128', 'int256',
    'index',
}
_DTYPE_UNSIGNED_INT = {
    'uint', 'uint8', 'uint16', 'uint32', 'uint64', 'uint128', 'uint256',
}
_DTYPE_BOOL = {'bool', 'boolean'}

#: Scalar TYPE spellings that name a DType when they appear where a DType VALUE
#: is expected.  A generic whose parameter is declared `dtype: DType` is
#: instantiated either with a DType value (`DType.float32`) or with the scalar
#: type that value denotes (`Float32`), and monomorphization substitutes the
#: argument TEXTUALLY, so the instantiated body contains `Float32.is_floating_point()`
#: and `Float32 == .float32`.  Without this table those stay unfoldable, the
#: `comptime if` is emitted as a RUNTIME branch with both arms, and an arm that
#: is only type-correct for the dtype it was written for (the float8 bit-tests
#: in std/utils/numerics.mojo calling `to_bits()` on the now-scalar `float`
#: parameter) reaches gcc.  Mapping the spelling back to the dtype value is what
#: lets the branch be decided and the inapplicable arm pruned.
_DTYPE_TYPE_NAMES = {
    'Bool': 'bool', 'Boolean': 'bool',
    'Int': 'int', 'Int8': 'int8', 'Int16': 'int16', 'Int32': 'int32',
    'Int64': 'int64', 'Int128': 'int128', 'Int256': 'int256',
    'UInt': 'uint', 'UInt8': 'uint8', 'UInt16': 'uint16',
    'UInt32': 'uint32', 'UInt64': 'uint64', 'UInt128': 'uint128',
    'UInt256': 'uint256', 'Index': 'index',
    'Float16': 'float16', 'Float32': 'float32', 'Float64': 'float64',
    'BFloat16': 'bfloat16', 'Float4_E2M1FN': 'float4_e2m1fn',
    'Float8_E3M4': 'float8_e3m4', 'Float8_E4M3': 'float8_e4m3',
    'Float8_E4M3FN': 'float8_e4m3fn',
    'Float8_E4M3FNUZ': 'float8_e4m3fnuz',
    'Float8_E4M3B11FNUZ': 'float8_e4m3b11fnuz',
    'Float8_E5M2': 'float8_e5m2',
    'Float8_E5M2FNUZ': 'float8_e5m2fnuz',
    'Float8_E8M0FNU': 'float8_e8m0fnu',
}

#: The dtype names this evaluator knows how to compare.  Equality of two DType
#: values is by NAME (`Float32` and `DType.float32` and `.float32` are one
#: dtype), so a value is only compared this way when both sides resolve to one
#: of these; an unknown spelling keeps the old "not foldable" answer rather
#: than becoming a false one.
_KNOWN_DTYPE_NAMES = _DTYPE_INTEGRAL | _DTYPE_FLOATING | _DTYPE_BOOL


def _dtype_name_from_value(v):
    """Normalize a bound DType value to a lowercase dtype name, or None."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v
        if s.startswith('DType.'):
            s = s[len('DType.'):]
        if s.startswith('dtype.'):
            s = s[len('dtype.'):]
        return s.lower() if s else None
    if isinstance(v, tuple) and len(v) == 2:
        # ('.', name) from DottedLiteral, or ('DType', name) marker.
        if v[0] in ('.', 'DType', 'dtype'):
            return str(v[1]).lower()
    return None


def _dtype_spelling_name(text) -> str | None:
    """The lowercase dtype name a concrete SPELLING denotes, or None.

    A `dtype: DType` bracket parameter is instantiated with any of
    `DType.float32`, `.float32` and `Float32`; a caller that holds only the
    substituted TEXT (the where-clause checker, which is handed
    `{param: rendered_arg}`) cannot tell those apart without this, and a
    spelling it does not recognize must stay unrecognized rather than become
    a wrong `False`."""
    s = str(text).strip()
    if s.startswith('DType.'):
        s = s[len('DType.'):]
    elif s.startswith('dtype.'):
        s = s[len('dtype.'):]
    elif s.startswith('.'):
        s = s[1:]
    s = _DTYPE_TYPE_NAMES.get(s, s).lower()
    return s or None


def _chained_dot_predicate(func_node):
    """`(dtype_spelling, method)` for a chained dot-relative call, else None.

    The parser stores a chained dot-relative reference as ONE `DottedLiteral`
    whose `path` is the WHOLE chain -- `.float64.is_unsigned` arrives as
    `path='float64.is_unsigned'`, not as `MemberExpr(DottedLiteral('float64'),
    'is_unsigned')`. So every consumer that wants to test a DType predicate has
    to split the chain itself; the split lives here once.

    `('.float64', 'is_unsigned')` is returned for that node. A path with no dot,
    or an empty head/method, is not a predicate call and answers None. Resolved
    by class NAME so this module needs no new import from the self-hosted
    parser (same reason `_const_foldable` guards its own DottedLiteral use).
    """
    if type(func_node).__name__ != 'DottedLiteral':
        return None
    p = getattr(func_node, 'path', None)
    if not isinstance(p, str) or '.' not in p:
        return None
    head, method = p.rsplit('.', 1)
    if not head or not method:
        return None
    return '.' + head, method


def dtype_predicate_for_spelling(text, method: str) -> bool | None:
    """Evaluate a DType predicate for a concrete spelling of a dtype.

    `dtype_predicate_for_spelling('.float32', 'is_floating_point')` is True,
    exactly as it is for `DType.float32` and `Float32`: all three are the same
    dtype, and monomorphization substitutes whichever spelling the call site
    wrote. Returns None when the spelling is not a dtype this folder knows, so
    a caller keeps its own conservative answer instead of reading "not a
    known dtype" as "not floating"."""
    name = _dtype_spelling_name(text)
    if name is None or name not in _KNOWN_DTYPE_NAMES:
        return None
    return _eval_dtype_predicate(name, method)


def _resolve_dtype_name(node, bindings, platform=None):
    """Resolve `node` to a DType name string, or None."""
    # A scalar TYPE spelling used as a dtype value: `Float32` (see
    # _DTYPE_TYPE_NAMES — this is the spelling monomorphization substitutes for
    # a `dtype: DType` parameter).
    if isinstance(node, IdentExpr):
        _tn = _DTYPE_TYPE_NAMES.get(node.name)
        if _tn is not None:
            return _tn
    # DType.int32 / dtype.int32
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name in ('DType', 'dtype')):
        return node.member.lower()
    # Bound name (instantiated generic param): `dtype` -> DType.int32
    if isinstance(node, IdentExpr) and node.name in bindings:
        return _dtype_name_from_value(bindings[node.name])
    # Generic member access fallback (e.g. a value that eval_const can fold).
    v = eval_const(node, bindings, platform)
    return _dtype_name_from_value(v)


def _comprehension_iterable_values(iterable, bindings: dict, platform, conforms_to_pred=None):
    """The element values a comprehension generator iterates, or None.

    `range(...)` expands through resolve_for_iterable (the same bounds the
    unroller uses); anything else must fold to a list/tuple/str value."""
    items = resolve_for_iterable(iterable, bindings, {}, COMPREHENSION_FOLD_CAP,
                                 conforms_to_pred=conforms_to_pred)
    if items is None:
        whole = eval_const(iterable, bindings, platform, conforms_to_pred)
        if isinstance(whole, (list, tuple, str)):
            return list(whole)
        return None
    vals = []
    for item in items:
        v = eval_const(item, bindings, platform, conforms_to_pred)
        if v is None:
            return None
        vals.append(v)
    return vals


def _comprehension_run(node, generators: list, env: dict, out: list, platform, conforms_to_pred=None):
    """Depth-first walk of a comprehension's generators, appending each
    element's value to `out`. False when any part is not foldable."""
    if not generators:
        v = eval_const(node.element, env, platform, conforms_to_pred)
        if v is None:
            return False
        if len(out) >= COMPREHENSION_FOLD_CAP:
            return False
        out.append(v)
        return True
    gen = generators[0]
    if not isinstance(gen.target, str):
        return False
    values = _comprehension_iterable_values(gen.iterable, env, platform, conforms_to_pred)
    if values is None:
        return False
    for item in values:
        sub = dict(env)
        sub[gen.target] = item
        keep = True
        for cond in (gen.conditions or []):
            c = eval_const_bool(cond, sub, platform=platform, conforms_to_pred=conforms_to_pred)
            if c is None:
                return False
            if not c:
                keep = False
                break
        if not keep:
            continue
        if not _comprehension_run(node, generators[1:], sub, out, platform, conforms_to_pred):
            return False
    return True


def _fold_comprehension(node, bindings: dict, platform, conforms_to_pred=None):
    """Fold a LIST comprehension (`[i * 2 for i in range(3)]`) to a Python list
    of its element values, or None. Set/dict comprehensions are not folded.

    This is what lets `comptime vals = [...]` bind a value, so a `comptime
    for v in vals` unrolls with `v` bound and a `comptime assert` in it can fire.
    An unknown element or iterable makes the whole comprehension unfoldable,
    and the caller keeps its runtime behaviour."""
    if getattr(node, 'kind', None) != 'list':
        return None
    out = []
    if not _comprehension_run(node, list(node.generators or []),
                              dict(bindings), out, platform, conforms_to_pred):
        return None
    return out


def _eval_subscript(node, bindings: dict, platform=None, conforms_to_pred=None):
    """Fold subscript/slice on a comptime-known value, or None."""
    if SubscriptExpr is not None and isinstance(node, SubscriptExpr):
        base = eval_const(node.obj, bindings, platform, conforms_to_pred)
        if base is None:
            return None
        idx = eval_const(node.index, bindings, platform, conforms_to_pred)
        if idx is None:
            return None
        try:
            return base[idx]
        except Exception:
            return None
    if SliceExpr is not None and isinstance(node, SliceExpr):
        base = eval_const(node.obj, bindings, platform, conforms_to_pred)
        if base is None:
            return None
        start = stop = step = None
        if getattr(node, 'start', None) is not None:
            start = eval_const(node.start, bindings, platform, conforms_to_pred)
            if start is None:
                return None
        if getattr(node, 'stop', None) is not None:
            stop = eval_const(node.stop, bindings, platform, conforms_to_pred)
            if stop is None:
                return None
        if getattr(node, 'step', None) is not None:
            step = eval_const(node.step, bindings, platform, conforms_to_pred)
            if step is None:
                return None
        try:
            return base[slice(start, stop, step)]
        except Exception:
            return None
    return None


def _eval_dtype_predicate(dtype_name, method):
    """Evaluate a DType predicate method on a known dtype name, or None."""
    if dtype_name is None:
        return None
    d = dtype_name.lower()
    if method == 'is_integral':
        return d in _DTYPE_INTEGRAL
    if method == 'is_floating_point':
        return d in _DTYPE_FLOATING
    if method == 'is_signed':
        return d in _DTYPE_SIGNED_INT or d in _DTYPE_FLOATING
    if method == 'is_unsigned':
        return d in _DTYPE_UNSIGNED_INT or d in _DTYPE_BOOL
    if method == 'is_numeric':
        return d in _DTYPE_INTEGRAL or d in _DTYPE_FLOATING
    if method == 'is_bool':
        return d in _DTYPE_BOOL
    if method == 'is_index':
        return d == 'index'
    if method == 'is_float8':
        return d.startswith('float8')
    if method == 'is_half_float':
        return d in ('float16', 'bfloat16')
    return None



def _conforms_to_name(node):
    if node is None:
        return None
    if isinstance(node, IdentExpr):
        return node.name
    if isinstance(node, MemberExpr):
        m = getattr(node, 'member', None)
        if isinstance(m, str):
            return m
        return _conforms_to_name(m)
    if DottedLiteral is not None and isinstance(node, DottedLiteral):
        n = getattr(node, 'name', None)
        if isinstance(n, str):
            return n
        p = getattr(node, 'path', None)
        if isinstance(p, str) and p:
            return p.split('.')[-1]
        return None
    if SubscriptExpr is not None and isinstance(node, SubscriptExpr):
        return _conforms_to_name(getattr(node, 'obj', None))
    if TupleExpr is not None and isinstance(node, TupleExpr):
        elems = getattr(node, 'elements', None) or []
        if len(elems) == 1:
            return _conforms_to_name(elems[0])
        return None
    n = getattr(node, 'name', None)
    if isinstance(n, str):
        return n
    return None


def _conforms_to_bases(struct_name, bases_map, _memo=None):
    if _memo is None:
        _memo = {}
    if struct_name in _memo:
        return _memo[struct_name]
    _memo[struct_name] = set()
    out = set()
    for b in (bases_map.get(struct_name) or []):
        bname = b if isinstance(b, str) else _conforms_to_name(b)
        if not bname:
            continue
        out.add(bname)
        out.update(_conforms_to_bases(bname, bases_map, _memo))
    _memo[struct_name] = out
    return out


# Traits the language derives for a struct from its fields, so their absence
# from a DECLARED-bases map is not evidence against conformance.
_AUTO_DERIVED_TRAITS = frozenset({'Copyable', 'Movable'})


def conforms_to(struct_name, trait_name, bases_map):
    """Whether STRUCT_NAME conforms to TRAIT_NAME, from the DECLARED bases map
    (`{decl: [base, ...]}`): True/False when the map decides it, None when it
    cannot. `_conforms_to_bases` is transitive.

    `Copyable` and `Movable` are derived by the language for a struct whose
    fields all support them, so a struct that does not LIST `Copyable` still
    conforms: the map records declarations, not derivations. Proving a negative
    from the empty list made a plain struct element satisfy neither — that is
    how `LinkedList[CopyCountedStruct]()`'s
    `comptime assert conforms_to(Self.ElementType, Copyable)` in the stdlib
    failed to compile (2026-11-12), while the same struct is copied freely
    everywhere else in this C backend. For a name the map does not know we
    still answer None: nothing is known about it at all."""
    if not isinstance(struct_name, str) or not isinstance(trait_name, str):
        return None
    # A BUILTIN SCALAR has no source-level struct declaration for the map to
    # read, but the language's answer is not unknown: the compiler synthesizes
    # `TrivialRegisterPassable` for these types, and that trait derives
    # `Deinitable`, `ImplicitlyCopyable -> Copyable -> Movable` and
    # `RegisterPassable` (std/builtin/value.mojo). This is what lets
    # `IsTriviallyDeinitable[Int]` — a `conforms_to(T, ...) or (...)` alias —
    # fold at an instantiation with `T = Int` instead of staying CONST_UNKNOWN
    # and becoming a runtime branch on a zero word (the imported-generic-alias
    # miscompile: a NULL boxed-list read for `IsTriviallyDeinitable[T]`). Any
    # OTHER trait is still an honest None: nothing here says a scalar does not
    # conform.
    if struct_name in TRIVIAL_REGISTER_PASSABLE_TYPES:
        if trait_name in TRIVIAL_REGISTER_PASSABLE_TRAITS:
            return True
        # A trait THIS module declares and the stdlib does not is one no
        # builtin scalar conforms to: a conformance is written in the
        # conforming type's own base list, and the scalars' lists live in
        # std, which cannot name a trait declared here. A stdlib trait (or a
        # name the stdlib declares twice) may be one a scalar DOES conform to
        # (`Writable`), so that stays an honest None.
        if trait_name in bases_map and trait_name not in _stdlib_trait_index():
            return False
        return None
    if not bases_map:
        return None
    if struct_name not in bases_map:
        return None
    if trait_name in _AUTO_DERIVED_TRAITS:
        return True
    if trait_name not in bases_map:
        known = False
        for bs in bases_map.values():
            for b in (bs or []):
                bname = b if isinstance(b, str) else _conforms_to_name(b)
                if bname == trait_name:
                    known = True
                    break
            if known:
                break
        if not known:
            # The trait is named by no declared base: the declaration map can
            # still decide it by the closed-world walk (every base reached is
            # resolved through the map or the stdlib's trait declarations).
            # `String` conforms to nothing but its declared bases, so
            # `conforms_to(String, TrivialRegisterPassable)` is False.
            return _closed_world_verdict(struct_name, trait_name, bases_map)
    return trait_name in _conforms_to_bases(struct_name, bases_map)


_STDLIB_TRAIT_INDEX = None


def _stdlib_trait_index():
    """`{trait name: (qualified name, [base, ...])}` for every trait the stdlib
    declares, read from the stdlib sources once per process. A stdlib
    `comptime NAME = A & B & C` (an intersection of traits, e.g. `KeyElement`)
    is indexed as a pseudo-trait whose bases are its conjuncts: a type that
    conforms to `NAME` conforms to each of them, so a base list naming it can
    be walked.

    A name declared by more than one stdlib file maps to None: the bare name
    does not then identify one trait, so nothing may be concluded from it.
    The qualified name is the defining file's path under the stdlib root with
    `/` read as `::` and the `.mojo` suffix dropped, which is the spelling the
    real compiler prints (`std/format/__init__.mojo` -> `std::format::__init__`).
    """
    global _STDLIB_TRAIT_INDEX
    if _STDLIB_TRAIT_INDEX is not None:
        return _STDLIB_TRAIT_INDEX
    import os
    import re
    from module_loader import STDLIB_PATH
    index = {}
    header = re.compile(r'^trait\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:\(([^)]*)\))?\s*:',
                        re.MULTILINE)
    intersection = re.compile(r'^comptime\s+([A-Za-z_]\w*)\s*=\s*([^\n]*&[^\n]*)$',
                              re.MULTILINE)
    pending = []

    def _declare(name, qual, bases):
        if name in index:
            index[name] = None
        else:
            index[name] = (qual + '::' + name, bases)
    root = os.path.join(STDLIB_PATH, 'std')
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith('.mojo'):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except OSError:
                continue
            rel = os.path.relpath(path, STDLIB_PATH)[:-len('.mojo')]
            qual = rel.replace(os.sep, '::')
            for m in header.finditer(text):
                bases = []
                for part in (m.group(2) or '').split(','):
                    part = part.split('[')[0].split('.')[-1].strip()
                    if part and re.match(r'^[A-Za-z_]\w*$', part):
                        bases.append(part)
                _declare(m.group(1), qual, bases)
            for m in intersection.finditer(text):
                parts = [p.split('[')[0].split('.')[-1].strip()
                         for p in m.group(2).split('&')]
                if all(re.match(r'^[A-Za-z_]\w*$', p) for p in parts):
                    pending.append((m.group(1), qual, parts))
    # An intersection is a trait alias only when every conjunct is a trait
    # this index already holds (or another accepted alias). A plain integer
    # constant `comptime MASK = FLAG_A & FLAG_B` names no trait and is left out.
    progress = True
    while progress:
        progress = False
        rest = []
        for name, qual, parts in pending:
            if all(index.get(p) is not None for p in parts):
                _declare(name, qual, parts)
                progress = True
            else:
                rest.append((name, qual, parts))
        pending = rest
    _STDLIB_TRAIT_INDEX = index
    return index


def conforms_to_closed(struct_name, trait_name, bases_map, module_name):
    """Whether STRUCT_NAME conforms to TRAIT_NAME, deciding every case the
    closed world allows: returns `(verdict, trait_qualified_name)` where
    verdict is True, False, or None (undecidable).

    `conforms_to` answers None for any trait the module's own declarations
    do not mention, so a struct that never declared a stdlib trait (`Writable`
    on a struct whose bases are `(ImplicitlyCopyable)`) was accepted as
    conforming. Here the struct's transitive bases are walked through the
    module's declarations and then the stdlib's trait declarations. The answer
    is False only when every base reached is itself known, so the walk is
    complete; a single base it cannot resolve (an unknown name, or a bare name
    the stdlib declares twice) makes the verdict None.

    `Copyable` and `Movable` are derived by the language and keep
    `conforms_to`'s True answer.
    """
    if not isinstance(struct_name, str) or not isinstance(trait_name, str) or not bases_map:
        return None, None
    if struct_name not in bases_map:
        return None, None
    if trait_name in bases_map:
        trait_q = f'{module_name}::{trait_name}' if module_name else trait_name
    else:
        index = _stdlib_trait_index()
        entry = index.get(trait_name)
        trait_q = entry[0] if entry else trait_name
    return _closed_world_verdict(struct_name, trait_name, bases_map), trait_q


def _closed_world_verdict(struct_name, trait_name, bases_map):
    """True / False / None for STRUCT_NAME conforming to TRAIT_NAME by walking
    its transitive bases: through BASES_MAP where the module declares a name,
    then the stdlib's trait declarations. False only when every base reached
    is itself resolved (the walk is complete); any unresolved base is None.
    The one walk both `conforms_to` (for a name no declared base mentions) and
    `conforms_to_closed` (diagnostics) answer from."""
    if trait_name in _AUTO_DERIVED_TRAITS:
        return True
    index = _stdlib_trait_index()
    seen = set()
    todo = [struct_name]
    complete = True
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in bases_map:
            bases = [b if isinstance(b, str) else _conforms_to_name(b)
                     for b in (bases_map.get(name) or [])]
        elif name in index and index[name] is not None:
            bases = index[name][1]
        else:
            complete = False
            continue
        for b in bases:
            if not b:
                continue
            if b == trait_name:
                return True
            todo.append(b)
    if not complete:
        return None
    return False


def _conforms_to_operand_name(node, bindings):
    """`_conforms_to_name`, with a bound TYPE spelling resolved first.

    A generic comptime alias's body asks about its own bracket parameter
    (`conforms_to(T, TrivialRegisterPassable)`), and the application site binds
    `T` to the argument's spelling (`Int`). Without this the question is asked
    about the NAME `T`, which no struct declaration answers, so the alias could
    never fold even when its argument's conformance is known. Only a STRING
    binding is a spelling; a bound value (an int/float/bool) leaves the answer
    to `_conforms_to_name`, exactly as before.
    """
    if bindings and isinstance(node, IdentExpr):
        _b = bindings.get(node.name)
        if isinstance(_b, str):
            return _b
    return _conforms_to_name(node)


def _fold_conforms_to_call(node, conforms_to_pred, bindings=None):
    if conforms_to_pred is None:
        return None
    if not isinstance(node, CallExpr) or not isinstance(node.func, IdentExpr):
        return None
    if node.func.name != 'conforms_to':
        return None
    if getattr(node, 'kwargs', None):
        return None
    args = getattr(node, 'args', None) or []
    if len(args) != 2:
        return None
    tname = _conforms_to_operand_name(args[0], bindings)
    trname = _conforms_to_operand_name(args[1], bindings)
    if tname is None or trname is None:
        return None
    try:
        return conforms_to_pred(tname, trname)
    except Exception:
        return None


class ConformancePredicate:
    """The declared facts a comptime fold may ask about a named type, as one
    object: calling it is `conforms_to(struct, trait)` over `bases_map`, and
    `trivially_deinitable(struct)` answers the destructor question
    `downcast[T, Deinitable].__del__is_trivial` reads.

    `declare_missing(name)` supplies the declared bases of a name the map does
    not hold yet (an imported struct, whose home module is parsed only when a
    fold names it); `deinit_trivial(name)` supplies True/False/None. Either is
    optional: without it the answer for that name is undecided, never guessed.
    """

    def __init__(self, bases_map, declare_missing=None, deinit_trivial=None):
        self.bases_map = bases_map
        self._declare_missing = declare_missing
        self._deinit_trivial = deinit_trivial

    def _declare(self, name):
        if (isinstance(name, str) and name not in self.bases_map
                and self._declare_missing is not None):
            declared = self._declare_missing(name)
            if declared is not None:
                self.bases_map[name] = declared

    def __call__(self, struct_name, trait_name):
        self._declare(struct_name)
        return conforms_to(struct_name, trait_name, self.bases_map)

    def trivially_deinitable(self, struct_name):
        if self._deinit_trivial is None or not isinstance(struct_name, str):
            return None
        return self._deinit_trivial(struct_name)


def _downcast_deinitable_operand(node, bindings):
    """The bound type name `T` of `downcast[T, Deinitable]`, or None when
    NODE is not that shape. The shape is what `std/traits/deinitable.mojo`'s
    `IsTriviallyDeinitable` names for its `__del__is_trivial` disjunct."""
    if not (isinstance(node, MemberExpr) and node.member == '__del__is_trivial'):
        return None
    sub = node.obj
    if SubscriptExpr is None or not isinstance(sub, SubscriptExpr):
        return None
    if not (isinstance(sub.obj, IdentExpr) and sub.obj.name == 'downcast'):
        return None
    idx = sub.index
    elems = getattr(idx, 'elements', None) if TupleExpr is not None and isinstance(idx, TupleExpr) else None
    if not elems or len(elems) != 2:
        return None
    trait = _conforms_to_operand_name(elems[1], bindings)
    if trait != 'Deinitable':
        return None
    return _conforms_to_operand_name(elems[0], bindings)


def _fold_del_is_trivial(node, conforms_to_pred, bindings=None):
    """`downcast[T, Deinitable].__del__is_trivial` as True / False, or None when
    the declared facts do not decide it (or the shape is not that read)."""
    tname = _downcast_deinitable_operand(node, bindings)
    if tname is None:
        return None
    triv = getattr(conforms_to_pred, 'trivially_deinitable', None)
    if triv is None:
        return None
    try:
        return triv(tname)
    except Exception:
        return None


def _comptime_alias_template(bindings, obj):
    """The generic `comptime` alias declaration `obj` names, or None.

    A GENERIC comptime alias (`comptime IsTriviallyDeinitable[T: AnyType]:
    Bool = conforms_to(T, ...)`) has no value of its own: its RHS names its
    bracket parameters. The binding table holds the alias's own
    ComptimeVarStmt instead of a value (see `_gmi_prefold_toplevel_comptime`
    and the gimple importer's `from X import NAME` walk), so an APPLICATION
    (`IsTriviallyDeinitable[Int]`) can bind those parameters and fold the
    body. Only a node WITH parameters is an application target; a name that
    binds a real value is not.
    """
    if not bindings or not isinstance(obj, IdentExpr):
        return None
    _b = bindings.get(obj.name)
    if isinstance(_b, ComptimeVarStmt):
        _av = _as_comptimevar_node(_b)
        if _av.comptime_params:
            return _av
    return None


def _alias_type_spelling(node):
    """The TYPE SPELLING a bracket argument denotes (`Int`, `List[Int]`), or
    None. See `_alias_arg_value` for why a type argument must be spelled."""
    if isinstance(node, IdentExpr):
        return node.name
    if isinstance(node, MemberExpr):
        _o = _alias_type_spelling(node.obj)
        if isinstance(_o, str) and isinstance(node.member, str):
            return _o + '.' + node.member
        return None
    if SubscriptExpr is not None and isinstance(node, SubscriptExpr):
        _base = _alias_type_spelling(node.obj)
        if _base is None:
            return None
        _idx = node.index
        if TupleExpr is not None and isinstance(_idx, TupleExpr):
            _elems = _idx.elements or []
        else:
            _elems = [_idx]
        _parts = []
        for _e in _elems:
            _s = _alias_type_spelling(_e)
            if _s is None:
                _v = eval_const(_e, {}, None)
                if isinstance(_v, bool) or isinstance(_v, int):
                    _s = str(_v)
                elif isinstance(_v, str):
                    _s = _v
            if _s is None:
                return None
            _parts.append(_s)
        return _base + '[' + ', '.join(_parts) + ']'
    return None


def _alias_arg_value(node, bindings, platform, conforms_to_pred):
    """The value an alias application's bracket argument binds.

    A VALUE argument (`Alias[3]`, or a bound comptime constant) folds
    normally. A TYPE argument must bind its SPELLING: `Int` folds to the
    `('DType', 'int')` marker, which carries no type name a conformance
    question can consume, so `conforms_to(T, Trait)` in the alias body would
    never see `Int`."""
    v = eval_const(node, bindings, platform, conforms_to_pred)
    if isinstance(v, bool) or isinstance(v, int) or isinstance(v, float):
        return v
    if isinstance(v, str):
        return v
    return _alias_type_spelling(node)


def _eval_alias_application(node, tmpl, bindings, platform, conforms_to_pred):
    """Evaluate `Alias[args]` against the alias declaration `tmpl`: bind its
    bracket parameters to the application's arguments and fold its body, or
    None when the body still cannot be decided (an unknown conformance, a
    nested uninstantiated type, ...).

    A self-referential body (`comptime A[T] = A[T]`) would otherwise re-enter
    forever; an in-progress marker in the cloned binding table stops it (no
    real identifier can be spelled with the NUL prefix)."""
    if isinstance(node.obj, IdentExpr):
        _mark = _ALIAS_EXPANDING_PREFIX + node.obj.name
        if bindings and _mark in bindings:
            return None
    _params = tmpl.comptime_params or []
    _body = tmpl.value
    if _body is None:
        return None
    _idx = node.index
    if TupleExpr is not None and isinstance(_idx, TupleExpr):
        _args = _idx.elements or []
    else:
        _args = [_idx]
    if len(_args) != len(_params):
        return None
    _bound = dict(bindings)
    if isinstance(node.obj, IdentExpr):
        _bound[_ALIAS_EXPANDING_PREFIX + node.obj.name] = True
    for _i, _p in enumerate(_params):
        _av = _alias_arg_value(_args[_i], bindings, platform, conforms_to_pred)
        if _av is None:
            return None
        _bound[_p] = _av
    return eval_const(_body, _bound, platform, conforms_to_pred)


def _eval_interpolated_string(node, bindings: dict, platform=None, conforms_to_pred=None):
    """Evaluate an interpolated (f/t) string literal into a plain string, or
    None if any interpolation expression cannot be comptime-folded. Used for
    compile-time diagnostic messages (comptime assert / constrained)."""
    try:
        from mojo.middle.resolve_shared import (
            _decode_str_literal_text, _parse_fstring_parts)
        from fire_compiler import Parser, py_tokenize
        is_interp = '1' if getattr(node, 'is_interpolated', False) else ''
        inner, is_fstring = _decode_str_literal_text(
            None, getattr(node, 'value', '') or '', is_interp)
        if not is_fstring:
            return None
        parts = _parse_fstring_parts(None, inner)
        out = []
        for part in parts:
            kind = part[0] if isinstance(part, (list, tuple)) else getattr(part, 'kind', '')
            text = part[1] if isinstance(part, (list, tuple)) and len(part) > 1 else getattr(part, 'text', '')
            if kind == 'lit':
                out.append(text if isinstance(text, str) else str(text))
            elif kind == 'expr':
                expr_src = text if isinstance(text, str) else str(text)
                if not expr_src.strip():
                    return None
                try:
                    expr_node = Parser(py_tokenize(expr_src))._parse_expr(0)
                except Exception:
                    return None
                v = eval_const(expr_node, bindings, platform, conforms_to_pred)
                if v is None:
                    return None
                if isinstance(v, bool):
                    out.append('True' if v else 'False')
                else:
                    out.append(str(v))
            else:
                out.append(str(text) if text is not None else '')
        return ''.join(out)
    except Exception:
        return None



_HOST_IS_MACOS = (sys.platform == 'darwin')
_HOST_IS_LINUX = sys.platform.startswith('linux')
_HOST_MACHINE = (platform.machine() or '').lower() if 'platform' in globals() and platform is not None else __import__('platform').machine().lower()
_HOST_IS_X86 = _HOST_MACHINE in ('x86_64', 'amd64', 'x86')
_HOST_IS_ARM = _HOST_MACHINE in ('arm64', 'aarch64', 'armv8')
_HOST_IS_32BIT = sys.maxsize <= 2**32


def _eval_compilation_target_pred(node):
    """Fold a zero-arg `CompilationTarget.<predicate>()` to a host bool/int,
    or None. Only predicates that are compile-time constants for THIS host
    build fold; anything else stays unknown so a runtime branch is kept."""
    if not (isinstance(node, CallExpr) and isinstance(node.func, MemberExpr)
            and not node.args and not node.kwargs):
        return None
    obj = node.func.obj
    # `CompilationTarget.is_macos()` (name) or `sys.CompilationTarget...` not
    # needed here; the stdlib spells it as a bare name.
    if not (isinstance(obj, IdentExpr) and obj.name == 'CompilationTarget'):
        return None
    m = node.func.member
    # OS
    if m == 'is_macos':
        return _HOST_IS_MACOS
    if m == 'is_linux':
        return _HOST_IS_LINUX
    # Arch
    if m == 'is_x86':
        return _HOST_IS_X86
    if m == 'is_x86_64' or m == 'is_amd64':
        return _HOST_IS_X86 and not _HOST_IS_32BIT
    if m == 'is_arm':
        return _HOST_IS_ARM
    if m == 'is_aarch64':
        return _HOST_IS_ARM and not _HOST_IS_32BIT
    if m in ('is_apple_silicon', 'is_apple_m'):
        return _HOST_IS_MACOS and _HOST_IS_ARM
    # ISA features (host)
    if m == 'has_neon':
        return _HOST_IS_ARM
    if m in ('has_neon_int8_dotprod', 'has_neon_int8_matmul'):
        # Conservative on generic ARM; Apple Silicon has these but detecting
        # portably is non-trivial. Leave unknown rather than guess wrong?
        # has_neon is the common gate used in path.mojo; keep others unknown.
        return None
    if m == 'has_sse4':
        return _HOST_IS_X86
    if m == 'has_avx':
        # Not guaranteed on all x86_64 hosts; fold false only when clearly
        # not x86. On x86 keep unknown unless we know - safer to not fold
        # than fold wrong. But for macOS arm64 host this is false.
        return False if not _HOST_IS_X86 else None
    if m in ('has_avx2', 'has_avx512f', 'has_fma', 'has_vnni', 'has_intel_amx'):
        return False if not _HOST_IS_X86 else None
    if m == 'is_32bit':
        return _HOST_IS_32BIT
    if m == 'is_64bit':
        return not _HOST_IS_32BIT
    if m == 'is_little_endian':
        return sys.byteorder == 'little'
    if m == 'is_big_endian':
        return sys.byteorder == 'big'
    return None


def folded_truth(value):
    """The truth value of a value `eval_const` folded, or None when the fold
    produced no value at all.

    Truthiness is the source language's own (Python's) rule, so every folded
    value answers it: `""`, `[]`, `{}` and `()` are false, their non-empty
    counterparts true, and numbers are `!= 0`. Every place in this file that
    turns a folded value into a bool goes through here, because two of them
    used to accept only `bool`/`int`: a module-level `if` on a folded string,
    list, tuple or dict had its then-arm deleted as CONST_FALSE, and the
    `not` fold answered "not a number, so unfoldable" (which the same caller
    then read as CONST_FALSE). That is how `if "x":` and `if not "":`
    compiled to their else arms while the numbers-only cases looked right.
    """
    if isinstance(value, (bool, int, float, str, bytes, list, tuple, dict,
                          set, frozenset)):
        return bool(value)
    return None


def eval_const(node, bindings: dict, platform: str = None, conforms_to_pred=None):
    """Evaluate `node` as any compile-time constant — an int, bool, float,
    str, or a list/tuple/dict of them — or None if it isn't foldable.

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
    if isinstance(node, FloatLiteral): return node.value
    if isinstance(node, StringLiteral):
        if getattr(node, 'is_interpolated', False):
            v = _eval_interpolated_string(node, bindings, platform, conforms_to_pred)
            return v if v is not None else node.value
        return node.value
    _ct = _fold_conforms_to_call(node, conforms_to_pred, bindings)
    if _ct is not None:
        return bool(_ct)
    _dt = _fold_del_is_trivial(node, conforms_to_pred, bindings)
    if _dt is not None:
        return bool(_dt)
    if DottedLiteral is not None and isinstance(node, DottedLiteral):
        # A dot-relative value (`.float32`, `.Some`) folds to a marker for
        # enum/DType values. The node's field is `path`
        # (fire_compiler.DottedLiteral: `.float32` -> path='float32'); it has no
        # `.name`, and reading that orphan field raised AttributeError, which the
        # guard turned into "not foldable" — while `_const_foldable` called the
        # same node foldable, which reads as CONST_FALSE, not CONST_UNKNOWN.
        # That made `DType.float32 == .float32` fold FALSE and prune the arm
        # that was true. `path` is REQUIRED to be a non-empty string here: a
        # dot value whose spelling cannot be read is not foldable, and saying
        # so keeps it consistent with `_const_foldable`.
        try:
            _dpath = getattr(node, 'path', None)
            if _dpath is None:
                _dpath = getattr(node, 'name')
        except Exception:
            return None
        if not isinstance(_dpath, str) or not _dpath:
            return None
        return ('.', _dpath)
    if TupleExpr is not None and isinstance(node, TupleExpr):
        res = []
        for e in getattr(node, 'elements', []) or []:
            v = eval_const(e, bindings, platform, conforms_to_pred)
            if v is None:
                return None
            res.append(v)
        return tuple(res)
    if ListExpr is not None and isinstance(node, ListExpr):
        res = []
        for e in getattr(node, 'elements', []) or []:
            v = eval_const(e, bindings, platform, conforms_to_pred)
            if v is None:
                return None
            res.append(v)
        return res
    if Comprehension is not None and isinstance(node, Comprehension):
        return _fold_comprehension(node, bindings, platform, conforms_to_pred)
    if DictExpr is not None and isinstance(node, DictExpr):
        res = {}
        for pair in getattr(node, 'pairs', []) or []:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                return None
            k = eval_const(pair[0], bindings, platform, conforms_to_pred)
            v = eval_const(pair[1], bindings, platform, conforms_to_pred)
            if k is None or v is None:
                return None
            try:
                res[k] = v
            except Exception:
                return None
        return res
    # PART 6 (2026-10-23, family S): the string-wrapping CONSTRUCTOR over a
    # single foldable argument — `StringSlice("x")`, `StaticString("x")`,
    # `String("x")`, `StringSpan("x")`. In every backend of this tree the
    # wrapped value IS the string itself (the gimple path's char* model, the
    # arm64 path's text value), so the constructor is transparent to
    # folding. Measured need: test/collections/string/test_iterators's
    # module-level `comptime EVERY_CODEPOINT_LENGTH_STR =
    # StringSlice("...")` — without this the constructor folded to None,
    # the module-level ComptimeVarStmt dropped the name, and every read
    # inside a function emitted the `(int64_t)0  /* ct param or undeclared
    # */` placeholder (probe f_global: `var s = E; s.byte_length()` read the
    # zero stub on the word receiver). Before this, such a guard in a
    # comptime `if` was UNRESOLVABLE (the documented first-branch-wins
    # fallback); folding it answers the measured value — strictly more
    # precise, the same direction as this file's own sys.platform fold.
    # `_get_kgen_string["text"]()` — the stdlib's reflection spelling of a
    # string constant (std.collections.string.string_span). Folded BY NAME, the
    # same way `String`/`StaticString` are, so a diagnostic built from it reads
    # its text instead of a temp name. The index is folded first, so a comptime
    # string alias works too. Any other shape (arguments, an unknown index, a
    # non-string value) stays unfolded.
    if (isinstance(node, CallExpr) and not node.args and not node.kwargs
            and isinstance(node.func, SubscriptExpr)
            and isinstance(node.func.obj, IdentExpr)
            and node.func.obj.name == '_get_kgen_string'):
        v = eval_const(node.func.index, bindings, platform)
        return v if isinstance(v, str) else None
    # `String(int)` / `String(bool)` stringifies at compile time so comptime
    # diagnostics (e.g. `comptime assert cond, "got " + String(x)`) produce
    # the evaluated message, not a lowered temp name.
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and len(node.args) == 1 and not node.kwargs
            and node.func.name in ('String', 'StringSlice', 'StaticString',
                                   'StringSpan')):
        v = eval_const(node.args[0], bindings, platform, conforms_to_pred)
        if node.func.name == 'String' and isinstance(v, (int, bool)) and not isinstance(v, str):
            return str(v)
        return v
    # `ord("0")` of a one-character constant, and a fixed-width scalar
    # constructor over a foldable integer — `comptime ord_0 = Byte(ord("0"))`
    # is the idiom (std/collections/string/_parsing_numbers/parsing_floats).
    # Neither folded, so the ComptimeVarStmt dropped the name and every read
    # inside a function emitted `(int64_t)0  /* ct param or undeclared */`:
    # `byte == ord_dot` compared against 0 and `byte - ord_0` subtracted 0,
    # i.e. silently wrong digits, with a `-Wpointer-to-int-cast` warning as
    # the only symptom. The constructor wraps to its width, as the runtime
    # constructor does. `len(x)` folds when `x` is a comptime-known
    # list/tuple/string/dict so `comptime assert len(a) == ...` and
    # `comptime for i in range(len(a))` bounds produce compile-time
    # diagnostics (DIAGNOSTICS_missing_validation_modular).
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and len(node.args) == 1 and not node.kwargs):
        _cfn = node.func.name
        if _cfn == 'len':
            _lv = eval_const(node.args[0], bindings, platform, conforms_to_pred)
            if isinstance(_lv, (list, tuple, str, dict)):
                return len(_lv)
            return None
        if _cfn == 'ord':
            _ov = eval_const(node.args[0], bindings, platform, conforms_to_pred)
            if isinstance(_ov, str) and len(_ov) == 1:
                return ord(_ov)
            return None
        _bits = _SCALAR_CTOR_BITS.get(_cfn)
        if _bits is not None:
            _iv = eval_const(node.args[0], bindings, platform, conforms_to_pred)
            if isinstance(_iv, int) and not isinstance(_iv, (bool, str)):
                _w = _iv & ((1 << _bits[0]) - 1)
                if _bits[1] and _w >= (1 << (_bits[0] - 1)):
                    _w -= (1 << _bits[0])
                return _w
            return None
    if isinstance(node, IdentExpr):
        if node.name in bindings:
            _bv = bindings.get(node.name)
            # A generic comptime alias is a TEMPLATE, not a value: an
            # application is what names one (`Alias[Int]`, handled below).
            # Returning the declaration here would read as a folded constant.
            if isinstance(_bv, ComptimeVarStmt):
                return None
            return _bv
        # A scalar type spelling in a DType position is that dtype's value
        # (`Float32` == `DType.float32` == `.float32`).  Only used where a
        # compile-time VALUE is being folded, so an ordinary type name used as
        # a type (annotations, constructors) never reaches here.
        _tn = _DTYPE_TYPE_NAMES.get(node.name)
        if _tn is not None:
            return ('DType', _tn)
        return None
    # `DType.int32` / `dtype.int32` — a compile-time DType value.
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name in ('DType', 'dtype')):
        return ('DType', node.member.lower())
    # DType predicate methods: `dtype.is_integral()`, `DType.float32.is_integral()`.
    # `constrained`/`comptime assert` conditions depend on these; folding them
    # (including when `dtype` is an instantiated generic param in `bindings`)
    # lets the compile-time diagnostic paths reject provably-false cases.
    if (isinstance(node, CallExpr) and isinstance(node.func, MemberExpr)
            and not node.args and not node.kwargs):
        _dm = node.func.member
        _dn = _resolve_dtype_name(node.func.obj, bindings, platform)
        if _dn is not None:
            _dv = _eval_dtype_predicate(_dn, _dm)
            if _dv is not None:
                return _dv
    # The same predicate reached through a chained dot-value: `.float64.is_unsigned()`.
    # Without this the condition reads CONST_UNKNOWN, BOTH arms are emitted, and
    # `max_finite[.float64]` put `~Scalar[.float64](0)` -- a bit-complement on a
    # float dtype -- into the C, where GCC rejects it.
    if isinstance(node, CallExpr) and not node.args and not node.kwargs:
        _ch = _chained_dot_predicate(node.func)
        if _ch is not None:
            _dv = dtype_predicate_for_spelling(_ch[0], _ch[1])
            if _dv is not None:
                return bool(_dv)
    # Dict/list method calls on comptime-known values
    if isinstance(node, CallExpr) and isinstance(node.func, MemberExpr) and not node.kwargs:
        _obj = node.func.obj
        _method = node.func.member
        _ov = eval_const(_obj, bindings, platform)
        if isinstance(_ov, dict):
            if _method == 'keys' and len(node.args) == 0:
                try:
                    return list(_ov.keys())
                except Exception:
                    return None
            if _method == 'values' and len(node.args) == 0:
                try:
                    return list(_ov.values())
                except Exception:
                    return None
            if _method == 'items' and len(node.args) == 0:
                try:
                    return list(_ov.items())
                except Exception:
                    return None
        if isinstance(_ov, (list, tuple, str)):
            if _method == 'copy' and len(node.args) == 0:
                try:
                    if isinstance(_ov, str):
                        return _ov
                    return type(_ov)(_ov)
                except Exception:
                    return None

    # Subscript/slice on a comptime-known value (list/tuple/str/dict element
    # access or slicing). Required so `comptime assert a[i] == ...` and similar
    # conditions over comptime collections produce compile-time diagnostics
    # (comptime collection ops beyond len()).
    #
    # An APPLICATION of a generic comptime alias (`IsTriviallyDeinitable[Int]`)
    # is a subscript too, but its base is a TEMPLATE rather than a value, so it
    # is decided by substituting the bracket arguments into the alias body
    # before the collection-subscript fold can decline it.
    if SubscriptExpr is not None and isinstance(node, SubscriptExpr):
        _tmpl = _comptime_alias_template(bindings, node.obj)
        if _tmpl is not None:
            return _eval_alias_application(node, _tmpl, bindings, platform,
                                           conforms_to_pred)
    _sv = _eval_subscript(node, bindings, platform, conforms_to_pred)
    if _sv is not None:
        return _sv
    if isinstance(node, UnaryOp) and node.op in FOLD_UNARY_OPS:
        v = eval_const(node.operand, bindings, platform, conforms_to_pred)
        # A float operand makes this a float fold, which `fold_unary_sign`
        # (an integer sign table) and its `eval_const_int` fallback cannot
        # answer at all: `if -0.5:` folded to None and its then-arm was
        # deleted as CONST_FALSE. `+`/`-` are exact on a double; `~` has no
        # float meaning (CPython raises), so it stays unfolded.
        if isinstance(v, float) and node.op in ('+', '-'):
            return -v if node.op == '-' else v
        return fold_unary_sign(node.op, v) if isinstance(v, (int, bool)) \
            and not isinstance(v, str) else None
    if isinstance(node, UnaryOp) and node.op == 'not':
        # Truthiness of every folded value, not just numbers: `not "x"` is
        # False and `not ""` is True. Answering None here made
        # `eval_const_bool_state` read the shape as CONST_FALSE and delete
        # the then-arm of a module-level `if not "":`.
        t = folded_truth(eval_const(node.operand, bindings, platform,
                                    conforms_to_pred))
        return None if t is None else not t
    if isinstance(node, BinaryOp):
        op = node.op
        # DType equality is identity of the dtype, not identity of the marker's
        # spelling: `Float32`, `DType.float32` and `.float32` all denote one
        # dtype, but eval_const's markers carry different tags for them
        # (('DType', name) / ('.', name)), so the generic tuple comparison below
        # would answer False for two equal dtypes. Compare the resolved dtype
        # names first; an unknown spelling falls through to the ordinary fold.
        if op in ('==', '!='):
            _ldn = _resolve_dtype_name(node.left, bindings, platform)
            _rdn = _resolve_dtype_name(node.right, bindings, platform)
            if (_ldn in _KNOWN_DTYPE_NAMES
                    and _rdn in _KNOWN_DTYPE_NAMES):
                _eq = _ldn == _rdn
                return _eq if op == '==' else not _eq
        l = eval_const(node.left, bindings, platform, conforms_to_pred)
        # Short-circuit `and`/`or`: a provably-false left of `and` (or
        # provably-true left of `or`) determines the result even when the
        # right side cannot be folded. This is required for compile-time
        # diagnostics (comptime assert / constrained): `False and <unknown>`
        # is provably false and must be rejected, not treated as unknown.
        if op == 'and':
            if l is None:
                return None
            if not l:
                return l
            r = eval_const(node.right, bindings, platform, conforms_to_pred)
            return r
        if op == 'or':
            if l is None:
                return None
            if l:
                return l
            r = eval_const(node.right, bindings, platform, conforms_to_pred)
            return r
        if op == 'in':
            r = eval_const(node.right, bindings, platform, conforms_to_pred)
            if l is None or r is None:
                return None
            if _is_dtype_value(l) and isinstance(r, (list, tuple)):
                # `dtype in (.float32, .float64)`: membership by DType name
                # (see compare_op), not the raw tuple test a bound DType never
                # satisfies against its dot-relative members.
                return compare_op('in', l, r)
            try:
                if isinstance(r, (list, tuple, set)):
                    return l in r
                if isinstance(r, dict):
                    return l in r
                if isinstance(r, str) and isinstance(l, str):
                    return l in r
            except Exception:
                pass
            return None
        if op == 'not in':
            res = eval_const(BinaryOp(op='in', left=node.left, right=node.right), bindings, platform)
            if res is None:
                return None
            return not res
        r = eval_const(node.right, bindings, platform, conforms_to_pred)
        if l is None or r is None: return None
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
        # A float operand makes the expression float-valued, and no integer
        # folder can answer it, so this is the only place that can. Entering
        # only on a REAL float keeps `7 % 2` and `2 ** 3` folding exactly as
        # before (through `eval_const_int`'s fallback), which is what a
        # `comptime` integer constant is entitled to.
        if isinstance(l, float) or isinstance(r, float):
            folded = fold_arith_float(op, l, r)
            if folded is not None:
                return folded
        # String concatenation folds so comptime diagnostics can format
        # messages like `"got " + String(x)` when both sides are known.
        if op == '+' and isinstance(l, str) and isinstance(r, str):
            return l + r
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
            and node.obj.name == 'sys'):
        if node.member == 'platform':
            return platform
        if node.member == 'byteorder':
            # `sys.byteorder` is a host constant in exactly the sense the
            # `sys.platform` fold above is one: CPython's value is fixed for
            # the machine the binary runs on, and this path resolves with no
            # target attached, so the plain-`import sys` fallback is the same
            # (the unaliased import must stay unaliased — see this
            # function's docstring). Measured need (row 10, ctypes/_endian):
            # its `if sys.byteorder == "little":` / `elif "big":`
            # conditional-toplevel shape unfolded to BOTH branches, and the
            # dead branch's plain `BigEndianStructure = Structure` assignment
            # references a module global the live branch's `class
            # BigEndianStructure` never registers as a lookable member —
            # `struct _ctypes__endian_toplev has no member named
            # 'BigEndianStructure'; did you mean 'Little...'` at _endian.py
            # :63:27 and :70:27. Folding picks the host's branch exactly as
            # the runtime would, and removes the other one. The
            # AttributeError guard keeps the self-host route byte-identical
            # to the pre-fold behavior: there the unaliased `import sys`
            # binds the compiled stdlib's sys, which exposes no byteorder,
            # so the fold declines and both branches emit, as before.
            try:
                return sys.byteorder
            except AttributeError:
                return None
    # `CompilationTarget.<predicate>()` is a compile-time constant for the
    # host this compiler is building for, the same way `sys.platform` is: a
    # `comptime if CompilationTarget.is_macos(): ... elif
    # CompilationTarget.has_neon(): ...` chain must keep only the branch the
    # host can take, because every other branch names target-specific
    # definitions that do not exist on this host and cannot be linked. See
    # CODEGEN_stdlib_dylib_lazy_undefined_refs-part4: the fold was missing,
    # so the lowering emitted a call (and an extern) into every arm.
    _ctv = _eval_compilation_target_pred(node)
    if _ctv is not None:
        return _ctv
    return None


def eval_const_int(node, bindings: dict, call_hook=None, conforms_to_pred=None):
    """Evaluate `node` as a compile-time int, or None.

    `call_hook(name, args) -> int | None` is the one backend-specific case —
    folding a *call* by running it at compile time. The gimple path passes a
    hook backed by elaborate.py + comptime.py (compiled-and-run the imported
    function); a backend with no such machinery (the arm64 path) omits it and
    simply does not fold calls."""
    if isinstance(node, IntLiteral):  return node.value
    if isinstance(node, BoolLiteral): return int(node.value)
    if isinstance(node, IdentExpr):
        v = bindings.get(node.name)
        if isinstance(v, (int, bool)) and not isinstance(v, str):
            return int(v)
        return None
    if isinstance(node, UnaryOp) and node.op in FOLD_UNARY_OPS:
        v = eval_const_int(node.operand, bindings, call_hook, conforms_to_pred)
        return None if v is None else fold_unary_sign(node.op, v)
    if isinstance(node, BinaryOp):
        op = node.op
        l = eval_const_int(node.left, bindings, call_hook, conforms_to_pred)
        # Short-circuit and/or: required for comptime diagnostics and to
        # match eval_const's semantics (False and <unknown> is provably false).
        if op == 'and':
            if l is None: return None
            if not l: return l
            return eval_const_int(node.right, bindings, call_hook, conforms_to_pred)
        if op == 'or':
            if l is None: return None
            if l: return l
            return eval_const_int(node.right, bindings, call_hook, conforms_to_pred)
        r = eval_const_int(node.right, bindings, call_hook, conforms_to_pred)
        if l is None or r is None: return None
        if op == '+': return l + r
        if op == '-': return l - r
        if op == '*': return l * r
        if op == '//': return l // r if r else None
        if op == '%': return l % r if r else None
        if op == '**': return l ** r
        if op == '==': return int(l == r)
        if op == '!=': return int(l != r)
        if op == '<': return int(l < r)
        if op == '<=': return int(l <= r)
        if op == '>': return int(l > r)
        if op == '>=': return int(l >= r)
        return None
    if isinstance(node, CompareChain):
        # Same short-circuit chained-comparison semantics as
        # myinterpreter.py's eval_CompareChain / _lower_compare_chain, just
        # over compile-time constants instead of runtime values.
        left = eval_const_int(node.operands[0], bindings, call_hook, conforms_to_pred)
        if left is None: return None
        for op, operand in zip(node.ops, node.operands[1:]):
            right = eval_const_int(operand, bindings, call_hook, conforms_to_pred)
            if right is None: return None
            link = compare_op(op, left, right)
            if link is None: return None
            if not link: return 0
            left = right
        return 1
    # `len(x)` of a comptime-known list/tuple/string/dict
    # (DIAGNOSTICS_missing_validation_modular).
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and node.func.name == 'len' and len(node.args) == 1
            and not node.kwargs):
        _lv = eval_const(node.args[0], bindings)
        if isinstance(_lv, (list, tuple, str, dict)):
            return len(_lv)
        return None
    # Subscript/slice yielding an int (e.g. `range(a[0])` with comptime `a`).
    if ((SubscriptExpr is not None and isinstance(node, SubscriptExpr))
            or (SliceExpr is not None and isinstance(node, SliceExpr))):
        _sv = eval_const(node, bindings)
        if isinstance(_sv, (int, bool)) and not isinstance(_sv, str):
            return int(_sv)
        return None
    _ctv = _eval_compilation_target_pred(node)
    if _ctv is not None:
        return int(_ctv)
    if call_hook is not None and isinstance(node, CallExpr) and isinstance(
            node.func, IdentExpr):
        argvals = [eval_const_int(a, bindings, call_hook, conforms_to_pred) for a in node.args]
        # A zero-arg call reaches the hook: `argvals` is an empty list, and
        # the old `argvals and ...` gate read that as "cannot answer" even
        # though every (zero) argument folded. That left the stdlib's
        # zero-arg target queries (`is_nvidia_gpu()`, ...) permanently
        # CONST_UNKNOWN, so a `comptime if` over them emitted every arm, the
        # GPU ones included, as live code on a CPU build. `all([])` is True:
        # there is nothing left to fold.
        if all(v is not None for v in argvals):
            return call_hook(node.func.name, argvals)
    return None


def eval_const_bool(node, bindings: dict, call_hook=None, platform: str = None, conforms_to_pred=None):
    """Evaluate `node` as a compile-time bool, or None.

    A folded value answers PYTHON truthiness (`folded_truth`), not just
    bool/int: a folded float (`bool(0.5)` is True) and a folded container
    (`if "x":`, `if [1]:`, `if {1: 2}:` are all True in CPython, and their
    empty forms False). A shape that folds to a value and is then not
    answered here is reported FALSE by `eval_const_bool_state` below, which
    folded `if 0.0001:` and `if "x":` to the else arm at module level,
    deleting the then-arm before emission.
    """
    t = folded_truth(eval_const(node, bindings, platform, conforms_to_pred))
    if t is not None:
        return t
    # Fallback: eval_const_int also folds what eval_const does not (calls,
    # via the hook).
    result = eval_const_int(node, bindings, call_hook, conforms_to_pred)
    return bool(result) if isinstance(result, (bool, int)) else None


# The tri-state answer as an INT: 1 (true), 0 (false), -1 (not a compile-time
# constant). `eval_const_bool`'s `bool | None` cannot carry three states once
# this file is compiled by the self-hosted compiler: its value model spells
# None as the zero word, which is also False, so "not foldable" read as
# "false". Every caller that branches on the answer -- a module-level `if
# __name__ == '__main__':` the global scan resolves, a `comptime if` -- then
# took the else-branch of a condition nobody could decide, and the stage2
# binary dropped the whole `if __name__` body from the module's globals.
CONST_TRUE = 1
CONST_FALSE = 0
CONST_UNKNOWN = -1


def _const_foldable(node, bindings: dict, call_hook=None, conforms_to_pred=None) -> bool:
    """Is `node` a compile-time constant at all? Decided from the SHAPE of
    the expression and the names bound, never from a folded value, so the
    answer survives the compiled value model (see CONST_UNKNOWN). Mirrors
    the cases `eval_const` / `eval_const_int` fold; anything else is not
    foldable. A call is foldable only when the backend's hook can run it,
    which is the one case that has to evaluate to find out."""
    if isinstance(node, (BoolLiteral, IntLiteral, FloatLiteral, StringLiteral)):
        return True
    if DottedLiteral is not None and isinstance(node, DottedLiteral):
        return True
    if TupleExpr is not None and isinstance(node, TupleExpr):
        for e in getattr(node, 'elements', []) or []:
            if not _const_foldable(e, bindings, call_hook, conforms_to_pred):
                return False
        return True
    if ListExpr is not None and isinstance(node, ListExpr):
        for e in getattr(node, 'elements', []) or []:
            if not _const_foldable(e, bindings, call_hook, conforms_to_pred):
                return False
        return True
    if DictExpr is not None and isinstance(node, DictExpr):
        for pair in getattr(node, 'pairs', []) or []:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                return False
            if not _const_foldable(pair[0], bindings, call_hook, conforms_to_pred):
                return False
            if not _const_foldable(pair[1], bindings, call_hook, conforms_to_pred):
                return False
        return True
    _ct = _fold_conforms_to_call(node, conforms_to_pred, bindings)
    if _ct is not None:
        return True
    if _fold_del_is_trivial(node, conforms_to_pred, bindings) is not None:
        return True
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and node.func.name == 'conforms_to'):
        return False
    if isinstance(node, IdentExpr):
        if node.name in bindings:
            # A generic alias template is foldable only through an
            # APPLICATION (`Alias[Int]`), not as a bare name.
            return _comptime_alias_template(bindings, node) is None
        return node.name in _DTYPE_TYPE_NAMES
    # `DType.int32` / `dtype.int32`
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name in ('DType', 'dtype')):
        return True
    # DType predicate method on a resolvable DType (literal or bound param).
    # Only foldable when the dtype and predicate are both known, so an
    # unresolved dtype stays CONST_UNKNOWN rather than becoming a false
    # diagnostic.
    if (isinstance(node, CallExpr) and isinstance(node.func, MemberExpr)
            and not node.args and not node.kwargs):
        _dn = _resolve_dtype_name(node.func.obj, bindings)
        if _dn is not None and _eval_dtype_predicate(_dn, node.func.member) is not None:
            return True
    # The chained dot-value spelling of the same predicate (see
    # `_chained_dot_predicate`). Shape-only, like the branch above: a path this
    # folder cannot resolve stays CONST_UNKNOWN rather than reading as false.
    if isinstance(node, CallExpr) and not node.args and not node.kwargs:
        _ch = _chained_dot_predicate(node.func)
        if _ch is not None and dtype_predicate_for_spelling(*_ch) is not None:
            return True
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name == 'sys' and node.member == 'platform'):
        return True
    if (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)
            and node.obj.name == 'sys' and node.member == 'byteorder'):
        # Foldable only where `eval_const` really can read the host value:
        # in the self-hosted binary `sys` binds the compiled stdlib's, which
        # exposes no byteorder, the fold declines, and a shape-only "yes"
        # would then read as CONST_FALSE and drop the live branch.
        return eval_const(node, bindings) is not None
    # CompilationTarget host predicates fold to constants for this host.
    if _eval_compilation_target_pred(node) is not None:
        return True
    # String/ord/len/scalar constructors and other 1-arg ident calls eval_const folds.
    if (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
            and len(node.args) == 1 and not node.kwargs
            and node.func.name in ('String', 'StringSlice', 'StaticString',
                                   'StringSpan', 'ord', 'len')
            or (isinstance(node, CallExpr) and isinstance(node.func, IdentExpr)
                and len(node.args) == 1 and not node.kwargs
                and node.func.name in _SCALAR_CTOR_BITS)):
        return _const_foldable(node.args[0], bindings, call_hook)
    # Dict/list method calls on comptime-known values
    if isinstance(node, CallExpr) and isinstance(node.func, MemberExpr) and not node.kwargs:
        _method = node.func.member
        if _method in ('keys', 'values', 'items') and len(node.args) == 0:
            try:
                _ov = eval_const(node.func.obj, bindings)
                if isinstance(_ov, dict):
                    return True
            except Exception:
                pass
        if _method == 'copy' and len(node.args) == 0:
            try:
                _ov = eval_const(node.func.obj, bindings)
                if isinstance(_ov, (list, tuple, str, dict)):
                    return True
            except Exception:
                pass
    # Subscript/slice on a comptime-known collection (DIAGNOSTICS_missing_validation_modular).
    if SubscriptExpr is not None and isinstance(node, SubscriptExpr):
        if getattr(node, 'attrs', None):
            return False
        # A generic comptime alias application is foldable exactly when its
        # substituted BODY folds. Deciding this by shape alone would let a
        # body that still cannot be decided (`downcast[T, Trait].member` for
        # an unknown T) read as CONST_FALSE, silently pruning the true arm —
        # the failure mode this whole path exists to avoid.
        _tmpl = _comptime_alias_template(bindings, node.obj)
        if _tmpl is not None:
            return _eval_alias_application(node, _tmpl, bindings, None,
                                           conforms_to_pred) is not None
        return (_const_foldable(node.obj, bindings, call_hook, conforms_to_pred)
                and _const_foldable(node.index, bindings, call_hook, conforms_to_pred))
    if SliceExpr is not None and isinstance(node, SliceExpr):
        if not _const_foldable(node.obj, bindings, call_hook, conforms_to_pred):
            return False
        for _part in (getattr(node, 'start', None),
                      getattr(node, 'stop', None),
                      getattr(node, 'step', None)):
            if _part is not None and not _const_foldable(_part, bindings, call_hook, conforms_to_pred):
                return False
        return True
    if isinstance(node, UnaryOp) and (node.op in FOLD_UNARY_OPS or node.op == 'not'):
        return _const_foldable(node.operand, bindings, call_hook, conforms_to_pred)
    if isinstance(node, BinaryOp):
        op = node.op
        if op == 'and':
            if not _const_foldable(node.left, bindings, call_hook, conforms_to_pred):
                return False
            try:
                lv = eval_const(node.left, bindings, None, conforms_to_pred)
            except Exception:
                lv = None
            if lv is None and call_hook is not None:
                # `eval_const` carries no hook: a call only the backend's
                # hook can fold (a zero-arg target query, `is_amd_gpu()`)
                # reads as not-false here, and the whole `and` would then
                # demand its right side be foldable to prune an arm the
                # hook has already decided dead. Ask the hook the same
                # question; a falsy answer settles the condition.
                try:
                    lv = eval_const_int(node.left, bindings, call_hook,
                                        conforms_to_pred)
                except Exception:
                    lv = None
            if lv is not None and not lv:
                return True
            return _const_foldable(node.right, bindings, call_hook, conforms_to_pred)
        if op == 'or':
            if not _const_foldable(node.left, bindings, call_hook, conforms_to_pred):
                return False
            try:
                lv = eval_const(node.left, bindings, None, conforms_to_pred)
            except Exception:
                lv = None
            if lv is None and call_hook is not None:
                # Mirror of the `and` case: a hook-foldable truthy left
                # settles the whole condition.
                try:
                    lv = eval_const_int(node.left, bindings, call_hook,
                                        conforms_to_pred)
                except Exception:
                    lv = None
            if lv is not None and lv:
                return True
            return _const_foldable(node.right, bindings, call_hook, conforms_to_pred)
        return (_const_foldable(node.left, bindings, call_hook, conforms_to_pred)
                and _const_foldable(node.right, bindings, call_hook, conforms_to_pred))
    if isinstance(node, CompareChain):
        for _operand in node.operands:
            if not _const_foldable(_operand, bindings, call_hook, conforms_to_pred):
                return False
        return True
    if (call_hook is not None and isinstance(node, CallExpr)
            and isinstance(node.func, IdentExpr)):
        return eval_const_int(node, bindings, call_hook, conforms_to_pred) is not None
    return False


def eval_const_bool_state(node, bindings: dict, call_hook=None,
                          platform: str = None, conforms_to_pred=None) -> int:
    """`eval_const_bool` as CONST_TRUE / CONST_FALSE / CONST_UNKNOWN.

    Foldability comes first and from the expression's shape
    (`_const_foldable`); only a foldable condition is evaluated. A foldable
    shape whose fold still fails (`1 // 0`) answers false rather than
    unknown -- the one place the two spellings differ, and a condition that
    divides by zero at compile time has no meaningful branch either way."""
    if not _const_foldable(node, bindings, call_hook, conforms_to_pred):
        return CONST_UNKNOWN
    if eval_const_bool(node, bindings, call_hook, platform, conforms_to_pred):
        return CONST_TRUE
    return CONST_FALSE


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
    if isinstance(base, _fc.MemberExpr):
        return base.member
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
                    platform: str = None, conforms_to_pred=None):
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
        v = eval_const(a, bindings, platform, conforms_to_pred)
        if not isinstance(v, (int, bool)) or isinstance(v, str):
            v = eval_const_int(a, bindings, call_hook, conforms_to_pred)
        if v is None:
            return None          # one unfolded argument ⇒ no constant
        args.append(int(v))
    return call_hook(node.func.name, args)


def resolve_var(stmt, bindings: dict, call_hook=None,
                platform: str = None, conforms_to_pred=None):
    """What a `comptime NAME = value` statement binds, or None if it cannot.

    Returns ('value', v) for a scalar that folded, or ('list', ast) for a
    list/tuple binding — which has no single scalar to fold to but is still
    compile-time state, and is kept as its AST so `comptime for x in NAME` can
    unroll over it. None means "not a compile-time constant", which a backend
    must report rather than quietly turn into a runtime variable: that would
    give the program different behaviour than the source declares."""
    val = eval_const(stmt.value, bindings, platform, conforms_to_pred)
    if val is None:
        # A call is the one shape `eval_const` cannot fold on its own; the
        # backend's hook runs it (see formal/comptime_runner.py).
        val = eval_const_call(stmt.value, bindings, call_hook, platform, conforms_to_pred)
    if val is not None:
        return ('value', val)
    if isinstance(stmt.value, (_fc.ListExpr, _fc.TupleExpr)):
        return ('list', stmt.value)
    return None


def resolve_if(stmt, bindings: dict, platform: str = None,
               call_hook=None, conforms_to_pred=None):
    """Which `comptime if` branch is taken, or None if it is not knowable.

    'then' / ('elif', i) / 'else' mean "emit only that branch"; None means the
    condition is not statically known and the backend must emit a runtime
    branch — same observable behaviour, no silent miscompile."""
    val = eval_const_bool_state(stmt.condition, bindings, call_hook,
                                platform=platform, conforms_to_pred=conforms_to_pred)
    if val == CONST_TRUE:
        return 'then'
    if val == CONST_FALSE:
        for i, (cond, _body) in enumerate(getattr(stmt, 'elifs', None) or []):
            if eval_const_bool_state(cond, bindings, call_hook,
                                     platform=platform, conforms_to_pred=conforms_to_pred) == CONST_TRUE:
                return ('elif', i)
        return 'else'
    return None


def resolve_for_iterable(iterable, bindings: dict, list_asts: dict,
                         unroll_cap: int, call_hook=None, conforms_to_pred=None):
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
        v = eval_const_int(a, bindings, call_hook, conforms_to_pred)
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

