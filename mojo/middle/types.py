# Moved from gimple_ctypes.py - shared middle-end (mojo/middle).
# Import rewrite performed via AST; original docstring/comments preserved below.
"""Shared C-type utilities and leaf constants for the GIMPLE backend.

Mechanically extracted from gimple_codegen.py (Wave-2 integration, M1).
Leaf-most module: stdlib imports only; every other gimple_* module may
import from here without cycles. Definitions are verbatim moves;
gimple_codegen re-imports them so unqualified internal references and
external `from gimple_codegen import X` keep working unchanged.
"""
from __future__ import annotations

# `_RUNTIME_FUNCS` (runtime function name -> C return type) is defined ONCE,
# in gimple_codegen.py, and re-exported here: this file previously held
# a second, STALE copy that had drifted (it was missing eight entries,
# so a new runtime function added to the real table was invisible to
# anything reading this one). gimple_codegen is the module the rest of
# the compiler imports the name from, so it stays the definition and
# this is a re-export rather than the reverse.
import hashlib
import os
import re
import sys
import dataclasses
from fire_compiler import split_top_level_commas, target_slots, for_target_is_tuple, for_target_names, for_target_single_name, IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, DottedLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, MatchCase, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, py_tokenize, Parser, _as_str, _as_int, _as_intlit_node, _as_boollit_node, _signed_int64, _signed_int64_c_literal
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
from generated_dispatch import _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT, _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS, _STMT_DISPATCH, _EXPR_DISPATCH

def _debug_note(where: str, detail: object='') -> None:
    """Report a deliberately-swallowed error on stdout when MOJO_DEBUG is set.

    Codegen degrades gracefully on some failures (module imports, type
    inference, generic instantiation).  Those paths intentionally continue
    with reduced information; this hook makes them diagnosable without
    changing compiler behavior for normal runs.

    `print(..., flush=True)` to plain stdout, NOT `file=sys.stderr`: the
    self-hosted backend has no lowering for `sys.stderr`/`sys.stderr.write`
    (see `_compile_imported_module`'s own identical fix in
    gimple_gen_resolve.py) — it faults at the `sys.stderr` attribute access
    itself. That fault is a real, catchable exception under this runtime's
    setjmp-based exception protocol, so it doesn't crash outright; instead
    it becomes a NEW exception raised from inside whatever `except:` block
    had just called `_debug_note` to report the ORIGINAL failure. If that
    surrounding `except` has nothing further to catch it, the new exception
    propagates in its place -- but the global exception MESSAGE slot
    (`mojo_exc_msg_set`) is never overwritten by the stderr fault itself, so
    the propagated exception still carries the original failure's message
    text, making the real cause (this line) invisible from the outside.
    Concretely: `_gen_stmt_ForStmt`'s zip-loop fallback (gimple_gen_stmts.py)
    calls this on a caught `ValueError`, and self-hosted `--dump-full fire.py`
    would silently DROP an entire sibling module (gimple_gen_coro.py) whose
    `for (a, b), c in zip(...)` shape hit that fallback, with only a
    misleadingly-labeled "# ERROR: ...: zip() lowering needs a tuple loop
    target" reaching the module-level catch-all in
    `_compile_imported_module` -- the real point of failure was here, not
    the original (correctly-handled) ValueError.
    """
    if os.environ.get('MOJO_DEBUG'):
        print(f'[gimple_codegen] {where}: {detail}', flush=True)

def _params_have_vararg(params: list) -> bool:
    """True if any `(name, type)` pair in `params` is a `*args`/`**kwargs`
    slot (name starts with `*`).

    Indexed, NOT `any(pn.startswith('*') for pn, _ in params)` — a
    generator-expression target unpack over a `list[tuple[str, str]]`'s
    elements boxes both slots to int64_t on the self-hosted path, which
    GCC then rejects outright as undeclared C identifiers (`'pn'
    undeclared`) — a hard compile failure, not just a silently-wrong
    value, first exposed when an unrelated edit forced this file's
    CAS-cached object to be retranspiled from scratch. This single
    helper replaces ~8 duplicated copies of the same broken idiom across
    gimple_module_gen.py.
    """
    if not params:
        return False
    for i in range(len(params)):
        if params[i][0].startswith('*'):
            return True
    return False

def _param_names_stripped(params: list) -> list:
    """`[pn.lstrip('*') for pn, _ in (params or [])]` — as a plain unpack
    LOOP, not a comprehension: a comprehension's target unpack over a
    `list[tuple[str, str]]` boxes both slots to int64_t self-hosted (see
    `_params_have_vararg`'s sibling note and
    bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md). Shared
    here instead of re-deriving the loop at each call site."""
    out = []
    for pn, _pt in params or []:
        out.append(pn.lstrip('*'))
    return out

class TypeLattice:
    """Numeric type promotion lattice for Mojo → C lowering.

    join(t1, t2) implements C11 usual-arithmetic-conversion rules:
      - If either operand is float, float wins; wider float wins.
      - If both are signed ints, wider wins.
      - If both are unsigned ints, wider wins.
      - If mixed signed/unsigned: if unsigned rank >= signed rank → unsigned; else signed.
    """
    _SIGNED = _GD_SIGNED
    _UNSIGNED = _GD_UNSIGNED
    _FLOAT = _GD_FLOAT

    @classmethod
    def is_float(cls, t: str) -> bool:
        # `if not t` first: the compiled path can hand these predicates a
        # NULL/empty type string where the reference never does, and
        # `None in <dict>`/`'*' in None` lower to a runtime `in` whose
        # `strcmp` then dereferences the NULL (SIGSEGV in `_dict_lookup`
        # via `mojo_in_dispatch_str`). Repro: std/runtime/tracing.mojo's
        # `join(t1=NULL, ...)`.
        if not t:
            return False
        return t in _TYPE_FLOAT

    @classmethod
    def is_signed(cls, t: str) -> bool:
        if not t:
            return False
        return t in _TYPE_SIGNED

    @classmethod
    def is_unsigned(cls, t: str) -> bool:
        if not t:
            return False
        return t in _TYPE_UNSIGNED

    @classmethod
    def is_int(cls, t: str) -> bool:
        if not t:
            return False
        return t in _TYPE_SIGNED or t in _TYPE_UNSIGNED

    @classmethod
    def is_numeric(cls, t: str) -> bool:
        return cls.is_float(t) or cls.is_int(t)

    @classmethod
    def is_pointer(cls, t: str) -> bool:
        if not t:
            return False
        return '*' in t

    @classmethod
    def is_bool(cls, t: str) -> bool:
        if not t:
            return False
        return t == '_Bool'

    @classmethod
    def join(cls, t1: str, t2: str) -> str:
        """LUB for binary arithmetic result type."""
        if t1 == t2:
            return t1
        if t1 == '_Bool':
            t1 = 'int'
        if t2 == '_Bool':
            t2 = 'int'
        if t1 == t2:
            return t1
        if cls.is_pointer(t1) or cls.is_pointer(t2):
            if cls.is_pointer(t1) and cls.is_pointer(t2):
                if t1 == 'void *' or t2 == 'void *':
                    return 'void *'
                if t1 == 'char *' or t2 == 'char *':
                    return 'char *'
                return 'int64_t'
            return t1 if cls.is_pointer(t1) else t2
        if cls.is_float(t1) or cls.is_float(t2):
            r1 = _TYPE_FLOAT.get(t1, 0)
            r2 = _TYPE_FLOAT.get(t2, 0)
            if r1 == 0:
                return t2
            if r2 == 0:
                return t1
            return t1 if r1 >= r2 else t2
        rs1 = _TYPE_SIGNED.get(t1, 0)
        rs2 = _TYPE_SIGNED.get(t2, 0)
        ru1 = _TYPE_UNSIGNED.get(t1, 0)
        ru2 = _TYPE_UNSIGNED.get(t2, 0)
        if rs1 and rs2:
            return t1 if rs1 >= rs2 else t2
        if ru1 and ru2:
            return t1 if ru1 >= ru2 else t2
        if rs1 and ru2:
            return t2 if ru2 >= rs1 else t1
        if ru1 and rs2:
            return t1 if ru1 >= rs2 else t2
        return 'int64_t'

    @classmethod
    def join_all(cls, types: list) -> str:
        """LUB of a list of types (e.g. for return type inference)."""
        if not types:
            return 'void'
        result = types[0]
        for t in types[1:]:
            if result == 'void':
                result = t
            elif t != 'void':
                result = cls.join(result, t)
        return result

    @classmethod
    def coerce(cls, src: str, dst: str, val: str) -> str:
        """Return `val` cast to `dst` if types differ.
        NOTE: GIMPLE only allows single-level casts on simple variables.
        This method must be called only when val is guaranteed to be a simple
        variable name, not a function call or compound expression.
        """
        if src == dst:
            return val
        if src in ('int', 'int64_t', '_Bool') and dst in ('int', 'int64_t', '_Bool'):
            if src == dst:
                return val
            return f'({dst}){val}'
        if src == '_Bool':
            if dst == 'int':
                return f'(int){val}'
            return f'({dst}){val}'
        if dst == '_Bool':
            return f'(_Bool){val}'
        if src.endswith(' *') and dst == 'int64_t':
            if src == 'void *':
                return f'(int64_t){val}'
            return f'(int64_t)(void *){val}'
        if src == 'int64_t' and dst.endswith(' *'):
            if dst == 'void *':
                return f'(void *){val}'
            raise TypeError(f'UNSAFE CAST: int64_t → {dst} requires type validation in _actual_types. Call must verify via _actual_types[{val}] before casting. Use (void *){val} as intermediate if truly generic.')
        return f'({dst}){val}'

    @classmethod
    def list_suffix(cls, elem: str) -> str:
        """Select 'int'/'double'/'str' API suffix based on element C type."""
        if elem in _TYPE_FLOAT:
            return 'double'
        if elem == 'char *':
            return 'str'
        return 'int'

    @classmethod
    def slot_kind_byte(cls, elem: str) -> str:
        """The one byte per list slot of `mojo_list_set_kinds`' alphabet that
        an element of C type `elem` holds — see that function's docstring in
        runtime/fire_runtime.c for the alphabet and the MOJO_KIND_* names.

        A MojoList slot is a raw int64_t, so every consumer that has to know
        what a slot HOLDS (the repr, the per-slot readers, the sorters) needs
        this one mapping rather than its own; the runtime's own default for an
        undescribed slot is 'i', so an unrecognised element type maps there too
        instead of inventing a letter.

        `None` is NOT decided here — it is indistinguishable from 0 once
        lowered, so a caller that can still see the expression (a list
        literal) detects it there, as _list_literal_slot_kind does."""
        if elem in _TYPE_FLOAT:
            return 'd'
        if elem in ('char *', 'MojoStr *'):
            return 'p'
        if elem == 'MojoBytes *':
            return 's'
        if elem in ('MojoList *', 'MojoDict *', 'MojoSet *'):
            return 'l'
        return 'i'

    # The MOJO_KIND_* constant each alphabet byte is named by in
    # runtime/fire_runtime.h, so generated C says `MOJO_KIND_STR` rather than a
    # bare `'p'`. The header is the one definition of the letters; this is the
    # one definition of their names.
    SLOT_KIND_CONST = {'i': 'INT', 'd': 'DOUBLE', 's': 'BYTES',
                       'p': 'STR', 'l': 'LIST', 'n': 'NONE'}

    @classmethod
    def printf_fmt(cls, ctype: str) -> str:
        if ctype in ('double', 'float', '__fp16'):
            return '%g'
        if ctype == 'char *':
            return '%s'
        if ctype == 'char':
            return '%c'
        if ctype == 'int64_t':
            return '%ld'
        if ctype == 'uint64_t':
            return '%lu'
        if ctype in ('unsigned int', 'uint32_t', 'uint16_t', 'uint8_t'):
            return '%u'
        return '%d'
_TYPE_MAP: dict[str | None, str] = {'Int': 'int64_t', 'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t', 'UInt': 'uint64_t', 'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t', 'Float16': '__fp16', 'Float32': 'float', 'Float64': 'double', 'float': 'double', 'Bool': '_Bool', 'bool': 'int', 'String': 'char *', 'str': 'char *', 'List': 'MojoList *', 'list': 'MojoList *', 'Dict': 'MojoDict *', 'dict': 'MojoDict *', 'Set': 'MojoSet *', 'set': 'MojoSet *', 'Str': 'MojoStr *', 'bytes': 'MojoBytes *', 'bytearray': 'MojoBytes *', 'memoryview': 'MojoMemoryView *', 'None': 'void', 'object': 'int64_t'}
# Python builtin name -> the C type it evaluates to. ONE table, because
# two consumers need it and they were two lists: `_quick_type` (which
# types the enclosing function's PROTOTYPE and every local) and
# `_gmi_collect_self_assigns` (which types `self.<field> = <builtin>(...)`).
# The second list was missing every builtin here that is not a literal
# ctor — `sorted`, `reversed`, `map`, `filter`, `range`, `tuple`,
# `enumerate`, `zip` — so `self.itos = sorted(set(text))` declared the
# field `int64_t`, the MojoList* was boxed on the store, and every later
# read of `self.itos` went through the dynamic tagged path with no element
# type: `for i, c in enumerate(self.itos)` bound `c` as int64_t and passed
# those raw pointer bits to `stoi[c] = i`, which gimple rejects outright
# ("invalid argument to gimple call" — mojo_dict_set_int takes char *).
_BUILTIN_RET_CTYPES = {
    'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *',
    # sorted()/reversed() both materialise a MojoList*
    # (see _lower_builtin_sorted / _lower_builtin_reversed).
    'sorted': 'MojoList *', 'reversed': 'MojoList *',
    # enumerate() in VALUE position builds a list of (index, value)
    # pair-lists; as a `for` target it is an iterator instead, but that
    # path dispatches on the call's own shape, not on this type.
    'enumerate': 'MojoList *',
    # zip() chains mojo_zip, which walks MojoLists and returns a new one
    # of pair-lists.
    'zip': 'MojoList *',
    # mojo_range/mojo_range3 return a MojoList*.
    'range': 'MojoList *',
    # tuple(x) lowers to the same MojoList as list(x).
    'tuple': 'MojoList *',
    # map(f, xs) / filter(f, xs) build their result in the CODEGEN
    # (_build_per_element_list), not in the runtime: mojo_map/mojo_filter
    # are identity stubs because a char* function pointer cannot call back
    # into a GIMPLE-compiled body. Both really do produce a MojoList of
    # results / kept elements.
    'map': 'MojoList *', 'filter': 'MojoList *',
    # Bytes/bytearray materialize a MojoBytes*, not a container.
    'bytes': 'MojoBytes *', 'bytearray': 'MojoBytes *',
    # Naming the runtime constructors too, so a `self.x = mojo_list_new()`
    # -shaped call is answered from the same place.
    'mojo_list_new': 'MojoList *', 'mojo_dict_new': 'MojoDict *',
    'mojo_set_new': 'MojoSet *',
    # The Mojo spellings of the container types.
    'DynamicVector': 'MojoList *', 'Dict': 'MojoDict *', 'Set': 'MojoSet *',
    'frozenset': 'MojoSet *',
}

_SCALAR_INT_TYPES = frozenset({'int', 'char', '_Bool', 'int8_t', 'int16_t', 'int32_t', 'int64_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'})
# The floating counterparts, next to _SCALAR_INT_TYPES and for the same
# reason: a builtin that has to branch on "is this argument numeric, and
# if so which" (abs, min, max) should not each re-spell the two sets.
# `float` is a real C float here and `double` is this compiler's default
# for a Python float, so both are in it.
_SCALAR_FLOAT_TYPES = frozenset({'float', 'double', '__fp16'})
_CONTAINER_KIND_TYPES = frozenset({'MojoDict *', 'MojoList *', 'MojoSet *', 'MojoBytes *'})
_EMPTY_CONTAINER_CTOR = {'MojoDict *': 'mojo_dict_new ()', 'MojoList *': 'mojo_list_new ()', 'MojoSet *': 'mojo_set_new ()'}

def _seedable_local_ctype(t) -> bool:
    """True when `_infer_local_var_types`' answer for a local is real
    EVIDENCE and may therefore be seeded into `var_types` so a
    `return <local>` (and the local's own uses) stop falling to the
    int64_t default.

    The rule is "any POINTER-shaped answer", which is the one class that
    cannot BE the no-evidence default: `_quick_type` returns the bare
    `int64_t` default — never a pointer — for everything it cannot resolve,
    so a `*`-suffixed ctype is a resolved struct field, container, builtin
    result or `char *`. This generalises what the three call sites had each
    written out separately as a literal `== 'MojoBytes *'` (two in
    `module_gen`'s Pass 2b / `_struct_method_signatures`, one in
    `emit_funcs._gen_struct_method`), which was the COMPILE_FAIL_zipfile
    bytes-accumulator case and nothing else: the same `t = self.<field>;
    return t` shape with a `char *` or `MojoList *` field lost the type
    identically and silently, printing the pointer as a decimal address.

    Deliberately still excludes every SCALAR answer, including `double` and
    `_Bool`. Those are where `_infer_local_var_types` is most likely reading
    a genuinely ambiguous name (a parameter, an opaque receiver, a builtin
    whose result type is only a guess), and a wrong scalar declaration
    silently changes arithmetic — whereas a wrong pointer declaration was
    already the status quo for everything but bytes, so this widens nothing
    that was previously correct.

    Lives here — the shared C-type-shape module both `module_gen` and
    `emit_funcs` already import — because the two of them both need it and
    `module_gen` imports `emit_funcs` (either of those as a home would be a
    circular import)."""
    _ts = _as_str(t)
    return bool(_ts) and _ts.endswith(' *')


def container_kind(ctype: str) -> str | None:
    """DESIGN.html R1's canonical predicate: 'dict'/'list'/'set'/'bytes' for
    one of this codegen's container pointer ctypes, else None (not a
    container, or an unrecognized/opaque type). This is step one of R1 (a
    single place that answers "what kind of container is this") — most of
    the ~300 sites that independently DECIDE a container's ctype from
    scratch (AST shape, call signature, method name, ...) still do not
    route through a shared decision function, because their inputs are too
    varied to unify mechanically; that migration is a separate, much larger
    follow-on. What IS centralized here and in `reify_empty_container_
    literal` below is the narrower, already-identified recurring pattern:
    treating an unprovable/mismatched EMPTY literal as if guessing one
    concrete kind were safe."""
    if ctype not in _CONTAINER_KIND_TYPES:
        return None
    return {'MojoDict *': 'dict', 'MojoList *': 'list', 'MojoSet *': 'set', 'MojoBytes *': 'bytes'}[ctype]

def _is_empty_container_literal(node) -> bool:
    """True when `node` is a SYNTACTICALLY EMPTY container literal — `[]`,
    `()`, `{}`, `set()` — which carries no evidence of what it would hold.

    The same shape `reify_empty_container_literal` recognises, and for the
    same reason it needs its own test rather than reusing that one: an empty
    literal still has a STORAGE element type (`_infer_list_elem_type([])` is
    `'int64_t'`, so a local can be declared), it is just not a statement about
    the values. The consumer that needs the distinction is
    `_gen_ReturnStmt`'s publish of `_return_elem_types`, where treating that
    storage default as evidence routed a str-valued result through
    `mojo_repr_list_ints` and printed its slots as pointer decimals — see
    “A comprehension inside an `if` body loses its RESULT list's element type”.
    """
    if isinstance(node, (DictExpr, ListExpr, SetExpr, TupleExpr)):
        return not (getattr(node, 'elements', None)
                    or getattr(node, 'pairs', None))
    return False


def reify_empty_container_literal(gen, value_type: str, declared_type: str, value_node) -> str | None:
    """If `value_node` is a syntactically-EMPTY container literal (`{}`,
    `[]`, `set()`, `()`) whose default lowering (`value_type`) doesn't
    match the REAL declared/needed container kind (`declared_type`),
    return a freshly-constructed value of `declared_type` — the empty-
    literal shape carries no real evidence for ANY particular kind (an
    empty dict, list, and set are equally "nothing"), so building the
    kind the destination actually needs is always safe, unlike coercing
    (reinterpret-casting) the wrong one. Returns None when this doesn't
    apply (caller falls through to its normal coercion/cast path).

    Centralizes what were 3 independently-written copies of this same
    check (`_gen_stmt_AssignStmt` x2 in gimple_gen_stmts.py for a var-decl
    and a struct-field write, and `_lower_dict_method`'s `.get(k, default)`
    in gimple_gen_methods.py) — see commit 634852c, DESIGN.html R1/R2/R4."""
    if value_type == declared_type or declared_type not in _EMPTY_CONTAINER_CTOR:
        return None
    if not isinstance(value_node, (DictExpr, ListExpr, SetExpr, TupleExpr)):
        return None
    if getattr(value_node, 'elements', None) or getattr(value_node, 'pairs', None):
        return None
    return gen._new_val(declared_type, _EMPTY_CONTAINER_CTOR[declared_type])
_FLOAT_TYPES = {'double', 'float', '__fp16'}
# The `struct` module's module-level function surface, mapped to the C type
# each call's VALUE has. This is the SINGLE source of that answer, consulted by
# BOTH the authoritative lowering (`_lower_struct_module_call` in
# mojo/backend_gimple/emit_methods.py, which gates on these keys and returns
# these values) and the side-effect-free type ESTIMATOR (`_quick_type` in
# mojo/middle/resolve_shared.py, which writes the C prototype via
# `_collect_return_types`/`_infer_return_type`).
#
# The two MUST agree, and the reason is a value-identity bug, not a tidiness
# one: the estimator runs FIRST and its answer becomes the declared return
# type, so the body is then obliged to CONVERT its real value to whatever the
# prototype says. With no row consulted by the estimator, a function whose only
# `return` is `struct.Struct("<HH")` was declared `int64_t`, its body boxed the
# real `MojoStructFmt *` through `void *` to satisfy that prototype, and every
# consumer of the returned handle — including the `s.size` attribute read that
# emit_exprs.py routes to `mojo_struct_size` — degraded to
# `_mojo_dispatch_getattr` on an untyped value and raised AttributeError. A
# table only the lowering consulted would reopen exactly that hole the next
# time a function returns one of these calls.
#
# `calcsize` is listed even though `int64_t` is also the estimator's fallback:
# it is the lowering's real answer, and keeping it here is what lets the two
# sides be checked for agreement by construction rather than by coincidence.
_STRUCT_MODULE_FN_RETVALS = {
    'Struct': 'MojoStructFmt *',
    'calcsize': 'int64_t',
    'pack': 'MojoBytes *',
    'unpack': 'MojoList *',
    'unpack_from': 'MojoList *',
    'iter_unpack': 'MojoList *',
    'pack_into': 'int',
}
def _struct_value_codes(fmt: str | None):
    """The per-VALUE format codes of a const-foldable struct format string
    ('4h' -> ['h','h','h','h'], 'x' padding dropped, '10s' -> ['s']), or
    None if the format isn't statically known. Used to pick the right
    MojoList append (int vs double vs bytes-pointer) per argument and the
    element type of an unpack result.

    THE single implementation of the struct-format grammar. Mirrors the
    runtime's own format compiler (runtime/fire_runtime.c's
    mojo_struct_compile) code for code, so a codegen answer and a runtime
    answer cannot disagree; the runtime is the one that has to be right when
    they do, which is why its per-slot kinds are the ones recorded on the
    value (mojo_list_set_kinds) and this table is only ever used to decide
    statically.

    WHY THE BODY LIVES HERE AND NOT IN A DELEGATE. Merging integ (which
    introduced `_struct_format_codes` as the canonical name) with metal
    (which had relocated these three helpers into this module) briefly left
    TWO copies of the parser. Collapsing the duplicate by making THIS name a
    tail-call delegate to `_struct_format_codes` compiles standalone but
    breaks the whole-closure `mojoc`/`selfhost` build with

        resolve_shared.py:98: error: assignment to 'int64_t' from 'MojoList *'
        makes integer from pointer without a cast [-Wint-conversion]

    on `codes = _struct_value_codes(gen._try_const_fold_str(fmt_node))`.
    The self-hosted return-type inference reads a list LITERAL (`codes = []`
    below) as direct evidence that the result is a `MojoList *`; a function
    whose only `return` is a call to another function gives it nothing local
    to read, the local falls back to the int64_t default, and the assignment
    then mismatches. So the inference needs the `codes = []` to be in the
    function whose own return type is being decided -- which is why the
    duplicate was collapsed in THIS direction rather than the other.
    `_struct_format_codes` below delegates here, keeping both spellings
    working for their existing callers (`types.py` internally, and
    `emit_methods.py`'s shim).
    """
    if not isinstance(fmt, str):
        return None
    codes = []
    i, n = 0, len(fmt)
    if i < n and fmt[i] in '<>=!@':
        i += 1
    while i < n:
        c = fmt[i]
        if c in ' \t\n':
            i += 1
            continue
        count = None
        if c.isdigit():
            count = 0
            while i < n and fmt[i].isdigit():
                count = count * 10 + int(fmt[i]); i += 1
            if i >= n:
                return None
            c = fmt[i]
        i += 1
        if c not in 'xbBhHiIlLqQfds?c':
            return None
        if c in 'sc':
            codes.append('s')
        elif c == 'x':
            continue
        else:
            codes.extend([c] * (1 if count is None else count))
    return codes


def _struct_slot_kinds(codes):
    """Per-slot element kind for an unpack format: one of 'int'/'double'/
    'bytes' per value, in wire order.

    A `MojoList` holds ONE element ctype, which is why a format mixing ints
    and floats used to degrade wholesale to int64 slots — the float came
    back as its raw IEEE bits (`struct.unpack('<if', ...)` giving
    `1 4607182418800017408`). But the format string is a compile-time
    constant here, so each slot's real kind is statically known and only
    the CONTAINER is untyped. Recording the per-slot kinds lets every
    statically-indexed read of the result pick the right accessor for that
    slot: the subscript (emit_calls.py's MojoList branch), the `a, b = t`
    destructuring target (loops_shared._tuple_elem_value), and the
    whole-result repr (`_list_repr_fn` -> `mojo_repr_list_kinds`). It is a
    property of the VALUE, not of whether it was bound to a local; a read
    with no compile-time slot index (iteration, a computed subscript) still
    has no single right C type. That residue was closed in the RUNTIME, by
    moving the per-slot kinds onto the live `MojoList` (a side table keyed on
    its address) and boxing a read with no compile-time index — see
    `mojo_list_set_kinds` / `mojo_list_get_boxed` / `mojo_repr_boxed` in
    runtime/fire_runtime.c and `_lower_LambdaExpr`'s env-field block in
    emit_calls.py for the consumers.
    """
    out = []
    for c in codes or ():
        if c in 'fd':
            out.append('double')
        elif c == 's' or c == 'c':
            out.append('bytes')
        else:
            out.append('int')
    return out


def _struct_elem_ctype(codes):
    """Uniform MojoList element ctype for an unpack tuple, or 'int64_t'
    when the codes are mixed / unknown (the common integer-format case is
    exact; a genuinely mixed int+float format degrades to int64 slots).

    That degradation is now confined to reads with no compile-time slot
    index: `_struct_slot_kinds` carries the real per-slot kinds, and the
    subscript, the `a, b = t` destructuring target and the whole-result repr
    all consult it. See `_struct_slot_kinds` / `_struct_attr_format` in
    mojo/backend_gimple/emit_methods.py, which are where those consumers are
    written."""
    if not codes:
        return 'int64_t'
    kinds = set()
    for c in codes:
        if c in 'fd':
            kinds.add('double')
        elif c == 's':
            kinds.add('bytes')
        else:
            kinds.add('int')
    if kinds == {'double'}:
        return 'double'
    if kinds == {'bytes'}:
        return 'MojoBytes *'
    return 'int64_t'


# Python `math` name -> the C type that function returns in C, for the
# libm functions whose Python and C signatures are identical. The C symbol
# is the same name, so this table is ALSO the identity map that tells the
# backend which real symbol to call — gimple_codegen builds its
# BUILTIN_VALUE_MAP entries from these keys rather than restating the
# names, so "which C function" and "what does it return" cannot drift.
#
# `math` is not a resolvable module in this project
# (module_loader's `can_resolve_module_path('math')` is False), so these
# had no lowering at all: the name fell through `_safe_name` to a
# `mojo_<name>` stub that nothing defines, which linked only against the
# auto-stub (answering 0) and failed to link in a whole-closure build.
#
# Only functions that are genuinely 1:1 belong here. Deliberately ABSENT,
# each for a concrete reason:
#   - `round`    Python rounds half-to-EVEN and returns int for one arg;
#                C `round` rounds half-away-from-zero and returns double.
#   - `trunc`    kept (C trunc IS Python's math.trunc), but note `int()`
#                is the floor-based one — different function, different name.
#   - `degrees`/`radians`/`gcd`/`factorial`/`fsum`/`isqrt`/`dist`/`comb`/
#     `perm`/`prod`   no same-named C function; mapping them would be a lie.
#   - `frexp`/`modf`   return `double *` through an out-parameter, which
#                this single-type table cannot express.
#   - `pow` with integer arguments and `hypot` with >2 args are fine as
#     double (C promotes), so both stay.
_LIBM_FN_RETVALS = {
    'sqrt': 'double', 'exp': 'double', 'log': 'double', 'log2': 'double',
    'log10': 'double', 'sin': 'double', 'cos': 'double', 'tan': 'double',
    'asin': 'double', 'acos': 'double', 'atan': 'double', 'atan2': 'double',
    'sinh': 'double', 'cosh': 'double', 'tanh': 'double',
    'asinh': 'double', 'acosh': 'double', 'atanh': 'double',
    'pow': 'double', 'fabs': 'double', 'floor': 'double', 'ceil': 'double',
    'trunc': 'double', 'fmod': 'double', 'expm1': 'double', 'log1p': 'double',
    'cbrt': 'double', 'hypot': 'double', 'copysign': 'double',
    'erf': 'double', 'erfc': 'double', 'lgamma': 'double', 'tgamma': 'double',
    'ldexp': 'double', 'remainder': 'double', 'nextafter': 'double',
    'fma': 'double',
    # C returns int; Python returns bool, and _Bool would be the closer
    # match, but `int` is what the surrounding scalar conventions use for
    # a truth value and converts to either without a cast.
    'isnan': 'int', 'isinf': 'int', 'isfinite': 'int',
}

# The dispatch-table and type-table MODULE GLOBALS, with the C DECLARATION
# TYPE each one really has. ONE mapping, because four sites need this same fact
# and each used to carry its own hand-written copy -- and the copies drifted the
# moment the globals moved from `gimple_codegen.py` into `mojo/middle/types.py`
# under the module split, which is how "struct _mojo_middle_types_toplev has no
# member named '_TYPE_MAP'" happened.
#
# THE TYPE IS PART OF THE KEY'S ANSWER, and a bare "a dispatch table is a
# `MojoDict *`" is wrong for eleven of the twenty-four: ten are sets
# (`_CMP_OPS` is declared `_CMP_OPS: set` in `generated_dispatch.py`; the rest
# are `frozenset`s or `{...}` set literals) and two are plain strings and two
# are not containers at all. That mis-typing is not cosmetic. Each answer is
# written into the SHARED, bare-name-keyed `_global_c_decl_types`, and
# `_own_overlay_global_ctype`'s rule 1 ("a container cdecl beats a scalar
# own-conclusion") then lets it beat the OWNING module's own correct
# conclusion -- so module_loader's `_C_KEYWORDS = frozenset({...})` found
# `_global_c_decl_types['_C_KEYWORDS'] == 'MojoDict *'` and refused to coerce:
#
#     # ERROR: compiling imported module 'module_loader': cannot coerce
#     #   MojoSet * to MojoDict * (incompatible container kinds)
#
# for four modules of the self-host closure, `selfhost`/`mojoc` red.
#
# Read the global's own DEFINITION before adding a name -- a `{...}` literal
# with no `key: value` pairs is a SET, not a dict. `'int64_t'` is the BOX: the
# value is right and there is no typed accessor, which is the convention
# `_gscan_declare_global`'s own non-dispatch arms use for exactly that case
# (`_FIXED_ARRAY_ANN_RE` is a compiled regex; its pattern source lives in
# `_regex_patterns` and `.finditer()` is lowered from that string, so the
# object itself is never read at run time).
#
# `dispatch_table_global_ctype` below is the ONLY way out of this table, so
# membership ("is this one of ours?") and the type ("what C type is it?")
# cannot come apart the way a name-list-plus-a-parallel-type-list pair does.
_DISPATCH_TABLE_GLOBAL_CTYPES = {
    # ── dicts ──
    '_STMT_DISPATCH': 'MojoDict *',
    '_EXPR_DISPATCH': 'MojoDict *',
    '_BIN_OPS': 'MojoDict *',
    '_TYPE_MAP': 'MojoDict *',
    '_SIGNED': 'MojoDict *',
    '_UNSIGNED': 'MojoDict *',
    '_FLOAT': 'MojoDict *',
    '_LIBM_FN_RETVALS': 'MojoDict *',
    '_SELFHOST_EXTRA_FIELD_CACHE': 'MojoDict *',
    # ── `frozenset`s and `{...}` set literals ──
    '_CMP_OPS': 'MojoSet *',
    '_C_KEYWORDS': 'MojoSet *',
    '_C_RESERVED_FUNCS': 'MojoSet *',
    '_FORCE_RENAME_RESERVED': 'MojoSet *',
    '_CPP_KEYWORD_FIELDS': 'MojoSet *',
    '_C_PARAM_EXTRA_KEYWORDS': 'MojoSet *',
    '_PSEUDO_DUNDER_ATTRS': 'MojoSet *',
    '_LIST_RETURNING_METHODS': 'MojoSet *',
    '_STR_RETURNING_METHODS': 'MojoSet *',
    '_SCALAR_INT_TYPES': 'MojoSet *',
    '_SCALAR_FLOAT_TYPES': 'MojoSet *',
    # ── plain strings ──
    '_CPP_CALLABLE_CTYPE': 'char *',
    '_CPP_CALLABLE_CTYPE_1ARG': 'char *',
    '_UNKNOWN_FIELD_CTYPE': 'char *',
    # ── no typed accessor: the box ──
    '_FIXED_ARRAY_ANN_RE': 'int64_t',
}


# ---------------------------------------------------------------------------
# Modules whose CALLS this compiler answers from the SOURCE TEXT, at compile
# time, so the runtime value of a call on the module MARKER is never observed.
# ---------------------------------------------------------------------------

# `re` is the one today: `_gmi_phase17`'s `X = re.compile("...")` scan records
# the PATTERN against `X` (`gen._regex_patterns`), and `.finditer()` /
# `.findall()` on `X` are then lowered against that recorded pattern with
# `mojo_regex_*` — the value stored in `X` is a token and is never read.
#
# This table exists because that fact is load-bearing somewhere ELSE, and the
# somewhere else used to get it wrong. `import re` binds a module MARKER: an
# `int64_t` global initialised to 0 (`_root_globals.re = 0`), because
# `module_loader.can_resolve_module_path('re')` is false — that predicate asks
# whether there is MOJO SOURCE for a module under `TEST_PATH` or `std*`, and
# the real Python stdlib is neither. So `re.compile(...)` is genuinely stubbed
# to the marker, i.e. to 0, in the generated C — and that is CORRECT, because
# nothing reads it.
#
# `_uncompiled_module_marker`'s raise (see
# bugs/RUNTIME_argparse_is_stubbed_so_parse_args_consumers_crash.md) therefore
# has to exclude these modules: it answers “is this a marker for a module this
# compile never compiled”, which is true for `re` and irrelevant, because the
# compile-time recogniser already holds the answer. Raising there turned
# `for m in re.compile(r'[a-z]+').finditer(src)` into
# `NotImplementedError: re.compile: module 're' is not compiled into this
# binary` — on master that program prints its matches, so this is a regression
# caught by `test_silent_noop_iter.py::finditer_still_lowered`.
#
# ONE table, read by the recogniser that fills `_regex_patterns` AND by the
# predicate that decides not to raise, so “which modules are compile-time
# handled” has one answer. A second module only enters by being implemented
# here and in the recogniser together — which is the point.
_COMPILE_TIME_CALL_MODULES = frozenset({'re'})


def compile_time_call_module(module: str) -> bool:
    """Does this compiler answer `module.<name>(...)` from the SOURCE TEXT?

    True for `re` today — see `_COMPILE_TIME_CALL_MODULES`. A module in this
    set binds a 0 marker and every call on it is answered by a lowering that
    read the call's own arguments, so neither the marker's value nor the call's
    return value is observable. See that set's comment for the two readers
    that must agree and the regression that comes of it when they do not."""
    return module in _COMPILE_TIME_CALL_MODULES


def dispatch_table_global_ctype(name) -> str | None:
    """The C declaration type for the compiler-internal table global `name`,
    or None when it is not one of ours.

    ONE accessor for the whole table, rather than the table plus a names list:
    a `name -> ctype` mapping and a parallel `names` list can disagree, and
    that disagreement has been a build break twice (see
    `_DISPATCH_TABLE_GLOBAL_CTYPES`'s own comment) -- `selfhost` red with
    "cannot coerce MojoSet * to MojoDict *". `... is not None` is therefore
    also the ONE membership test, which is the other half of what a name list
    was for.

    A FUNCTION, and not a bare read of the dict at each call site: these sites
    are in other modules (`mojo/backend_gimple/module_gen.py`,
    `mojo/middle/module_shared.py`, `gimple_codegen.py`), and a cross-module
    call is the one shape that does not depend on how the self-hosted compiled
    path represents another module's globals. A module-level `dict.get` and a
    module-level `in` over a dict literal both happen to work there today; a
    cross-module ATTRIBUTE read of one does not, and a `tuple(<dict>)` /
    `set(<tuple>)` derived view of the table does not either, so neither this
    function nor its callers may be "simplified" into either."""
    return _DISPATCH_TABLE_GLOBAL_CTYPES.get(name)

_SCALAR_CTORS = {'Float32': 'float', 'Float64': 'double', 'Float16': '__fp16', 'BFloat16': '__fp16', 'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t', 'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t', 'Int': 'int64_t', 'UInt': 'uint64_t', 'Bool': '_Bool'}
_STR_WRAPPER_CTORS = frozenset({'StringSlice', 'StaticString'})

def _split_top_level_commas(s: str) -> list[str]:
    """Split `s` on commas that are not nested inside ([{ }]). Used to pull
    just the element-type segment out of a multi-arg bracket annotation like
    `UnsafePointer[X, SomeOrigin]` without splitting inside a nested `X` that
    itself contains a bracketed, comma-bearing type arg (e.g. `Tuple[Int, Int]`).

    This is fire_compiler.split_top_level_commas under the name this module's
    ~25 callers already use, and it is an ALIAS rather than a second copy: the
    same bracket-aware split serves a bracket annotation AND an
    unpacking-target string, and a trailing-comma 1-tuple target is only
    expressible if every reader drops the empty slot it leaves (see
    fire_compiler.py's "Unpacking-target representation" section). Two copies
    would be free to disagree about exactly that."""
    return split_top_level_commas(s)

def _class_attr_ctype(v) -> str | None:
    """C pointer type for a container-valued class-body attribute initializer
    (`MojoSet *` / `MojoDict *` / `MojoList *`), or None if the initializer
    isn't a container value. Handles both container LITERALS (set `{...}`,
    dict `{...}`, list `[...]`, tuple `(...)`) and container CONSTRUCTOR calls
    (`set(...)`, `frozenset(...)`, `dict(...)`, `list(...)`, and the runtime
    helpers) — the class-body `_X = frozenset({...})` pattern used all over
    this file for membership-test class attrs. Mirrors the container
    classification in `_collect_self_assigns` (CallExpr branch) so every site
    agrees on one answer."""
    if isinstance(v, SetExpr):
        return 'MojoSet *'
    if isinstance(v, DictExpr):
        return 'MojoDict *'
    if isinstance(v, (ListExpr, TupleExpr)):
        return 'MojoList *'
    if isinstance(v, CallExpr) and isinstance(v.func, IdentExpr):
        cn = v.func.name
        if cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
            return 'MojoSet *'
        if cn in ('dict', 'Dict', 'mojo_dict_new'):
            return 'MojoDict *'
        if cn in ('list', 'DynamicVector', 'mojo_list_new'):
            return 'MojoList *'
    if isinstance(v, CallExpr) and isinstance(v.func, MemberExpr) and isinstance(v.func.obj, IdentExpr) and (v.func.obj.name == 'struct') and (v.func.member == 'Struct'):
        return 'MojoStructFmt *'
    return None


def _struct_format_codes(fmt):
    """The per-VALUE format codes of a const-foldable struct format string
    ('4h' -> ['h','h','h','h'], 'x' padding dropped, '10s' -> ['s']), or
    None if the format isn't statically known.

    A THIN DELEGATE to `_struct_value_codes` beside it, which holds the one
    implementation of the grammar. This is the spelling
    `mojo/backend_gimple/emit_methods.py`'s shim uses; kept so the merge with
    integ need not touch its call sites, and so the grammar cannot come to
    exist in two places. See `_struct_value_codes` for why the implementation
    sits there rather than here."""
    return _struct_value_codes(fmt)

def _struct_literal_format(a) -> str | None:
    """The format string a `struct.*` call's format ARGUMENT node literally
    carries, or None for anything that is not a plain non-bytes string
    literal.

    The one place the "is this format statically known" bar is defined, for
    both callers: `struct.unpack(fmt, buf)`'s first argument and
    `struct.Struct(fmt)`'s single argument are the same question with the
    same answer, so they must not each grow their own reading of what a
    literal node looks like — that is how `_returns_kinds_valued` came to
    reach for `.value` on whatever node it was handed and crash with
    `AttributeError: 'IdentExpr' object has no attribute 'value'` on
    `struct.unpack(fmt, buf)` where `fmt` is a variable (zipfile,
    shutil, tempfile, importlib/resources/*).

    A bytes literal is None on purpose: `struct.unpack(b'<if', buf)` takes
    its format as bytes, and none of the callers' callers want to reason
    about that spelling here."""
    if isinstance(a, StringLiteral):
        val = a.value
        return val if isinstance(val, str) and not a.is_bytes else None
    return None


def _struct_format_is_mixed(fmt) -> bool:
    """True when a const-foldable struct format has values of more than one
    kind, i.e. its unpack result is a heterogeneous container. The
    condition the whole per-slot-kinds mechanism exists for: a uniform
    format's answer is the same through any accessor, so a format this
    rejects costs nothing."""
    codes = _struct_format_codes(fmt)
    if not codes:
        return False
    kinds = set()
    for c in codes:
        if c in 'fd':
            kinds.add('d')
        elif c == 's':
            kinds.add('s')
        else:
            kinds.add('i')
    return len(kinds) > 1


def _struct_ctor_format(v) -> str | None:
    """The const-folded format string of a `struct.Struct('<fmt>')`
    initializer, or None for anything else.

    A `struct.Struct` handle is a runtime `MojoStructFmt *`: the format
    travels inside it, not in the C type. A codegen that can read the
    format back out of the SOURCE recovers the per-slot kinds of that
    handle's `unpack` result, which is what a mixed format's float slot
    needs to be read as a float rather than as its raw IEEE-754 bits
    (`self.F.unpack(data)` with `var F = struct.Struct('<if')` is the case
    that motivated this: a class-attribute handle has no local name for the
    codegen to have recorded the format against).

    Only a literal format is answered, which is the same
    compile-time-constant bar the module-level `struct.unpack('<if', b)`
    path already uses. A computed format yields None, and the caller then
    has no static kinds — where the runtime's own record of the unpack
    result's per-slot kinds (runtime/fire_runtime.c's
    `mojo_list_set_kinds`) is what keeps the answer right."""
    if not (isinstance(v, CallExpr) and isinstance(v.func, MemberExpr)
            and isinstance(v.func.obj, IdentExpr)
            and v.func.obj.name == 'struct' and v.func.member == 'Struct'):
        return None
    if len(v.args) != 1 or getattr(v, 'kwargs', None):
        return None
    return _struct_literal_format(v.args[0])
_FIXED_ARRAY_ANN_RE = re.compile('^\\[\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*;\\s*([A-Za-z_0-9]+)\\s*\\]$')


def _is_dataclasses_module_ref(obj) -> bool:
    """True for an AST expression referencing the `dataclasses` module,
    written either bare (`dataclasses`) or through the
    `gimple_ctypes.dataclasses` alias `mojo/middle/resolve_shared.py` uses
    (`import mojo.middle.types as gimple_ctypes`). The
    `dataclasses.fields`/`is_dataclass`/`replace` interception and the
    `for f in dataclasses.fields(x)` loop tracking previously matched ONLY
    the bare-IdentExpr form, so the aliased form fell through to dynamic
    attribute access — `f.name` then raised `AttributeError('name')` and
    the compile silently bailed to an EMPTY `.ci` (repro:
    std/collections/deque.mojo, std/collections/bitset.mojo, many others)."""
    if isinstance(obj, IdentExpr):
        return obj.name == 'dataclasses'
    if isinstance(obj, MemberExpr) and isinstance(obj.obj, IdentExpr):
        return obj.member == 'dataclasses'
    return False

def _mojo_type(ann: str | type | None) -> str:
    if not ann:
        return 'int64_t'
    if isinstance(ann, type):
        ann = ann.__name__
    if isinstance(ann, str) and ann.startswith('__mlir_type.'):
        c = mlir.type_to_c(ann[len('__mlir_type.'):])
        if c is not None:
            return c
    if ' | ' in ann:
        parts = [p.strip() for p in ann.split(' | ')]
        non_none = [p for p in parts if p != 'None']
        if non_none:
            return _mojo_type(non_none[0])
        return 'int64_t'
    if isinstance(ann, str) and ann.endswith('()') and ('[' not in ann):
        base = ann[:-2].strip()
        if base in ('list', 'List', 'DynamicVector', 'Array'):
            return 'MojoList *'
        if base in ('dict', 'Dict'):
            return 'MojoDict *'
        if base in ('set', 'Set'):
            return 'MojoSet *'
    if isinstance(ann, str):
        _m = _FIXED_ARRAY_ANN_RE.match(ann.strip())
        if _m:
            return 'MojoList *'
    if '[' in ann:
        base, rest = ann.split('[', 1)
        inner = rest.rstrip(']').strip()
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            elem = _mojo_type(_split_top_level_commas(inner)[0].strip())
            return f'{elem} *'
        if base in ('List', 'list', 'InlineArray', 'Array'):
            # `Array[T, N]` — Mojo's fixed-size array — is a LIST at this
            # representation level, exactly like `List[T]`: one `MojoList *`
            # with an element type, no separate fixed-size struct. It was
            # missing here, so the annotation erased to `int64_t` and every
            # use lost its static container type. The visible damage was a
            # `for x in xs:` over an `Array[Int, N]`, where an untyped
            # iterable emits the runtime dict-or-list dispatch and the DICT
            # arm declares the loop variable `char *` (it is a key); the
            # later `var val = <a double>` in the same function then assigned
            # a double to that `char *` — "cannot convert to a pointer type"
            # in the stdlib's test_math.mojo. Also in
            # `_IMPORTED_STRUCT_SKIP_BASENAMES`, i.e. already agreed not to
            # be an ordinary imported struct.
            return 'MojoList *'
        if base in ('Dict', 'dict'):
            return 'MojoDict *'
        if base in ('Set', 'set'):
            return 'MojoSet *'
        if base in ('Span', 'StringSlice'):
            return 'Span *'
        if base == 'Optional':
            return _mojo_type(_split_top_level_commas(inner)[0].strip())
        ann = base
    if isinstance(ann, str) and len(ann) > 1 and (ann[0] == '*') and (ann[1] != '*'):
        inner = ann[1:].strip()
        if inner in _TYPE_MAP:
            return f'{_TYPE_MAP[inner]} *'
    t = _TYPE_MAP.get(ann)
    return t if t is not None else 'int64_t'

def _result_type(t1: str, t2: str) -> str:
    return TypeLattice.join(t1, t2)
_PTR_OUT_PARAM_SCALAR_ELEMS = frozenset({'int8_t', 'uint8_t', 'int16_t', 'uint16_t', 'int32_t', 'uint32_t', 'int64_t', 'uint64_t', 'int', 'unsigned', 'long', 'size_t', 'float', 'double', '_Bool'})

def _elem_type(ptr_type: str) -> str:
    """Strip one level of pointer to get element type."""
    if ptr_type.endswith(' *'):
        return ptr_type[:-2]
    if '*' in ptr_type:
        return ptr_type.replace('*', '').strip()
    return 'int64_t'
_STR_RETURNING_METHODS = {'replace', 'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'format', 'zfill', 'capitalize', 'title', 'join', 'swapcase', 'expandtabs', 'casefold', 'center', 'ljust', 'rjust', 'removeprefix', 'removesuffix'}
_LIST_RETURNING_METHODS = {'split', 'rsplit', 'splitlines'}
_C_ID_MAP = {'char *': 'charptr', 'void *': 'voidptr', '_Bool': 'bool'}

def _c_id(ctype: str) -> str:
    """Convert a C type to a valid identifier suffix (for helper function names)."""
    return _C_ID_MAP.get(ctype, ctype.replace(' ', '_').replace('*', 'ptr'))
_FNPTR_CTYPE_RE = re.compile('^(.*)\\(\\*\\)\\((.*)\\)$')

def _c_var_decl(ctype: str, name: str) -> str:
    """A variable declaration for `ctype name` (no trailing `;`) — almost
    always just `f"{ctype} {name}"`, EXCEPT a function-pointer ctype (e.g.
    `'void (*)(int64_t)'`, this file's own spelling for the resume_fn/
    destroy_fn parameters of runtime/fire_async_runtime.h's
    AsyncRT_DeviceContext_enqueueHostFunction(Range) stubs — see
    _LIBC_SIGS' entries for those two names), whose C declarator syntax
    embeds the variable NAME INSIDE the parentheses (`void (*name)
    (int64_t)`), not after the whole type spelling like every other C
    type. Every declaration site in this file (_new_temp, the one central
    spot every GIMPLE temp's declaration text is built) used to do the
    naive `f"{ctype} {name}"` unconditionally, which is syntactically
    invalid for a function-pointer ctype and corrupted GCC's parse of the
    rest of the file (a real, hand-verified bug, not a hypothetical one —
    found wiring up device_context.mojo's `_coro_resume_fn`/
    `_coro_destroy_fn` values through to this exact call site)."""
    m = _FNPTR_CTYPE_RE.match(ctype)
    if m:
        ret, params = (m.group(1).rstrip(), m.group(2))
        return f'{ret} (*{name})({params})'
    return f'{ctype} {name}'

def _printf_fmt(ctype: str) -> str:
    return TypeLattice.printf_fmt(ctype)

def _strip_mojo_param_modifiers(pname: str) -> str:
    """Strip Mojo parameter modifiers (inout, borrowed, owned, etc.) from parameter name.

    These modifiers are not valid in C and must be removed for code generation.
    Examples: 'inout self' → 'self', 'borrowed x' → 'x', 'owned data' → 'data'
    """
    modifiers = ('inout', 'borrowed', 'owned', 'borrow', 'out', 'mut', 'ref', 'read', 'copy')
    for mod in modifiers:
        if pname.startswith(mod + ' '):
            return pname[len(mod) + 1:].strip()
    return pname
_type_walk_cache: dict[int, str] = {}

def _walk_type_expr(node) -> str:
    """Recursively serialize an AST type expression to a canonical string.

    NOTE: intentionally NO `id(node)`-keyed memo cache. An earlier version
    cached results by `id(node)`, which is address-dependent: on the
    self-hosted path a freed node's address can be reused by a different
    node, so the cache returned the WRONG type string and two distinct
    method overloads hashed to the same/different suffix non-reproducibly
    (e.g. `NoneType___init___3cbddd` reference vs `_be49df` self-hosted for
    the same `Self._mlir_type` param, while the single-param overload
    matched). `_walk_type_expr` is tiny and only called during overload-id
    computation, so the cache bought little.
    """
    if node is None:
        return 'any'
    if isinstance(node, str):
        return node
    if isinstance(node, IdentExpr):
        result = node.name
    elif isinstance(node, SubscriptExpr):
        base = _walk_type_expr(node.obj)
        idx = node.index
        if isinstance(idx, TupleExpr):
            inner = ','.join((_walk_type_expr(e) for e in idx.elements))
        else:
            inner = _walk_type_expr(idx)
        result = f'{base}[{inner}]'
    elif isinstance(node, MemberExpr):
        result = f'{_walk_type_expr(node.obj)}.{node.member}'
    elif isinstance(node, TupleExpr):
        result = '(' + ','.join((_walk_type_expr(e) for e in node.elements)) + ')'
    elif isinstance(node, (IntLiteral, FloatLiteral)):
        result = str(node.value)
    elif isinstance(node, StringLiteral):
        result = f'"{node.value}"'
    else:
        # `FunctionDef.params` stores each type annotation as a PLAIN STRING
        # (not a parsed node) for the overwhelmingly common case. The
        # leading `isinstance(node, str)` above is unreliable self-hosted —
        # a `char *` argument frequently does NOT match the `str` runtime
        # tag — so a string annotation reached here and the old
        # `type(node).__name__` fallback produced the literal string
        # `'<type>'`. That made overload ids diverge
        # (`NoneType___init___be49df` vs the reference `_3cbddd`, sig
        # `self:any,value:<type>` vs `self:any,value:Self._mlir_type`).
        # `_as_str` re-views the value as a `char *`; for the (rare)
        # non-string fallback it is at worst the previous behaviour.
        result = _as_str(node)
    return result

def _param_sig_str(params: tuple) -> str:
    """Produce a canonical signature string from a (pname, ptype) tuple of params."""
    parts = []
    for pname, ptype in params:
        bare = pname.lstrip('*') if pname else ''
        type_str = _walk_type_expr(ptype)
        parts.append(f'{bare}:{type_str}')
    return ','.join(parts)
_overload_hash_registry: dict[str, str] = {}

def _method_overload_id(param_types: tuple, struct_name: str='', method_name: str='') -> str:
    """Generate a short stable hash ID for a method overload from its param types.

    Walks each param's type expression recursively, hashes the canonical
    string, and returns the first 6 hex digits as the suffix.
    Also registers the mapping in _overload_hash_registry for demangling.

    The hash is a hand-rolled polynomial over the signature's bytes, NOT
    `hashlib.md5` — the compiled/self-hosted backend has no md5 (it stubs),
    so EVERY overload of a name got the SAME suffix once `mojoc` ran its own
    codegen: `CStringSlice___init___cbf29c`, `_cbf29c_2`, `_cbf29c_3` where
    the reference emits distinct `_d264de`/`_76edc3`/`_10ada0`. Same shape
    and rationale as `emit_funcs.overload_suffix_for` (which already made
    this switch for free functions); both sides now agree because both use
    this function.
    """
    sig = _param_sig_str(param_types)
    _h = 0
    _i = 0
    _n = len(sig)
    while _i < _n:
        _c = sig[_i]
        if isinstance(_c, str):
            _c = ord(_c)
        _h = (_h * 31 + _c) & 0x7FFFFFFF
        _i = _i + 1
    _h = _h & 0xFFFFFF
    _out = ''
    _k = 0
    while _k < 6:
        _d = _h % 16
        _h = _h // 16
        if _d < 10:
            _out = chr(48 + _d) + _out
        else:
            _out = chr(87 + _d) + _out
        _k = _k + 1
    full = f'{struct_name}.{method_name}({sig})' if struct_name else sig
    _overload_hash_registry[_out] = full
    return f'_{_out}'

def _crc32_str(s: str) -> int:
    """Pure-Python CRC-32 (IEEE 802.3, reflected, poly 0xEDB88320) over a
    string's bytes — IDENTICAL to `zlib.crc32(s.encode())`.

    `zlib.crc32` is not available in the compiled/self-hosted backend (it
    stubs), so `_exc_type_id` returned 1 for EVERY exception class, emitting
    `mojo_exc_type_set (1)` where the reference emits the real crc32
    (`... (471634805)`; repro: std/test/builtin/test_issue_1004). The runtime
    HARDCODES crc32 tags for the builtin exceptions
    (runtime/fire_runtime.c), so the ids must stay real crc32 values — this
    reproduces them exactly on both paths. `ord()`/`& 0xFF` and the
    `while`-free inner 8-bit fold are all shapes the compiled backend already
    lowers (see overload_suffix_for / _method_overload_id)."""
    _crc = 0xFFFFFFFF
    for _ch in s:
        _b = ord(_ch) & 0xFF
        _crc = _crc ^ _b
        _bit = 0
        while _bit < 8:
            if _crc & 1:
                _crc = (_crc >> 1) ^ 0xEDB88320
            else:
                _crc = _crc >> 1
            _bit = _bit + 1
    return _crc ^ 0xFFFFFFFF

def demangle_overload(c_name: str) -> str:
    """Demangle a C function name with an overload hash suffix back to Mojo form.

    E.g. 'Bool___init___76baef' → 'Bool.__init__(self:any)'
    Returns the original c_name unchanged if no match is found.
    """
    import re as _re
    m = _re.search('___([0-9a-f]{6})$', c_name)
    if not m:
        return c_name
    h = m.group(1)
    sig = _overload_hash_registry.get(h)
    if not sig:
        return c_name
    base = c_name[:-7]
    return f'{base} ({sig})'
_BIN_OPS = _GD_BIN_OPS
_CMP_OPS = _GD_CMP_OPS
_TYPE_SIGNED = _GD_SIGNED
_TYPE_UNSIGNED = _GD_UNSIGNED
_TYPE_FLOAT = _GD_FLOAT
_COMMON_METHOD_NAMES = frozenset({'write_to', 'write_text', 'write', 'format', 'copy', 'fdopen', '__contains__', '__str__', '__repr__', '__len__', '__iter__', '__next__', '__eq__', '__ne__', '__lt__', '__le__', '__gt__', '__ge__', '__bool__', '__init__', '__copyinit__', '__moveinit__', '__del__', '__hash__', '__getitem__', '__setitem__', '__add__', '__sub__', '__mul__', '__call__'})
_C_KEYWORDS = frozenset({'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if', 'inline', 'int', 'long', 'register', 'restrict', 'return', 'short', 'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union', 'unsigned', 'void', 'volatile', 'while', '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic', '_Generic', '_Noreturn', '_Static_assert', '_Thread_local', 'nullptr', 'constexpr', 'thread_local', 'static_assert', 'typeof_unqual'})
_CPP_KEYWORD_FIELDS = frozenset({'operator', 'new', 'delete', 'class', 'template', 'typename', 'namespace', 'public', 'private', 'protected', 'virtual', 'this', 'try', 'catch', 'throw', 'const', 'true', 'false', 'and', 'or', 'not', 'xor', 'bool', 'compl', 'nullptr'})
_C_PARAM_EXTRA_KEYWORDS = frozenset({'asm', '__asm__', 'typeof', '__typeof__'})
_C_MACRO_NAMES = frozenset({'true', 'false', 'NULL', 'EOF', 'SEEK_SET', 'SEEK_CUR', 'SEEK_END', 'TMP_MAX', 'FILENAME_MAX', 'FOPEN_MAX', 'BUFSIZ', 'L_tmpnam', 'L_ctermid', 'stdin', 'stdout', 'stderr'})
_PSEUDO_DUNDER_ATTRS = frozenset({'__class__', '__dict__', '__module__', '__name__', '__qualname__', '__doc__', '__bases__', '__base__', '__mro__', '__annotations__', '__slots__', '__weakref__', '__flags__', '__basicsize__', '__dictoffset__'})


# Module attributes that have a real, CONTAINER or string C representation
# (as opposed to the scalar `int64_t` the generic dynamic-getattr dispatch
# reports for an attribute read on an unresolved module marker).
#
# Why this table exists at all, and why it is keyed here rather than left
# implicit in the two consumers: `_quick_type` (a static estimate consumed
# by return-type inference, call-site typing, and the `and`/`or` type
# join) and `_lower_MemberExpr` (the actual lowering) MUST agree about an
# expression's C type. When they disagree the result is not a clean error
# but a coercion of a real pointer through a scalar slot -- same bit
# pattern, no crash, silently wrong. Each has grown its own ad-hoc cases
# (see `_lower_MemberExpr`'s `sys.argv`, `os.sep`, `signal.SIGTERM` arms);
# an entry belongs HERE whenever the case is a plain "this attribute is
# this ctype" fact that both need, so neither restates it.
#
# Keys are `(module_name, member)`. Add an entry only when BOTH the type
# AND the emitted expression are settled; a case needing its own emit logic
# (a list built element-by-element, a call, a computed constant) stays in
# `_lower_MemberExpr` and must be given a matching `_quick_type` arm.
_MODULE_ATTR_CTYPES: dict = {
    # `os.environ` as a whole mapping. Lowered to a runtime call
    # (`mojo_environ_dict()`, a process-wide singleton) -- see
    # `_lower_MemberExpr`'s own comment for why this is NOT an
    # `ast_rewriter` rule. The per-key idioms are rewritten away before
    # either consumer sees them.
    ('os', 'environ'): 'MojoDict *',
}


def _module_attr_ctype(module_name, member) -> str:
    """The agreed C type of a modelled module attribute, or `''`."""
    if not module_name or not member:
        return ''
    return _MODULE_ATTR_CTYPES.get((module_name, member), '')

def _safe_field(name: str) -> str:
    """Sanitize struct field and parameter names that are C keywords or
    platform-macro names (see _C_MACRO_NAMES's `stdin`/`stdout`/`stderr`
    entries — a field named identically to a Darwin <stdio.h> object-like
    macro gets silently text-substituted before GCC/G++ parses it, exactly
    the same failure mode _c_field_name already guards for module globals
    and gimple_gen_infra.py's local-variable declarator already guards for
    locals; this is that same chokepoint for struct fields/parameters).
    Also covers C++-ONLY keywords (_CPP_KEYWORD_FIELDS): a field named
    `delete` (real: Lib/tempfile.py's `_TemporaryFileCloser.delete`) is a
    valid C identifier, so the .ci side compiles clean, but the compiled-
    generator .cpp preamble re-emits the same typedef and g++ rejects
    `bool delete;` outright ("expected unqualified-id before 'delete'").
    Every field emission AND every field access goes through this one
    function on both sides, so the rename is applied uniformly."""
    if name in _C_KEYWORDS or name in _C_PARAM_EXTRA_KEYWORDS or name in _C_MACRO_NAMES or (name in _CPP_KEYWORD_FIELDS):
        return f'_kw_{name}'
    return name
_C_RESERVED_FUNCS = frozenset({'exit', 'abort', 'write', 'read', 'close', 'malloc', 'calloc', 'realloc', 'free', 'printf', 'fprintf', 'snprintf', 'sprintf', 'dprintf', 'puts', 'putchar', 'memcpy', 'memmove', 'memset', 'memcmp', 'memchr', 'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat', 'strchr', 'strrchr', 'strstr', 'strtok', 'strerror', 'atoi', 'atol', 'atoll', 'atof', 'strtol', 'strtoll', 'strtod', 'strtof', 'setvbuf', 'setbuf', 'remainderf', 'remainderl', 'posix_spawn', 'posix_spawnp', 'index', 'rindex', 'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf', 'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f', 'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf', 'sqrt', 'sqrtf', 'cbrt', 'cbrtf', 'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f', 'fabs', 'fabsf', 'fmod', 'fmodf', 'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma', 'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff', 'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf', 'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf', 'nextafter', 'nextafterf', 'copysign', 'copysignf', 'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder', 'expm1', 'expm1f', 'log1p', 'log1pf', 'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf', 'j0', 'j1', 'y0', 'y1', 'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath', 'open', 'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush', 'getline', 'getdelim', 'fgets', 'fputs', 'feof', 'ferror', 'clearerr', 'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf', 'fdopen', 'popen', 'pclose', 'remove', 'rename', 'rand', 'srand', 'random', 'srandom', 'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork', 'execv', 'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown', 'unlink', 'rmdir', 'ioctl', 'fcntl', 'dup', 'dup2', 'pipe', 'dlopen', 'dlsym', 'dlclose', 'dlerror', 'access', 'stat', 'lstat', 'fstat', 'qsort', 'bsearch', 'abs', 'labs', 'llabs', 'fabsf', 'fmodf', 'sqrtf', 'powf', 'ceilf', 'floorf', 'roundf', 'truncf', 'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit', 'fpclassify', 'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower', 'toupper', 'tolower', 'strdup', 'strndup', 'strtok_r', # `clock_gettime` is deliberately NOT here: it takes a `struct timespec*`,
# and a struct is a frame blob that cannot cross the Mojo/C boundary --
# the same reason formal/hostmods/time.mojo omits localtime/gmtime/mktime.
# Its stdlib caller declares a mismatched signature, which a real
# prototype in scope turns into `conflicting types for 'clock_gettime'`.
'time', 'clock', 'difftime', 'clock_gettime_nsec_np',
    'mach_absolute_time', 'mktime', 'strftime', 'gmtime', 'localtime', 'signal', 'raise', '_end'})
_FORCE_RENAME_RESERVED = frozenset({'index', 'rindex', 'getenv', 'atol', 'frexp', 'abort'})
_IDENT_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'

def _replace_first_ident(text: str, old: str, new: str) -> str:
    """Replace the first STANDALONE occurrence of identifier `old` in `text`
    with `new`, preserving every other byte — the compiled-backend-safe
    replacement for `re.sub(r'\\b' + re.escape(old) + r'\\b', new, text,
    count=1)`.

    Under the self-hosted backend that regex silently replaced NOTHING:
    `re.escape` had no lowering at all and returned 0, so the pattern lost
    the identifier it was meant to anchor on, and the compiled `re.sub`
    runs through POSIX `regcomp`, where `\\b` isn't a word boundary on
    macOS (verified: `regexec` returns no-match for `\\bfoo\\b`, while the
    BSD spelling `[[:<:]]foo[[:>:]]` matches). The visible symptom was a
    bare `extern void assert_equal (...)` in the self-hosted output against
    the defining module's real `std_testing___init___assert_equal` — the
    largest single shim-vs-noshim `--dump` divergence class (see
    bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md).

    Plain `str.find`/slicing is identical on both sides, so callers no
    longer depend on the regex engine at all."""
    if not old:
        return text
    _l = len(old)
    _i = text.find(old)
    while _i >= 0:
        _j = _i + _l
        _ok_l = _i == 0 or _IDENT_CHARS.find(text[_i - 1:_i]) < 0
        _ok_r = _j >= len(text) or _IDENT_CHARS.find(text[_j:_j + 1]) < 0
        if _ok_l and _ok_r:
            return text[:_i] + new + text[_j:]
        _i = text.find(old, _j)
    return text

def _safe_name(name: str) -> str:
    if name.startswith('`') and name.endswith('`') and (len(name) > 2):
        name = name[1:-1]
        if name and name[0].isdigit():
            name = '_' + name
        import re as _re
        name = _re.sub('[^a-zA-Z0-9_]', '_', name)
    if name in _C_KEYWORDS or name in _C_RESERVED_FUNCS:
        return f'mojo_{name}'
    return name

def _stub_guard_name(name: str) -> str:
    """Canonical `_MOJO_STUB_<name>` C-preprocessor guard macro used
    throughout this file's auto-stub/extern-suppression scheme (weak
    function stubs, forward-decl externs, ctor stubs, struct typedefs all
    share ONE guard namespace so that a real definition/typedef for a
    symbol always wins over a later auto-generated stub of that SAME
    symbol — see every call site's own comment for the specific collision
    it guards against).

    Case-PRESERVING by design: `name` here is already a real, exact C
    identifier (a mangled function symbol or a struct name), and every
    call site's matching half compares against that same exact string —
    the shared-guard scheme has never relied on case-insensitive matching.
    Previously every call site independently upper-cased `name` before
    building the guard purely for SCREAMING_SNAKE_CASE macro style; that
    incidentally made the guard namespace case-INSENSITIVE, so two
    genuinely different symbols that only differ in case (e.g. the struct
    `Deque` — a local subclass — and the unrelated function `deque` — an
    unresolved `from collections import deque`) collided: the struct's
    `#define _MOJO_STUB_DEQUE` (emitted first) silently suppressed the
    `deque` function's own `#ifndef _MOJO_STUB_DEQUE` weak-stub block
    later in the same translation unit, leaving `deque` completely
    undeclared and producing `implicit declaration of function 'deque'`
    at every call site. See bugs/CODEGEN_generator_function_Lib_test_test_
    deque.md. Preserving case here removes the false collision while
    leaving every genuine (exact-name) dedup case unaffected."""
    return f'_MOJO_STUB_{name}'

def _c_field_name(name: str) -> str:
    """Convert a Mojo variable/module name to a valid C struct field name.
    Dots in module paths (e.g. 'std.sys') become underscores ('std__sys').

    Also renames names that collide with C preprocessor macros (e.g. a Mojo
    global named `SEEK_CUR`) or C keywords, mirroring the rename `_declare_var`
    already does for local variables. Without this, the field name is emitted
    verbatim into the generated struct (e.g. `int SEEK_CUR;` / `.SEEK_CUR = 1,`)
    and the *textual* macro substitution from <stdio.h> (`SEEK_CUR` -> `1`)
    turns it into invalid C (`int 1;`) before GCC ever parses it."""
    safe = re.sub('[^a-zA-Z0-9_]', '_', name)
    if safe in _C_PARAM_EXTRA_KEYWORDS or safe in _C_MACRO_NAMES:
        return f'_kw_{safe}'
    if safe in _C_KEYWORDS:
        return f'_{safe}'
    return safe

def _env_field_ctype(ci, vname: str) -> str:
    """The C type of closure `ci`'s ENV FIELD for `vname`.

    A capture the closure (or, for a shared sibling env, any member of the
    group) can REASSIGN is stored BY REFERENCE: `ClosureInfo.mut_names`
    holds its name, and the field is a POINTER to the owner's heap box, not
    the value. So the field's C type is the capture's declared type with one
    `*` on top — `count = 0` captured by a sibling that does `count += 1`
    is `int64_t * count`, not `int64_t count`.

    Every site that DECLARES a field or STORES into one has to agree on
    that, which is why the answer lives here rather than being spelled out
    at each of them: a struct emitted with one spelling and filled with
    another is a hard `-Wint-conversion` pair at every store, and the
    store is a different file from the typedef.

    Real, in `mojo/middle/offload.py`'s `rewrite_fused_loop`: `fusable`
    and `walk` are siblings that call each other, so `discover_closures`
    gives them ONE shared env whose `count` field is the by-reference
    `int64_t *`, and `_lower_outer_closure_call` — the sibling-to-sibling
    env copy — was loading `_env->count` into a temp typed from
    `ci.captures` (`int64_t`). The struct was right and the code was
    wrong, which gcc reports as a bare pointer/integer mismatch at
    `fused = fusable(st)`, thousands of lines from either half.
    """
    for _cap in (getattr(ci, 'captures', None) or []):
        if _as_str(_cap[0]) == vname:
            _ct = _as_str(_cap[1])
            if vname in (getattr(ci, 'mut_names', None) or ()):
                return f'{_ct} *'
            return _ct
    # Not a declared capture: the only question left is whether the name is
    # a by-reference one the capture list never spelled out.
    if vname in (getattr(ci, 'mut_names', None) or ()):
        return 'int64_t *'
    return 'int64_t'

_CPP_OPAQUE_PTR_STRUCTS = frozenset({'MojoList', 'MojoDict', 'MojoSet', 'MojoStr', 'MojoStrIter', 'MojoListIter', 'MojoDictIter', 'MojoSetIter', 'MojoGenerator', 'MojoAsync', 'MojoBoundMethod', 'PyObject', 'MojoCompletedProcess', 'MojoFileHandle'})
_FIXED_RUNTIME_STRUCT_NAMES = frozenset({'MojoBoundMethod', 'MojoGenerator', 'MojoAsync'})

def _import_targets(node) -> list:
    """All `(module, alias)` targets of an ImportStmt: the primary
    `node.module`/`node.alias` plus every extra comma-separated target from
    `import a, b, c` (`node.extra`). Every ImportStmt consumer that binds/
    declares a name must walk this full list, not just the primary target —
    shared here instead of re-deriving `[(module, alias)] + extra` at each
    call site."""
    out = [(_as_str(node.module), _as_str(node.alias))]
    for _pair in getattr(node, 'extra', None) or []:
        out.append((_as_str(_pair[0]), _as_str(_pair[1])))
    return out

def _import_local_names(node: ImportStmt) -> list:
    """The bound local name for each target of an ImportStmt — `alias or
    module` — as a plain `list[str]`.

    `node: ImportStmt` (NOT an unannotated param): on the self-hosted
    compiled path an unannotated `node` is `int64_t`, so `node.alias` /
    `node.module` below still lowered to a `_mojo_dispatch_getattr` whose
    boxed result `_as_str` could not recover — every top-level `import X`
    then registered a garbage local name (or none), so `_lower_IdentExpr`'s
    bare-name global-read branch never saw `X` and a `X.attr` receiver read
    fell to `(int64_t)0` (`import sys` in t1.mojo/t_argv.mojo/mojo_main.py,
    stage1-vs-stage2 parity break under MOJO_NO_SHIM=1).

    `_import_targets` returns `(module, alias)` tuples; a consumer that only
    needs the local name and does `alias if alias else module` on the
    UNPACKED tuple slots hits a self-hosted bug: the tuple's `None` alias
    slot boxes to a stray non-NULL pointer, so the ternary picks it and the
    "local name" becomes a decimal heap address. Reading `node.alias`
    DIRECTLY (not through a tuple) keeps `None` `None`. Homogeneous
    `list[str]` return preserves each entry as `char *`."""
    _al = _as_str(node.alias)
    out = [_al if _al else _as_str(node.module)]
    for _pair in getattr(node, 'extra', None) or []:
        _pa = _as_str(_pair[1])
        out.append(_pa if _pa else _as_str(_pair[0]))
    return out

def _fi_name(entry) -> str:
    """Name half of a `name|alias` composite (FromImportStmt.name_alias_strs).

    Built by explicit character concatenation, NOT `_s[:_i]` slicing:
    `_as_str()` on the slice result does NOT fix this (tried and
    confirmed still broken) -- `_as_str` is a compile-time type-hint
    with CPython identity semantics, not a runtime re-box, so it cannot
    repair a value whose underlying representation is genuinely
    different from an ordinarily-constructed string. A sliced string
    came back with a working `==`/correct `len()` but a corrupted dict-
    key hash self-hosted (confirmed via a per-file aside/bside sweep on
    gimple_exprtypes.py --dump: `exports.get(name)` missed for every
    ALIASED import name -- the ones needing this slice -- while plain,
    unsliced names looked up fine). Concatenating one character at a
    time is the established safe construction shape elsewhere this
    session (see gimple_gen_exprs.py's `_lower_StringLiteral`/`_lit_
    bytes` fixes)."""
    _s = _as_str(entry)
    _i = _s.find('|')
    if _i < 0:
        return _s
    _out = ''
    for _ci in range(_i):
        _out += _s[_ci]
    return _out

def _fi_alias(entry) -> str:
    """Alias half of a `name|alias` composite, or None when unaliased.
    Built by explicit character concatenation -- see `_fi_name`'s
    docstring for why, not `_s[_i+1:]` slicing."""
    _s = _as_str(entry)
    _i = _s.find('|')
    if _i < 0:
        return None
    _out = ''
    for _ci in range(_i + 1, len(_s)):
        _out += _s[_ci]
    if _out:
        return _out
    return None

def _fromimport_names(node) -> list:
    """`[(name, alias|None), ...]` for a FromImportStmt, every slot
    `_as_str`-viewed — `FromImportStmt.names` is `list[(str, str|None)]` but
    the alias slot erases to int64_t on the self-hosted backend, so a
    consumer unpacking `for name, alias in stmt.names:` reads a boxed
    pointer and feeds it to `_stub_guard_name(...)` / `imported_symbols[...]`
    as a decimal-stringified address (non-deterministic garbage C
    identifiers). Mirrors `_import_targets` for ImportStmt."""
    out = []
    for _pair in getattr(node, 'names', None) or []:
        out.append((_as_str(_pair[0]), _as_str(_pair[1])))
    return out

def _join_import_member(mod: str, name: str) -> str:
    """Canonical dotted string naming what `from mod import name` binds —
    the exact string _module_candidate_paths/_compile_imported_module must
    resolve (and the string _generator_home_api keys are built from), so a
    binding site and a defining module's own compile always derive the SAME
    module identity from one `from X import Y` statement.

    For an ABSOLUTE `mod` this is plain `mod + '.' + name` (`pkg` +
    `sub` -> `pkg.sub`) — unchanged from the historical f-string shape.

    For a RELATIVE `mod` consisting ONLY of leading dots, appending another
    separator dot would double-count the depth: `from . import sibling`
    (mod='.') spelled '.' + '.' + 'sibling' as '..sibling' reads as a
    level-2 name and resolves one directory TOO HIGH (or nowhere). Real
    Python binds `sibling` in the level-1 package — so concatenate
    directly: '.' + 'sibling' == '.sibling' (level 1) and '..' +
    'sibling2' == '..sibling2' (level 2). A suffixed relative mod keeps
    the separator: '.mod' + '.' + 'name' == '.mod.name' (level 1, suffix
    'mod.name') — exactly how myinterpreter.py's own relative-import rule
    splits dots-then-suffix."""
    if mod and (not mod.replace('.', '')):
        return mod + name
    return f'{mod}.{name}'

def _c_escape(s: str) -> str:
    """Escape a Mojo string-literal's content for the body of a C string literal.

    The source already uses C-style escapes (`\\n`, `\\t`, `\\\\`, ...), so those are
    passed through unchanged rather than having their backslash doubled — the old
    code did `replace('\\\\','\\\\\\\\')` first, turning `\\n` into a literal
    backslash-n in the output. Lone backslashes, quotes, and raw control chars are
    escaped. Non-ASCII bytes pass through untouched."""
    known = set('ntr"\\\'0abfv')
    out = []
    i, n = (0, len(s))
    while i < n:
        ch = s[i]
        if ch == '\\' and i + 1 < n and (s[i + 1] in known):
            out.append(ch)
            out.append(s[i + 1])
            i += 2
            continue
        if ch == '\\' and i + 1 < n and (s[i + 1] == 'x'):
            if i + 2 < n and s[i + 2] in '0123456789abcdefABCDEF':
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            else:
                out.append('\\\\x')
                i += 2
                continue
        if ch == '\\':
            out.append('\\\\')
            i += 1
            continue
        if ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '?':
            out.append('\\?')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)

def _str_literal_value_is_fstring(val: str) -> bool:
    """Does a raw StringLiteral.value (as the parser leaves it -- an
    f/t-string keeps its prefix+quotes, unlike a plain string, whose
    quotes the parser already strips at tokenize time -- see
    GimpleGen._decode_str_literal_text's own comment) look like an f- or
    t-string? Pure prefix-sniffing, factored out as its own free
    function (rather than inlined at its one call site) so any FUTURE
    caller that only needs the yes/no answer (not the fully decoded
    text GimpleGen._decode_str_literal_text also strips out) has
    somewhere to reuse it instead of re-deriving the same prefix-walk.
    Deliberately mirrors (but, for now, does not share code with)
    _decode_str_literal_text's identical prefix-walk -- that method is
    a hot, widely-used (4 call sites) instance method deep in the
    f-string/`%`-formatting lowering path; refactoring it to delegate
    here is out of scope for this fix (unrelated risk, see this
    codebase's "one careful step at a time" convention for exactly this
    kind of prescan/global-inference change)."""
    prefix = ''
    rest = val
    while rest and rest[0] in 'fFrRbBuUtT':
        prefix += rest[0]
        rest = rest[1:]
    return bool(rest) and rest[0] in ('"', "'") and any((c in 'fFtT' for c in prefix))

def _extract_init_expr(stmt_value) -> str:
    """Generate C initialization code for a module-level assignment RHS."""
    if stmt_value is None:
        return '0'
    if isinstance(stmt_value, IntLiteral):
        _il = _as_intlit_node(stmt_value)
        _v64 = _signed_int64(_as_int(_il.value))
        if -0x80000000 <= _v64 <= 0x7FFFFFFF:
            _raw = _as_str(_il.raw)
            if _raw:
                return _raw
            return str(_v64)
        return _signed_int64_c_literal(_v64)
    if isinstance(stmt_value, BoolLiteral):
        return '1' if _as_boollit_node(stmt_value).value else '0'
    if isinstance(stmt_value, DictExpr):
        if not stmt_value.pairs:
            return 'mojo_dict_new()'
        return '0'
    elif isinstance(stmt_value, ListExpr):
        if not stmt_value.elements:
            return 'mojo_list_new()'
        return '0'
    elif isinstance(stmt_value, SetExpr):
        if not stmt_value.elements:
            return 'mojo_set_new()'
        return '0'
    elif isinstance(stmt_value, StringLiteral):
        if _str_literal_value_is_fstring(stmt_value.value):
            return '0'
        return f'"{_c_escape(stmt_value.value)}"'
    elif isinstance(stmt_value, (CallExpr, IdentExpr)):
        return '0'
    else:
        return '0'

def _module_toplevel_name(module_name: str) -> str:
    """Generate a unique C function name for a module's initializer."""
    import re
    safe = re.sub('[^A-Za-z0-9_]', '_', module_name)
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return f'_{safe}_toplevel'

def _module_init_name(module_name: str) -> str:
    """Public, documented C symbol name for a *library* module's module-scope
    initializer (DYLIB_module_scope_never_executes, box.3d/game repo).

    A `fire dylib` build (emit_entry_points=False) never emits any `main()` —
    there is nothing in the produced .dylib's ABI that calls the module's own
    `_<module>_toplevel()` (see `_module_toplevel_name`), so every module-scope
    `var x = f()` / bare statement silently never ran. Two independent fixes
    ride on this same name: (1) it's exported so a C host has a documented,
    callable "run this module's scope now" entry point, and (2) it's also
    invoked automatically from a `__attribute__((constructor))` so a host that
    does nothing special still gets correct behavior (matches how the
    executable path already runs top-level code unconditionally at process
    start — see gen_module's `int main` wrapper). Both routes funnel through
    the SAME underlying `_<module>_toplevel()`, which is itself guarded by a
    one-shot static flag (see `_gen_toplevel`) so calling both the ctor and
    the exported name (or calling the exported name more than once) is safe,
    not a double-init bug."""
    import re
    safe = re.sub('[^A-Za-z0-9_]', '_', module_name)
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return f'{safe}_init'

def _used_idents_node(node) -> set[str]:
    """All IdentExpr names referenced in node; does NOT cross FunctionDef or
    LambdaExpr boundaries.

    Two rules, and the second one is what this function's structure exists to
    enforce:

    1. A name bound inside the subtree is not free. The explicit branches below
       handle the shapes that need that said out loud (Comprehension subtracts
       its generator targets, AssignStmt counts its target as a use, IfStmt
       walks elifs and else), because a generic field walk cannot tell a
       binding from a reference.
    2. A node type with no explicit branch is walked GENERICALLY over its
       dataclass fields, never silently reported as using nothing.

    Rule 2 was added 2026-09-30 because the function used to end in a bare
    `return set()`, which made an unhandled node type an UNDER-approximation:
    the free names inside it vanished, and `discover_closures` feeds this set
    straight into a closure's capture list (`used - inner_declared`), so a
    `comptime if`, a `comptime for`, a `match`, an `await` or a `yield` nested
    in a nested `def` with no explicit `[capture ...]` list produced a closure
    that did not capture what its body reads. 39 of the 67 AST dataclass node
    types had no branch. An over-approximation costs a slightly larger env and
    is absorbed by the existing `inner_declared` subtraction; an
    under-approximation is a wrong capture and a wrong read. Deliberately the
    same direction as ForStmt, which also does not subtract its loop variable.

    The generic walk must still not cross into a nested function or lambda, so
    those two return early above and are never reached by the fallback.
    """
    if node is None:
        return set()
    if isinstance(node, (list, tuple, set, frozenset)):
        rl: set = set()
        for item in node:
            rl |= _used_idents_node(item)
        return rl
    if isinstance(node, IdentExpr):
        return {node.name}
    if isinstance(node, FunctionDef):
        return set()
    if isinstance(node, LambdaExpr):
        # A closure boundary, for the same reason FunctionDef is one: the
        # nested callable's own capture analysis is a separate pass, and
        # counting its body's names here would make the ENCLOSING function
        # capture variables only the lambda needs.
        return set()
    if isinstance(node, BinaryOp):
        return _used_idents_node(node.left) | _used_idents_node(node.right)
    if isinstance(node, CompareChain):
        r = set()
        for o in node.operands:
            r |= _used_idents_node(o)
        return r
    if isinstance(node, UnaryOp):
        return _used_idents_node(node.operand)
    if isinstance(node, CallExpr):
        r = _used_idents_node(node.func)
        for a in node.args:
            r |= _used_idents_node(a)
        return r
    if isinstance(node, MemberExpr):
        return _used_idents_node(node.obj)
    if isinstance(node, SubscriptExpr):
        return _used_idents_node(node.obj) | _used_idents_node(node.index)
    if isinstance(node, SliceExpr):
        r = _used_idents_node(node.obj)
        if node.start:
            r |= _used_idents_node(node.start)
        if node.stop:
            r |= _used_idents_node(node.stop)
        return r
    if isinstance(node, TernaryExpr):
        return _used_idents_node(node.condition) | _used_idents_node(node.then_val) | _used_idents_node(node.else_val)
    if isinstance(node, WalrusExpr):
        return {node.name} | _used_idents_node(node.value)
    if isinstance(node, (ListExpr, SetExpr, TupleExpr)):
        r: set = set()
        for e in node.elements:
            r |= _used_idents_node(e)
        return r
    if isinstance(node, DictExpr):
        r2: set = set()
        for _kv in node.pairs:
            r2 |= _used_idents_node(_kv[0]) | _used_idents_node(_kv[1])
        return r2
    if isinstance(node, Comprehension):
        r3 = _used_idents_node(node.element)
        if getattr(node, 'key', None) is not None:
            r3 |= _used_idents_node(node.key)
        gen_vars: set = set()
        for g in node.generators:
            r3 |= _used_idents_node(g.iterable)
            tgt = g.target
            if isinstance(tgt, str):
                gen_vars.add(tgt)
            elif isinstance(tgt, (list, tuple)):
                for item in tgt:
                    if isinstance(item, str):
                        gen_vars.add(item)
                    elif hasattr(item, 'name'):
                        gen_vars.add(item.name)
            elif hasattr(tgt, 'name'):
                gen_vars.add(tgt.name)
        r3 -= gen_vars
        return r3
    if isinstance(node, (PassStmt, BreakStmt, ContinueStmt)):
        return set()
    if isinstance(node, ReturnStmt):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, RaiseStmt):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, ExprStmt):
        return _used_idents_node(node.value)
    if isinstance(node, AssertStmt):
        return _used_idents_node(node.value)
    if isinstance(node, VarDecl):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, AssignStmt):
        return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, AugAssignStmt):
        return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, MultiAssignStmt):
        r4 = _used_idents_node(node.value)
        for t in node.targets:
            r4 |= _used_idents_node(t)
        return r4
    if isinstance(node, IfStmt):
        r5 = _used_idents_node(node.condition)
        for s in node.then_body:
            r5 |= _used_idents_node(s)
        for _elif in node.elifs:
            for s in _elif[1]:
                r5 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body:
                r5 |= _used_idents_node(s)
        return r5
    if isinstance(node, MatchStmt):
        rm = _used_idents_node(node.subject)
        for case in node.cases:
            rm |= _used_idents_node(case)
        return rm
    if isinstance(node, MatchCase):
        # The guard and the body are free uses. The patterns contribute their
        # EVALUATED parts and then give back their bindings, which is what makes
        # `case mod.CONST` keep `mod` (a real read) while `case Int(v)` gives
        # back both `Int` and `v`. Getting this the other way round is what the
        # generic fallback would have done: a bare `case Int(v)` contributes
        # `Int` (a type name) and `v` (a fresh binding) as if the enclosing
        # function read both, and `discover_closures` would try to CAPTURE them.
        rc = _used_idents_node(node.patterns)
        if node.guard is not None:
            rc |= _used_idents_node(node.guard)
        for s in node.body:
            rc |= _used_idents_node(s)
        return rc - _match_pattern_bound(node.patterns)
    if isinstance(node, WhileStmt):
        r6 = _used_idents_node(node.condition)
        for s in node.body:
            r6 |= _used_idents_node(s)
        return r6
    if isinstance(node, ForStmt):
        r7 = _used_idents_node(node.iterable)
        for s in node.body:
            r7 |= _used_idents_node(s)
        return r7
    if isinstance(node, TryStmt):
        r8: set = set()
        for s in node.body:
            r8 |= _used_idents_node(s)
        for h in node.handlers:
            for s in h.body:
                r8 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body:
                r8 |= _used_idents_node(s)
        if node.finally_body:
            for s in node.finally_body:
                r8 |= _used_idents_node(s)
        return r8
    if isinstance(node, WithStmt):
        r9: set = set()
        for item in node.items:
            r9 |= _used_idents_node(item.expr)
        for s in node.body:
            r9 |= _used_idents_node(s)
        return r9
    return _used_idents_generic(node)


def _match_pattern_bound(patterns) -> set[str]:
    """The names a `case`'s patterns BIND, which are therefore not free uses.

    Follows `match` semantics rather than guessing: a bare name in a pattern is
    an irrefutable CAPTURE, not a comparison. So `case _`, `case other`,
    `case Int(v)`, `case [x, y, *rest]`, `case {"k": z}` and `case a as b` all
    bind every IdentExpr they contain, and none of those is a use of an
    enclosing name. A pattern that does compare against an existing name spells
    it as a dotted value pattern -- `case mod.CONST` -- and that is the one
    shape whose base must be KEPT, because `mod` really is read from the
    enclosing scope. It arrives as a MemberExpr, whose `member` is a plain str
    (the bound name, so nothing to add) and whose `obj` is the use, so
    MemberExpr is deliberately not descended into.

    Without this, every `match` in the new-modular syntax leaked its type names
    and its bindings into the enclosing function's free-name set.
    """
    bound: set = set()

    def go(p) -> None:
        if p is None or isinstance(p, (str, bytes, int, float, bool)):
            return
        if isinstance(p, (list, tuple)):
            for item in p:
                go(item)
            return
        if isinstance(p, IdentExpr):
            bound.add(p.name)
            return
        if isinstance(p, MemberExpr):
            return          # value pattern: obj is a use, member is the binding
        if dataclasses.is_dataclass(p):
            for f in dataclasses.fields(p):
                go(getattr(p, f.name, None))

    for pat in (patterns or ()):
        go(pat)
    return bound


def _used_idents_generic(node) -> set[str]:
    """Rule 2: walk an unhandled node's dataclass fields for IdentExpr names.

    Split out from `_used_idents_node` so the recursion is obviously total: this
    is the only exit from that function that does not depend on the node's type
    matching one of the branches above.

    Every child goes back through `_used_idents_node`, never through itself.
    That is the whole trick, and getting it wrong is silent: recursing into
    `_used_idents_generic` instead walks an `IdentExpr` as a dataclass, finds
    its `name` is a str, and returns NOTHING for it — so the generic path
    reported zero free names and looked like a clean, plausible result. Strings,
    ints, bools and None are not nodes and contribute nothing here, which is what
    makes a blind field walk safe: a `VarDecl.name` or an annotation spelled as a
    str cannot invent a use.

    Because children re-enter `_used_idents_node`, a handled grandchild still
    gets its specialised treatment (a `MatchStmt`'s case bodies reach ExprStmt
    and AssignStmt that way), and an unhandled great-grandchild falls back here
    again. Every step descends the tree, so this terminates.
    """
    if node is None or isinstance(node, (str, bytes, int, float, bool)):
        return set()
    if isinstance(node, (list, tuple, set, frozenset)):
        r: set = set()
        for item in node:
            r |= _used_idents_node(item)
        return r
    if not dataclasses.is_dataclass(node) or isinstance(node, (FunctionDef, LambdaExpr)):
        return set()
    out: set = set()
    for f in dataclasses.fields(node):
        out |= _used_idents_node(getattr(node, f.name, None))
    return out

def _compute_exc_descendants(all_struct_defs):
    """For each struct name, the set of all struct names that transitively
    inherit from it (including itself) — used so a compiled `except
    BaseError:` handler matches any raised subclass of BaseError, not just
    an exact type-tag match (see _gen_stmt_TryStmt's typed-dispatch loop).
    The interpreter gets the equivalent behavior by walking a MojoClass's
    `.bases` chain at catch time (myinterpreter.py's _matches_exc_type);
    the compiled path has no such runtime walk available (dispatch is
    static int comparisons against a fixed tag), so this precomputes the
    same answer once, at compile time, instead."""
    by_name = {s.name: s for s in all_struct_defs if isinstance(s, StructDef)}
    descendants = {name: {name} for name in by_name}
    for name, s in by_name.items():
        stack = list(getattr(s, 'bases', None) or [])
        seen = set()
        while stack:
            base_name = stack.pop()
            if base_name in seen:
                continue
            seen.add(base_name)
            if base_name in by_name:
                descendants.setdefault(base_name, {base_name}).add(name)
                stack.extend(getattr(by_name[base_name], 'bases', None) or [])
    return descendants

def _unpack_target_leaf_names(target: str) -> list:
    """Flatten a tuple-unpack target string (`'(a, b)'`,
    `'(a, (b, (c, d)))'`, ... — the exact text _parse_unpack_target
    preserves) into its LEAF variable names.

    `fire_compiler.for_target_names` under the name this module's callers
    already use, and an alias rather than a second walk: this is a
    representation fire_compiler.py OWNS (see its "Unpacking-target
    representation" section), and a second recursion over the same text is
    exactly where the `(a,)` / `(a)` confusion came from — this copy stripped
    the outer parens and recursed unconditionally, so it read a
    parenthesised single NAME as a one-slot group and a 1-tuple as the same
    thing. It is also what knows about the trailing comma."""
    return for_target_names(target)

def _declared_vars_body(stmts) -> set[str]:
    """Variables declared in a statement list (does not cross FunctionDef boundaries)."""
    result: set = set()
    for node in stmts:
        if isinstance(node, VarDecl):
            result.add(node.name)
        elif isinstance(node, ForStmt):
            tgt = node.target
            name = tgt if isinstance(tgt, str) else getattr(tgt, 'name', '')
            # Every target shape through the ONE leaf-name reader, with no
            # "is it parenthesised?" test of its own. That test is what this
            # used to do, and it is the reason a 1-tuple `'(a,)'` and a
            # parenthesised name `'(a)'` were indistinguishable here: both
            # took the paren branch and both produced the same one-element
            # set, which happened to be right for NAMES and is why the
            # distinction had to be pushed down to `for_target_is_tuple`
            # rather than fixed here.
            if isinstance(name, str) and name:
                result.update(_unpack_target_leaf_names(name))
            result |= _declared_vars_body(node.body)
        elif isinstance(node, IfStmt):
            result |= _declared_vars_body(node.then_body)
            for _elif in node.elifs:
                result |= _declared_vars_body(_elif[1])
            if node.else_body:
                result |= _declared_vars_body(node.else_body)
        elif isinstance(node, (WhileStmt, WithStmt)):
            result |= _declared_vars_body(node.body)
        elif isinstance(node, TryStmt):
            result |= _declared_vars_body(node.body)
            for h in node.handlers:
                if h.name:
                    result.add(h.name)
                result |= _declared_vars_body(h.body)
            if node.else_body:
                result |= _declared_vars_body(node.else_body)
            if node.finally_body:
                result |= _declared_vars_body(node.finally_body)
    return result
_CPP_CALLABLE_CTYPE = 'std::function<int64_t()>'
_CPP_CALLABLE_CTYPE_1ARG = 'std::function<int64_t(int64_t)>'