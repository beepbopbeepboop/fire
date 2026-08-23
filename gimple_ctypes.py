"""Shared C-type utilities and leaf constants for the GIMPLE backend.

Mechanically extracted from gimple_codegen.py (Wave-2 integration, M1).
Leaf-most module: stdlib imports only; every other gimple_* module may
import from here without cycles. Definitions are verbatim moves;
gimple_codegen re-imports them so unqualified internal references and
external `from gimple_codegen import X` keep working unchanged.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import zlib
import dataclasses

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    py_tokenize, Parser,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
from generated_dispatch import (
    _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT,
    _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS,
    _STMT_DISPATCH, _EXPR_DISPATCH,
)
def _debug_note(where: str, detail: object = '') -> None:
    """Report a deliberately-swallowed error on stderr when MOJO_DEBUG is set.

    Codegen degrades gracefully on some failures (module imports, type
    inference, generic instantiation).  Those paths intentionally continue
    with reduced information; this hook makes them diagnosable without
    changing compiler behavior for normal runs.
    """
    if os.environ.get('MOJO_DEBUG'):
        print(f"[gimple_codegen] {where}: {detail}", file=sys.stderr)

# ---------------------------------------------------------------------------
# TypeLattice — C11 usual arithmetic conversions + container helpers
# ---------------------------------------------------------------------------

class TypeLattice:
    """Numeric type promotion lattice for Mojo → C lowering.

    join(t1, t2) implements C11 usual-arithmetic-conversion rules:
      - If either operand is float, float wins; wider float wins.
      - If both are signed ints, wider wins.
      - If both are unsigned ints, wider wins.
      - If mixed signed/unsigned: if unsigned rank >= signed rank → unsigned; else signed.
    """

    _SIGNED   = _GD_SIGNED
    _UNSIGNED = _GD_UNSIGNED
    _FLOAT    = _GD_FLOAT

    @classmethod
    def is_float(cls, t: str) -> bool:    return t in cls._FLOAT
    @classmethod
    def is_signed(cls, t: str) -> bool:   return t in cls._SIGNED
    @classmethod
    def is_unsigned(cls, t: str) -> bool: return t in cls._UNSIGNED
    @classmethod
    def is_int(cls, t: str) -> bool:      return t in cls._SIGNED or t in cls._UNSIGNED
    @classmethod
    def is_numeric(cls, t: str) -> bool:  return cls.is_float(t) or cls.is_int(t)
    @classmethod
    def is_pointer(cls, t: str) -> bool:  return '*' in t
    @classmethod
    def is_bool(cls, t: str) -> bool:     return t == '_Bool'

    @classmethod
    def join(cls, t1: str, t2: str) -> str:
        """LUB for binary arithmetic result type."""
        if t1 == t2:
            return t1
        # _Bool promotes to int before further analysis
        if t1 == '_Bool': t1 = 'int'
        if t2 == '_Bool': t2 = 'int'
        if t1 == t2:
            return t1
        # Pointer: when two different pointer types meet, use int64_t (opaque handle)
        if cls.is_pointer(t1) or cls.is_pointer(t2):
            if cls.is_pointer(t1) and cls.is_pointer(t2):
                # Two different pointer types → opaque int64_t handle
                if t1 == 'void *' or t2 == 'void *':
                    return 'void *'
                if t1 == 'char *' or t2 == 'char *':
                    return 'char *'
                return 'int64_t'
            # One pointer, one non-pointer → use the pointer type
            return t1 if cls.is_pointer(t1) else t2
        # Float wins over int; wider float wins
        if cls.is_float(t1) or cls.is_float(t2):
            r1 = cls._FLOAT.get(t1, 0)
            r2 = cls._FLOAT.get(t2, 0)
            if r1 == 0: return t2   # t2 is the float
            if r2 == 0: return t1   # t1 is the float
            return t1 if r1 >= r2 else t2
        # Both integral
        rs1 = cls._SIGNED.get(t1, 0)
        rs2 = cls._SIGNED.get(t2, 0)
        ru1 = cls._UNSIGNED.get(t1, 0)
        ru2 = cls._UNSIGNED.get(t2, 0)
        if rs1 and rs2:  return t1 if rs1 >= rs2 else t2   # both signed
        if ru1 and ru2:  return t1 if ru1 >= ru2 else t2   # both unsigned
        if rs1 and ru2:  return t2 if ru2 >= rs1 else t1   # t1 signed, t2 unsigned
        if ru1 and rs2:  return t1 if ru1 >= rs2 else t2   # t1 unsigned, t2 signed
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
        # No-op casts between compatible int types
        if src in ('int', 'int64_t', '_Bool') and dst in ('int', 'int64_t', '_Bool'):
            if src == dst:
                return val
            return f"({dst}){val}"
        # _Bool → int: single cast is fine
        if src == '_Bool':
            if dst == 'int':
                return f"(int){val}"
            return f"({dst}){val}"
        # int → _Bool
        if dst == '_Bool':
            return f"(_Bool){val}"
        # pointer ↔ int64_t: go through void * for non-void pointers (GIMPLE requirement)
        if src.endswith(' *') and dst == 'int64_t':
            if src == 'void *':
                return f"(int64_t){val}"
            # Non-void pointer requires type tracking on unboxing (caller's responsibility)
            return f"(int64_t)(void *){val}"
        if src == 'int64_t' and dst.endswith(' *'):
            # CRITICAL: Unboxing int64_t to specific pointer type requires type validation
            # Safe only for: void * (generic handle)
            # UNSAFE: casting to specific types (char*, MojoDict*, etc) without verifying actual type
            if dst == 'void *':
                # void * is safe - it's a generic opaque handle
                return f"(void *){val}"
            # Casting int64_t to specific pointer type without validation is a silent type-safety bug
            raise TypeError(
                f"UNSAFE CAST: int64_t → {dst} requires type validation in _actual_types. "
                f"Call must verify via _actual_types[{val}] before casting. "
                f"Use (void *){val} as intermediate if truly generic."
            )
        return f"({dst}){val}"

    @classmethod
    def list_suffix(cls, elem: str) -> str:
        """Select 'int'/'double'/'str' API suffix based on element C type."""
        if elem in cls._FLOAT: return 'double'
        if elem == 'char *':   return 'str'
        return 'int'

    @classmethod
    def printf_fmt(cls, ctype: str) -> str:
        if ctype in ('double', 'float', '__fp16'): return '%g'
        if ctype == 'char *': return '%s'
        if ctype == 'char':   return '%c'
        if ctype == 'int64_t': return '%ld'
        if ctype == 'uint64_t': return '%lu'
        if ctype in ('unsigned int', 'uint32_t', 'uint16_t', 'uint8_t'): return '%u'
        return '%d'


_TYPE_MAP: dict[str | None, str] = {
    'Int':    'int64_t',
    'Int8':   'int8_t',
    'Int16':  'int16_t',
    'Int32':  'int32_t',
    'Int64':  'int64_t',
    'UInt':   'uint64_t',
    'UInt8':  'uint8_t',
    'UInt16': 'uint16_t',
    'UInt32': 'uint32_t',
    'UInt64': 'uint64_t',
    'Float16': '__fp16',
    'Float32': 'float',
    'Float64': 'double',
    # Bare Python `float` (e.g. FloatLiteral.value: float in mojo_compiler.py's
    # own AST node) had no entry at all — only the Mojo-style Float16/32/64
    # names above — so it silently fell through to the int64_t boxed-object
    # default. That default type made generic repr() call mojo_repr_int()
    # instead of mojo_repr_float() for a genuine float field, printing e.g.
    # `0.0` as `0` (also losing the fractional part entirely for any
    # non-whole float, since the double's bit pattern was reinterpreted as
    # an int64_t instead of read back as a double).
    'float':  'double',
    'Bool':   '_Bool',
    # Python-style `bool` flags cross the C ABI as `int` (e.g. compile_to_gimple's
    # do_imports — runtime header declares `int do_imports`). A flag is never a
    # boxed handle, so it must not hit the int64_t boxed-object default.
    'bool':   'int',
    'String': 'char *',
    'str':    'char *',
    'List':   'MojoList *',
    'list':   'MojoList *',
    'Dict':   'MojoDict *',
    'dict':   'MojoDict *',
    'Set':    'MojoSet *',
    'set':    'MojoSet *',
    'Str':    'MojoStr *',
    'None':   'void',
    # A boxed object reference (AST node child, dynamic value) is a 64-bit tagged
    # handle in this runtime, accessed via mojo_obj_getattr — never a 32-bit int.
    'object': 'int64_t',
    # No `None:` entry: MojoDict (this compiler's own dict representation,
    # once self-hosted) is string-keyed only — a literal `None` key crashes
    # building this dict at runtime (hashing a NULL key). Harmless to drop:
    # `_mojo_type`'s first line (`if not ann: return 'int64_t'`) already
    # short-circuits on None before ever reaching a `_TYPE_MAP` lookup, so
    # this entry was unreachable dead code, not a real default.
}

# Integer scalar C types. GIMPLE rejects ANY implicit conversion between two
# different integer types (not just narrowing): an int64_t ABI-widened
# parameter assigned into a uint8_t local is a "non-trivial conversion in
# 'parm_decl'" (std/builtin/dtype.mojo's `_match(self, mask: UInt8)` — the
# param is physically int64_t while its scalar-newtype semantic type is
# uint8_t), and the reverse (uint8_t -> int64_t) is rejected just as hard.
# The codegen must emit an explicit cast every time the *declared* C type of a
# value differs from the destination's C type.
_SCALAR_INT_TYPES = frozenset({
    'int', 'char', '_Bool',
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
})

# Return types of well-known runtime functions (seeds func_return_types)
_RUNTIME_FUNCS: dict[str, str] = {
    # exceptions (mojo_try_push is a macro, not a function)
    'mojo_exc_pop':               'void',
    'mojo_raise':                 'void',
    'mojo_exc_msg_set':           'void',
    'mojo_exc_msg_get':           'char *',
    # list
    'mojo_list_new':              'MojoList *',
    'mojo_list_len':              'int64_t',
    'mojo_list_get_int':          'int64_t',
    'mojo_list_get_double':       'double',
    'mojo_list_get_str':          'char *',
    'mojo_list_contains_int':     'int',
    'mojo_list_contains_double':  'int',
    'mojo_list_contains_str':     'int',
    'mojo_list_set_int':          'void',
    'mojo_list_set_double':       'void',
    'mojo_list_set_str':          'void',
    'mojo_list_slice':            'MojoList *',
    'mojo_list_concat':           'MojoList *',
    # dict
    'mojo_dict_new':              'MojoDict *',
    'mojo_dict_get_int':          'int64_t',
    'mojo_dict_get_double':       'double',
    'mojo_dict_get_str':          'char *',
    'mojo_dict_contains':         'int',
    'mojo_dict_len':              'int64_t',
    'mojo_dict_iter_new':         'MojoDictIter *',
    'mojo_dict_iter_next':        'int',
    'mojo_dict_iter_key':         'char *',
    'mojo_dict_iter_val_int':     'int64_t',
    'mojo_dict_iter_val_double':  'double',
    'mojo_dict_iter_val_str':     'char *',
    'mojo_dict_iter_free':        'void',
    # set
    'mojo_set_new':               'MojoSet *',
    'mojo_set_contains_int':      'int',
    'mojo_set_contains_str':      'int',
    'mojo_set_len':               'int64_t',
    'mojo_set_iter_new':          'MojoSetIter *',
    'mojo_set_iter_next':         'int',
    'mojo_set_iter_val_int':      'int64_t',
    'mojo_set_iter_val_str':      'char *',
    'mojo_set_iter_free':         'void',
    # string
    'mojo_str_new':               'MojoStr *',
    'mojo_str_concat':            'MojoStr *',
    'mojo_str_len':               'int64_t',
    'mojo_str_data':              'char *',
    'mojo_str_char_at':           'char',
    'mojo_str_eq':                'int',
    'mojo_str_contains':          'int',
    'mojo_str_slice':             'MojoStr *',
    'mojo_cstr_slice':            'char *',
    'mojo_cstr_region_eq':        'int',
    'mojo_str_from_char':         'MojoStr *',
    'mojo_str_repeat':            'MojoStr *',
    'mojo_str_to_int':            'int64_t',
    'mojo_str_to_float':          'double',
    # C-string utilities used by the REPL and string methods
    'input':          'char *',
    'string_lower':   'char *',
    'string_strip':   'char *',
    'string_upper':   'char *',
    'compile_to_gimple': 'char *',
    # Interpreter/bridge functions (provided by runtime or compiled code)
    'py_tokenize':           'MojoList *',
    'Parser':             'Parser *',    # Parser() constructor
    'Interpreter':        'Interpreter *',
}

_FLOAT_TYPES = {'double', 'float', '__fp16'}

def _split_top_level_commas(s: str) -> list[str]:
    """Split `s` on commas that are not nested inside ([{ }]). Used to pull
    just the element-type segment out of a multi-arg bracket annotation like
    `UnsafePointer[X, SomeOrigin]` without splitting inside a nested `X` that
    itself contains a bracketed, comma-bearing type arg (e.g. `Tuple[Int, Int]`)."""
    parts, depth, buf = [], 0, []
    for c in s:
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth = max(0, depth - 1)
        if c == ',' and depth == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(c)
    parts.append(''.join(buf))
    return parts


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
    return None


# Fixed-size-array struct-field-annotation shape: `var x: [ElemType; N]`
# (mojo_compiler.py's `_parse_type_ann_inner` LBRACKET branch captures the
# bracket contents verbatim via `_capture_bracketed_text`, which joins
# tokens with single spaces — so `[Block; MAX_BLOCKS]` round-trips as the
# string "[Block ; MAX_BLOCKS]"). `N` may be a decimal-literal size or a
# NAME referencing a module-level `comptime NAME: Int = <int-literal-or-
# foldable-expr>` constant (the common real-world shape, e.g. box.3d/game's
# `comptime MAX_BLOCKS: Int = 4096`) — see GimpleGen._module_const_int.
# See bugs/BUG-2026-008.md (box.3d/game) for the real-world motivating case.
_FIXED_ARRAY_ANN_RE = re.compile(
    r'^\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*([A-Za-z_0-9]+)\s*\]$')


def _mojo_type(ann: str | type | None) -> str:
    if not ann:
        return 'int64_t'  # Default to 64-bit signed integer
    if isinstance(ann, type):
        ann = ann.__name__
    # MLIR builtin types underlying the stdlib's scalar newtypes: __mlir_type.index, etc.
    if isinstance(ann, str) and ann.startswith('__mlir_type.'):
        c = mlir.type_to_c(ann[len('__mlir_type.'):])
        if c is not None:
            return c
    # Handle Union types: X | Y | ... → resolve to first non-None type
    if ' | ' in ann:
        parts = [p.strip() for p in ann.split(' | ')]
        non_none = [p for p in parts if p != 'None']
        if non_none:
            return _mojo_type(non_none[0])
        return 'int64_t'
    # Bare call-shaped container annotation with NO type parameter --
    # `var x: list()` / `var x: dict()` / `var x: set()`. This is this
    # project's own idiom for "a dynamically-typed container, element type
    # inferred from usage" (used throughout box.3d/game, e.g. `var
    # g_item_ids: list()` in game/lib/recipes.mojo) -- distinct from the
    # bracketed `List[T]`/`Dict[K,V]`/`Set[T]` form handled below. Before
    # this, the annotation text "list()" had NO branch here (no `[` in it),
    # fell straight through to `_TYPE_MAP.get(ann)`, found nothing, and
    # silently defaulted to plain `int64_t` -- so a `var names: list()`
    # global/local was declared as a scalar instead of `MojoList *`, and
    # any `.append()`/subscript/read against it treated whatever garbage
    # bits happened to be in that int64_t slot as a pointer: deterministic
    # SIGSEGV on first use. See _gen_stmt_VarDecl's matching "()"-suffix
    # branch, which also auto-allocates an empty container for this exact
    # annotation shape when there's no initializer -- getting the TYPE
    # right here alone isn't enough; the pointer still has to point
    # somewhere real.
    if isinstance(ann, str) and ann.endswith('()') and '[' not in ann:
        base = ann[:-2].strip()
        if base in ('list', 'List', 'DynamicVector'):
            return 'MojoList *'
        if base in ('dict', 'Dict'):
            return 'MojoDict *'
        if base in ('set', 'Set'):
            return 'MojoSet *'
    # Fixed-size array annotation spelling `[T; N]` (BUG-2026-008 family,
    # box.3d/game: `[Int; 9]` crafting grids, `[Block; MAX_BLOCKS]`). The
    # rest of this compiler ALREADY represents such arrays as boxed
    # MojoList handles end-to-end wherever it works today: array literals
    # lower to mojo_list_new()+append, subscript reads/writes route
    # through mojo_list_get_int/set_int, and PARAMS of this spelling
    # decay to an int64_t handle (_param_ctype's own path) that callees
    # cast back to MojoList*. But THIS mapper — the canonical return-type
    # / import-signature resolver both gimple_codegen._resolve_type and
    # module_loader._mojo_type_to_c delegate to — had NO branch for the
    # spelling, so a function RETURNING `[Int; 3]` was silently erased to
    # int64_t on BOTH the definition and every importer's forward decl.
    # Every subsequent subscript store on such a value then fell into the
    # opaque-int-container fallback ("check if it's a list or dict ...
    # default to dict") and emitted mojo_dict_set_int against raw scalar
    # garbage — mutations lost / SIGSEGV (test_crafting's 72 wood->planks
    # failures; minimal repro `g := make(); g[1] = 5; print(sum(g))`).
    # Mapping to MojoList* matches the representation every working part
    # of the pipeline already uses for this annotation shape.
    if isinstance(ann, str):
        _m = _FIXED_ARRAY_ANN_RE.match(ann.strip())
        if _m:
            return 'MojoList *'
    # Handle parameterized types: UnsafePointer[Int], List[Float64], etc.
    if '[' in ann:
        base, rest = ann.split('[', 1)
        inner = rest.rstrip(']').strip()
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            # `inner` may carry trailing origin/mut params (e.g. "X,
            # SomeOrigin") — only the first top-level segment is the element
            # type; passing the whole multi-arg string through never matches
            # _TYPE_MAP and silently defaulted to int64_t.
            elem = _mojo_type(_split_top_level_commas(inner)[0].strip())
            return f"{elem} *"
        if base in ('List', 'list', 'InlineArray'):
            return 'MojoList *'
        if base in ('Dict', 'dict'):
            return 'MojoDict *'
        if base in ('Set', 'set'):
            return 'MojoSet *'
        # Span / StringSlice are fat pointers {_data, _len}; model as a struct ptr
        # so .unsafe_ptr()/.__len__()/len() lower to field reads (see _seed_span).
        if base in ('Span', 'StringSlice'):
            return 'Span *'
        if base == 'Optional':
            # simplified: treat as the inner (first, if multi-arg) type
            return _mojo_type(_split_top_level_commas(inner)[0].strip())
        # NOTE: `Some[X]` (existential/trait-object params, e.g. `mut writer:
        # Some[Writer]`) is deliberately NOT special-cased here. It's the
        # overwhelmingly common type of the `writer` parameter in every
        # Writable.write_to method across the stdlib, and falling through to
        # the plain int64_t default is what makes `writer.write(...)` hit
        # _lower_method_call's int-receiver fd-write dispatch — which is right
        # for the common case (writing char*/string-like data). Giving it a
        # distinct type (e.g. void *) breaks every one of those call sites at
        # once (confirmed: 588->548 passing when tried). Fix the rare
        # non-string-argument case (test_interval.mojo) at the call site
        # instead — see the argument-type check in _lower_method_call.
        # Unknown parameterized type — fall through to plain lookup
        ann = base
    # Raw C-pointer annotation: `*Int8`, `*Int64`, `*Float32`, ... — Mojo's
    # `@cdecl` bridge-function pointer-parameter syntax (`fn f(buf: *Int8)`),
    # parsed by mojo_compiler.py's `_parse_type_ann_inner` as the literal
    # text "*" + base-type-name (see its "Handle * prefix" branch). This is
    # a DIFFERENT, concrete use of a leading '*' than the unbound generic
    # variadic-type-pack placeholder (`*Ts`, `*T`) that also parses to the
    # same "*"-prefixed shape — that placeholder's inner name is never a
    # real _TYPE_MAP key (it's a type-parameter name like `Ts`/`T`/`T0`), so
    # gating on an EXACT _TYPE_MAP hit (not a fallback/default resolution)
    # distinguishes the two without misfiring on the generic case.
    #
    # Before this, `*Int8`/`*Int64` fell straight through to the plain
    # `_TYPE_MAP.get(ann)` lookup below with the WHOLE "*Int8" string as the
    # key (never a match) and silently defaulted to plain `int64_t` — same
    # opaque scalar type as every other unresolved annotation. That made a
    # `buf: *Int8` parameter indistinguishable, at the type-resolution
    # layer, from a genuine boxed-int64_t handle. The real bug this caused:
    # `buf[i] = data[i]` (`game/lib/game_ffi.mojo`'s `ffi_get_item_name`,
    # and the same `out_id[] = ...`/`out_count[] = ...` pattern used by
    # nearly every OTHER @cdecl bridge function in that file) lowers
    # subscript-assignment on an `int64_t`-typed object through
    # `_gen_stmt_Assign`'s "opaque int-typed container" fallback, which can
    # only tell List from "default to Dict" — it has no third case for "a
    # genuine raw pointer", so it silently emitted `mojo_dict_set_int(...)`
    # against the caller's raw buffer pointer, an immediate EXC_BAD_ACCESS
    # the moment that pointer wasn't itself a live MojoDict (real repro:
    # `ffi_get_item_name(206, buf, 64)` segfaults inside `_dict_set_raw_seq`,
    # confirmed via lldb backtrace, even though the wrapped
    # `recipes_get_item_name` call one line above it returns the correct
    # string). Resolving `*Int8` to its real C type here (`int8_t *`) fixes
    # the root cause: `_gen_stmt_Assign`'s subscript-write lowering already
    # has a correct, working raw-pointer branch (`ot.endswith(' *')`, using
    # the generic `_mojo_at_<elem>` helper family) — it just never used to
    # be reached because `ot` was always the wrong, opaque `int64_t`.
    if isinstance(ann, str) and len(ann) > 1 and ann[0] == '*' and ann[1] != '*':
        inner = ann[1:].strip()
        if inner in _TYPE_MAP:
            return f"{_TYPE_MAP[inner]} *"
    t = _TYPE_MAP.get(ann)
    return t if t is not None else 'int64_t'

# Keep legacy helper name for backward compat inside this file
def _result_type(t1: str, t2: str) -> str:
    return TypeLattice.join(t1, t2)

# Element ctypes a pointer parameter may point at for _emit_call's
# BUG-2026-016 auto-address coercion to fire. Deliberately EXCLUDES 'char'
# (string parameters — an int64_t local holding a string handle must keep the
# legacy by-value pass-through; see the call-site comment) and every struct /
# container pointer type (opaque-handle territory). This is exactly the set
# _mojo_type produces for raw-pointer OUT-parameter annotations `*T` where T
# is numeric/boolean (`*UInt64` -> 'uint64_t *', `*Float64` -> 'double *', …).
_PTR_OUT_PARAM_SCALAR_ELEMS = frozenset({
    'int8_t', 'uint8_t', 'int16_t', 'uint16_t', 'int32_t', 'uint32_t',
    'int64_t', 'uint64_t', 'int', 'unsigned', 'long', 'size_t',
    'float', 'double', '_Bool',
})

def _elem_type(ptr_type: str) -> str:
    """Strip one level of pointer to get element type."""
    if ptr_type.endswith(' *'):
        return ptr_type[:-2]
    if '*' in ptr_type:
        return ptr_type.replace('*', '').strip()
    return 'int64_t'

# Well-known Python str methods whose return type is unconditionally str/list
# (never bool/int, unlike e.g. find()/startswith()) -- used ONLY to infer a
# struct field's C type from a chained method call in its __init__ assignment
# (`self.field = obj.attr.replace(...)`), where the call's func is a
# MemberExpr (not a bare IdentExpr the generic CallExpr-name dispatch above
# already recognizes) so it fell through to a blind 'int' default otherwise.
_STR_RETURNING_METHODS = {
    'replace', 'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'format',
    'zfill', 'capitalize', 'title', 'join', 'swapcase', 'expandtabs',
    'casefold', 'center', 'ljust', 'rjust', 'removeprefix', 'removesuffix',
}
_LIST_RETURNING_METHODS = {'split', 'rsplit', 'splitlines'}

_C_ID_MAP = {'char *': 'charptr', 'void *': 'voidptr', '_Bool': 'bool'}

def _c_id(ctype: str) -> str:
    """Convert a C type to a valid identifier suffix (for helper function names)."""
    return _C_ID_MAP.get(ctype, ctype.replace(' ', '_').replace('*', 'ptr'))

_FNPTR_CTYPE_RE = re.compile(r'^(.*)\(\*\)\((.*)\)$')

def _c_var_decl(ctype: str, name: str) -> str:
    """A variable declaration for `ctype name` (no trailing `;`) — almost
    always just `f"{ctype} {name}"`, EXCEPT a function-pointer ctype (e.g.
    `'void (*)(int64_t)'`, this file's own spelling for the resume_fn/
    destroy_fn parameters of runtime/mojo_async_runtime.h's
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
        ret, params = m.group(1).rstrip(), m.group(2)
        return f"{ret} (*{name})({params})"
    return f"{ctype} {name}"

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

# Cache for type-expression walk results, keyed by id() of AST node.
_type_walk_cache: dict[int, str] = {}

def _walk_type_expr(node) -> str:
    """Recursively serialize an AST type expression to a canonical string."""
    if node is None:
        return 'any'
    if isinstance(node, str):
        return node
    nid = id(node)
    cached = _type_walk_cache.get(nid)
    if cached is not None:
        return cached
    if isinstance(node, IdentExpr):
        result = node.name
    elif isinstance(node, SubscriptExpr):
        base = _walk_type_expr(node.obj)
        idx = node.index
        if isinstance(idx, TupleExpr):
            inner = ','.join(_walk_type_expr(e) for e in idx.elements)
        else:
            inner = _walk_type_expr(idx)
        result = f"{base}[{inner}]"
    elif isinstance(node, MemberExpr):
        result = f"{_walk_type_expr(node.obj)}.{node.member}"
    elif isinstance(node, TupleExpr):
        result = '(' + ','.join(_walk_type_expr(e) for e in node.elements) + ')'
    elif isinstance(node, (IntLiteral, FloatLiteral)):
        result = str(node.value)
    elif isinstance(node, StringLiteral):
        result = f'"{node.value}"'
    else:
        result = type(node).__name__
    _type_walk_cache[nid] = result
    return result

def _param_sig_str(params: tuple) -> str:
    """Produce a canonical signature string from a (pname, ptype) tuple of params."""
    parts = []
    for pname, ptype in params:
        bare = pname.lstrip('*') if pname else ''
        type_str = _walk_type_expr(ptype)
        parts.append(f"{bare}:{type_str}")
    return ','.join(parts)

# Registry mapping hash suffix (e.g. '76baef') → canonical param signature string.
# Populated by _method_overload_id so that tools like mojofilt can demangle
# a C symbol like 'Bool___init___76baef' back to 'Bool.__init__(self:any)'.
_overload_hash_registry: dict[str, str] = {}
def _method_overload_id(param_types: tuple, struct_name: str = '', method_name: str = '') -> str:
    """Generate a short stable hash ID for a method overload from its param types.

    Walks each param's type expression recursively, hashes the canonical
    string, and returns the first 6 hex digits as the suffix.
    Also registers the mapping in _overload_hash_registry for demangling.
    """
    sig = _param_sig_str(param_types)
    h = hashlib.md5(sig.encode(), usedforsecurity=False).hexdigest()[:6]
    # Store demangle info: hash → "StructName.method(sig)"
    full = f"{struct_name}.{method_name}({sig})" if struct_name else sig
    _overload_hash_registry[h] = full
    return f"_{h}"

def demangle_overload(c_name: str) -> str:
    """Demangle a C function name with an overload hash suffix back to Mojo form.

    E.g. 'Bool___init___76baef' → 'Bool.__init__(self:any)'
    Returns the original c_name unchanged if no match is found.
    """
    # Pattern: StructName___methodname___HASH (6 hex chars)
    import re as _re
    m = _re.search(r'___([0-9a-f]{6})$', c_name)
    if not m:
        return c_name
    h = m.group(1)
    sig = _overload_hash_registry.get(h)
    if not sig:
        return c_name
    # Reconstruct: strip the _HASH suffix and replace with the full Mojo form
    base = c_name[:-(7)]  # strip '___' + 6 chars
    return f"{base} ({sig})"

# ---------------------------------------------------------------------------
# Operator tables  (imported from generated_dispatch.py)
# ---------------------------------------------------------------------------

_BIN_OPS  = _GD_BIN_OPS   # Mojo op → C infix op; **, //, @ handled separately
_CMP_OPS  = _GD_CMP_OPS   # operators whose result type is _Bool

# ---------------------------------------------------------------------------


# C keyword avoidance
# ---------------------------------------------------------------------------

# Trait/dunder method names common across many types — excluded from the imported
# struct method-call gate (a `.write_to(`/`.__str__(` elsewhere must not veto a
# struct that's only field-accessed; these also have generic codegen handling).
_COMMON_METHOD_NAMES = frozenset({
    'write_to', 'write_text', 'write', 'format', 'copy', 'fdopen',
    '__contains__', '__str__', '__repr__', '__len__', '__iter__', '__next__',
    '__eq__', '__ne__', '__lt__', '__le__', '__gt__', '__ge__', '__bool__',
    '__init__', '__copyinit__', '__moveinit__', '__del__', '__hash__',
    '__getitem__', '__setitem__', '__add__', '__sub__', '__mul__', '__call__',
})

_C_KEYWORDS = frozenset({
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
    'inline', 'int', 'long', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
    'unsigned', 'void', 'volatile', 'while',
    '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic',
    '_Generic', '_Noreturn', '_Static_assert', '_Thread_local',
    # C23 keywords gcc-15 enforces in its default mode — a Mojo identifier named
    # any of these (e.g. `nullptr`) would otherwise emit invalid C.
    'nullptr', 'constexpr', 'thread_local', 'static_assert', 'typeof_unqual',
})

# Identifiers that are valid C but are C++ KEYWORDS (a .cpp generator-body
# translation unit must escape them `_kw_<name>` in its globals-struct field
# names — `operator`, `new`, `class`, ... — while the .ci side, genuinely C,
# keeps the raw name). See the generator .cpp globals-struct emission and
# _cpp_expr's module-global field reference.
_CPP_KEYWORD_FIELDS = frozenset({
    'operator', 'new', 'delete', 'class', 'template', 'typename',
    'namespace', 'public', 'private', 'protected', 'virtual', 'this',
    'try', 'catch', 'throw', 'const', 'true', 'false', 'and', 'or',
    'not', 'xor', 'bool', 'compl', 'nullptr',
})

# Extra identifiers that are valid C keywords in GCC but not in standard C keywords list
# (e.g. GCC extension 'asm', C++ keywords that GCC treats as reserved in C mode)
_C_PARAM_EXTRA_KEYWORDS = frozenset({'asm', '__asm__', 'typeof', '__typeof__'})

# C standard-library macros that expand to numeric constants — using them as identifiers
# causes the preprocessor to replace them before GCC sees the code (e.g. 'true' → '1').
_C_MACRO_NAMES = frozenset({
    'true', 'false', 'NULL', 'EOF', 'SEEK_SET', 'SEEK_CUR', 'SEEK_END',
    # <stdio.h> object-like macros: a Mojo global/field named identically
    # (e.g. tempfile.py's own module-level `TMP_MAX = 10000` constant)
    # gets silently text-substituted by the C preprocessor before GCC ever
    # parses the struct, turning `int TMP_MAX;` into `int 308915776;`
    # ("expected identifier ... before numeric constant") wherever it's
    # declared/accessed — same failure mode SEEK_CUR/SEEK_SET/SEEK_END
    # above already guard against, just from the rest of the same header.
    'TMP_MAX', 'FILENAME_MAX', 'FOPEN_MAX', 'BUFSIZ', 'L_tmpnam', 'L_ctermid',
})

# Python pseudo-attributes provided by the runtime/type machinery, NOT real
# instance fields — excluded from the "read-only field" struct inference so
# they aren't synthesized as garbage int fields (`__class__` is handled
# specially in _lower_MemberExpr; the rest are class/type metadata this
# codegen doesn't model per-instance). Genuine instance-attribute dunders that
# happen to be named with underscores — most importantly `__args__`/
# `__origin__`/`__parameters__`, which typing's generic aliases set as real
# attributes and read in subclasses like _CallableGenericAlias — are NOT
# listed here, so they DO register as fields (previously the read-scan
# excluded every `__x__` name, so those reads compiled to "has no member").
_PSEUDO_DUNDER_ATTRS = frozenset({
    '__class__', '__dict__', '__module__', '__name__', '__qualname__',
    '__doc__', '__bases__', '__base__', '__mro__', '__annotations__',
    '__slots__', '__weakref__', '__flags__', '__basicsize__', '__dictoffset__',
})


def _safe_field(name: str) -> str:
    """Sanitize struct field and parameter names that are C keywords."""
    if name in _C_KEYWORDS or name in _C_PARAM_EXTRA_KEYWORDS:
        return f'_kw_{name}'
    return name


# libc/system symbols a Mojo *function definition* must not shadow: the library
# itself defines e.g. `fn exit(...)` whose body calls libc `exit` via
# external_call. Emitting that as C `exit` would self-recurse and clash with the
# stdlib.h prototype. So a Mojo function with one of these names is mangled to
# `mojo_<name>` (definition AND call sites, via this chokepoint), while
# external_call keeps emitting the raw libc symbol.
_C_RESERVED_FUNCS = frozenset({
    # Core libc functions that Mojo stdlib may redefine.
    # At DEFINITION sites these are always renamed (fn abs → mojo_abs).
    # At CALL sites they are only renamed when a local definition exists
    # (see _lower_CallExpr: the rename is gated on func_return_types).
    'exit', 'abort', 'write', 'read', 'close',
    'malloc', 'calloc', 'realloc', 'free',
    'printf', 'fprintf', 'snprintf', 'sprintf', 'dprintf', 'puts', 'putchar',
    'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
    'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat',
    'strchr', 'strrchr', 'strstr', 'strtok', 'strerror',
    'atoi', 'atol', 'atoll', 'atof',
    'strtol', 'strtoll', 'strtod', 'strtof',
    'setvbuf', 'setbuf',
    'remainderf', 'remainderl',
    'posix_spawn', 'posix_spawnp',
    'index', 'rindex',
    # Math functions (from <math.h>) that the Mojo stdlib may redefine
    'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf',
    'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f',
    'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf',
    'sqrt', 'sqrtf', 'cbrt', 'cbrtf',
    'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf',
    'log2', 'log2f', 'log10', 'log10f',
    'fabs', 'fabsf', 'fmod', 'fmodf',
    'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma',
    'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff',
    'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf',
    'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf',
    'nextafter', 'nextafterf', 'copysign', 'copysignf',
    'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder',
    'expm1', 'expm1f', 'log1p', 'log1pf',
    'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf',
    'j0', 'j1', 'y0', 'y1',
    # Environment / system functions
    'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath',
    # File I/O
    'open',
    'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush',
    'getline', 'getdelim', 'fgets', 'fputs', 'feof', 'ferror', 'clearerr',
    'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf',
    'fdopen', 'popen', 'pclose',
    'remove', 'rename',
    # Random / stdlib math
    'rand', 'srand', 'random', 'srandom',
    # Process / unix
    'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork', 'execv',
    'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown', 'unlink', 'rmdir',
    'ioctl', 'fcntl', 'dup', 'dup2', 'pipe',
    # Dynamic linking
    'dlopen', 'dlsym', 'dlclose', 'dlerror',
    # Other stdlib
    'access', 'stat', 'lstat', 'fstat',
    'qsort', 'bsearch',
    # Integer / float math
    'abs', 'labs', 'llabs',
    'fabsf', 'fmodf', 'sqrtf', 'powf', 'ceilf', 'floorf', 'roundf', 'truncf',
    # Math classification macros (<math.h>)
    'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit', 'fpclassify',
    # ctype
    'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower',
    'toupper', 'tolower',
    # POSIX/BSD extras
    'strdup', 'strndup', 'strtok_r',
    # Time
    'time', 'clock', 'difftime', 'mktime', 'strftime',
    'gmtime', 'localtime',
    # Signal
    'signal', 'raise',
    # GCC GIMPLE FE keywords — calling these inside __GIMPLE triggers a parse error.
    '_end',
})

# Names in _C_RESERVED_FUNCS where the real libc signature is incompatible with how
# the Mojo stdlib prelude redefines them (return type, e.g. char *, or arity, e.g.
# atol(s, base) vs libc atol(s)) — so a call site with no local def or explicit import
# (the common case: these are prelude symbols, and we don't model implicit prelude
# imports) must still be treated as a Mojo call, not real libc. Always renamed to
# mojo_X, which needs a matching variadic stub in _util_pairs below.
_FORCE_RENAME_RESERVED = frozenset({'index', 'rindex', 'getenv', 'atol', 'frexp', 'abort'})


def _safe_name(name: str) -> str:
    # Handle backtick-quoted Mojo identifiers (e.g. `6bit` → _6bit)
    if name.startswith('`') and name.endswith('`') and len(name) > 2:
        name = name[1:-1]
        if name and name[0].isdigit():
            name = '_' + name
        # Replace any remaining non-C-identifier chars
        import re as _re
        name = _re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name in _C_KEYWORDS or name in _C_RESERVED_FUNCS:
        return f"mojo_{name}"
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
    # Use the module-level `re` (not `import re as _re` inside the body): the
    # self-hosted compiler stubs a function-scope `import re` (the compiled
    # binary can't import CPython's re module at runtime), which made the
    # compiled _c_field_name return "" for every input (`_re` was garbage) and
    # emit `struct __toplev` instead of `struct _root_toplev`. The module-level
    # `re` global's compile-time-known `.sub()` IS lowered.
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if safe in _C_PARAM_EXTRA_KEYWORDS or safe in _C_MACRO_NAMES:
        return f"_kw_{safe}"
    if safe in _C_KEYWORDS:
        return f"_{safe}"
    return safe


# Opaque runtime struct types whose `X *` form is a real, forward-declared C++
# type this compiler emits (so a module-global annotated with one — e.g.
# `x: MojoDict = {}` — can be typed as a pointer to it in a globals struct).
# A `X *` whose basename X is none of these AND not a user-defined mojo `struct`
# (checked against self.struct_field_types at the call site) is an opaque
# Python CLASS used only as a type annotation — emitting `X field;` would be
# an undeclared type — so such globals are forced to `void *`. See
# GimpleGen._cpp_known_ptr_struct.
_CPP_OPAQUE_PTR_STRUCTS = frozenset({
    'MojoList', 'MojoDict', 'MojoSet', 'MojoStr', 'MojoStrIter',
    'MojoListIter', 'MojoDictIter', 'MojoSetIter',
    'MojoGenerator', 'MojoAsync', 'MojoBoundMethod', 'PyObject',
    'MojoCompletedProcess', 'MojoFileHandle',
})

# Runtime-owned, FIXED-layout C structs this codegen itself defines (in
# runtime/mojo_runtime.h or its own emitted preamble), as opposed to a
# struct arising from a user's own `class`/`struct` statement (those are
# never hardcoded here — they're always discovered via StructDef
# processing into `self.struct_field_types`, which is mutable/extensible:
# a not-yet-seen field on a USER struct legitimately grows the struct, see
# `_collect_self_assigns`). A fixed-layout runtime struct has no such
# extensibility (`MojoBoundMethod` is exactly `{ void *fn; void *self; }`,
# hardcoded in mojo_runtime.h, forever) — an attribute name that isn't one
# of its real C fields must route through the same dynamic-attribute
# dispatch (`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr` ->
# `mojo_obj_getattr`/`mojo_setattr`'s real per-object storage, see
# bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md Step 4) instead
# of a direct `->member` access GCC would reject outright ("has no member
# named ..."). Confirmed real instance: `inner.__name__ = 'read_nonlocal'`
# / `f.__name__` on a `MojoBoundMethod` (Tools/scripts/var_access_
# benchmark.py) and `__del__._slotted = True` (Tools/c-analyzer/c_common/
# clsutil.py). `MojoGenerator`/`MojoAsync` are included per the same doc's
# plan even though both are fully opaque (`typedef struct MojoGenerator
# MojoGenerator;`, no C-visible fields at all) and so are not confirmed to
# ever reach this exact path in practice — harmless to list defensively;
# see `_struct_name_owner`'s cross-module collision guard for why a user
# struct can never collide with one of these names.
_FIXED_RUNTIME_STRUCT_NAMES = frozenset({
    'MojoBoundMethod', 'MojoGenerator', 'MojoAsync',
})


def _import_targets(node) -> list:
    """All `(module, alias)` targets of an ImportStmt: the primary
    `node.module`/`node.alias` plus every extra comma-separated target from
    `import a, b, c` (`node.extra`). Every ImportStmt consumer that binds/
    declares a name must walk this full list, not just the primary target —
    shared here instead of re-deriving `[(module, alias)] + extra` at each
    call site."""
    return [(node.module, node.alias)] + list(getattr(node, 'extra', None) or [])


def _c_escape(s: str) -> str:
    """Escape a Mojo string-literal's content for the body of a C string literal.

    The source already uses C-style escapes (`\\n`, `\\t`, `\\\\`, ...), so those are
    passed through unchanged rather than having their backslash doubled — the old
    code did `replace('\\\\','\\\\\\\\')` first, turning `\\n` into a literal
    backslash-n in the output. Lone backslashes, quotes, and raw control chars are
    escaped. Non-ASCII bytes pass through untouched."""
    known = set('ntr"\\\'0abfv')
    out = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '\\' and i + 1 < n and s[i + 1] in known:
            out.append(ch); out.append(s[i + 1]); i += 2; continue
        if ch == '\\' and i + 1 < n and s[i + 1] == 'x':
            # Only pass \x through if followed by valid hex digit(s)
            if i + 2 < n and s[i + 2] in '0123456789abcdefABCDEF':
                out.append(ch); out.append(s[i + 1]); i += 2; continue
            else:
                out.append('\\\\x'); i += 2; continue
        if ch == '\\':
            out.append('\\\\'); i += 1; continue
        if ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
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
    return bool(rest) and rest[0] in ('"', "'") and any(c in 'fFtT' for c in prefix)

def _extract_init_expr(stmt_value) -> str:
    """Generate C initialization code for a module-level assignment RHS."""
    if stmt_value is None:
        return '0'
    if isinstance(stmt_value, DictExpr):
        if not stmt_value.pairs:
            return 'mojo_dict_new()'
        return '0'  # Non-empty: needs runtime init in _toplevel
    elif isinstance(stmt_value, ListExpr):
        if not stmt_value.elements:
            return 'mojo_list_new()'
        return '0'
    elif isinstance(stmt_value, SetExpr):
        if not stmt_value.elements:
            return 'mojo_set_new()'
        return '0'
    elif isinstance(stmt_value, IntLiteral):
        return str(stmt_value.value)
    elif isinstance(stmt_value, BoolLiteral):
        return '1' if stmt_value.value else '0'
    elif isinstance(stmt_value, StringLiteral):
        # An f/t-string's raw `.value` is the UNDECODED source text,
        # INCLUDING its f/t prefix and quotes (real decoding + runtime
        # interpolation only happens at actual codegen time, in
        # _lower_StringLiteral) -- treating it as an ordinary compile-
        # time string constant here stuffed the literal, uninterpolated
        # source text (e.g. the raw characters `f"warning: {e}"`, quotes
        # and all) into a struct's static initializer: a type-incoherent
        # placeholder, not the real runtime value, and not even valid
        # source text for what the string SHOULD contain. Real
        # interpolation needs a runtime call (mojo_str_cat/etc, emitted
        # elsewhere for the real assignment), which can't appear in a C
        # static initializer, so defer to the same '0'-then-runtime-
        # assignment path already used for CallExpr/IdentExpr below. See
        # bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_
        # annotation.md, "Part 3".
        if _str_literal_value_is_fstring(stmt_value.value):
            return '0'
        return f'"{_c_escape(stmt_value.value)}"'
    elif isinstance(stmt_value, (CallExpr, IdentExpr)):
        return '0'  # Can't static-initialize; needs runtime init
    else:
        return '0'

def _module_toplevel_name(module_name: str) -> str:
    """Generate a unique C function name for a module's initializer."""
    import re
    safe = re.sub(r'[^A-Za-z0-9_]', '_', module_name)
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return f"_{safe}_toplevel"

def _module_init_name(module_name: str) -> str:
    """Public, documented C symbol name for a *library* module's module-scope
    initializer (bugs/DYLIB_module_scope_never_executes.md, box.3d/game repo).

    A `mojo dylib` build (emit_entry_points=False) never emits any `main()` —
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
    safe = re.sub(r'[^A-Za-z0-9_]', '_', module_name)
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return f"{safe}_init"

# ---------------------------------------------------------------------------
# Free-variable helpers (module level, used by closure pre-pass)
# ---------------------------------------------------------------------------


def _used_idents_node(node) -> set:
    """All IdentExpr names referenced in node; does NOT cross FunctionDef boundaries."""
    if node is None: return set()
    if isinstance(node, IdentExpr):         return {node.name}
    if isinstance(node, FunctionDef):        return set()
    if isinstance(node, BinaryOp):           return _used_idents_node(node.left) | _used_idents_node(node.right)
    if isinstance(node, CompareChain):
        r = set()
        for o in node.operands: r |= _used_idents_node(o)
        return r
    if isinstance(node, UnaryOp):            return _used_idents_node(node.operand)
    if isinstance(node, CallExpr):
        r = _used_idents_node(node.func)
        for a in node.args: r |= _used_idents_node(a)
        return r
    if isinstance(node, MemberExpr):         return _used_idents_node(node.obj)
    if isinstance(node, SubscriptExpr):      return _used_idents_node(node.obj) | _used_idents_node(node.index)
    if isinstance(node, SliceExpr):
        r = _used_idents_node(node.obj)
        if node.start: r |= _used_idents_node(node.start)
        if node.stop:  r |= _used_idents_node(node.stop)
        return r
    if isinstance(node, TernaryExpr):
        return (_used_idents_node(node.condition) | _used_idents_node(node.then_val)
                | _used_idents_node(node.else_val))
    if isinstance(node, WalrusExpr):
        return {node.name} | _used_idents_node(node.value)
    if isinstance(node, (ListExpr, SetExpr, TupleExpr)):
        r: set = set()
        for e in node.elements: r |= _used_idents_node(e)
        return r
    if isinstance(node, DictExpr):
        r2: set = set()
        for k, v in node.pairs: r2 |= _used_idents_node(k) | _used_idents_node(v)
        return r2
    if isinstance(node, Comprehension):
        r3 = _used_idents_node(node.element)
        # dict comprehension: field 'key' holds the value expression
        if getattr(node, 'key', None) is not None: r3 |= _used_idents_node(node.key)
        gen_vars: set = set()
        for g in node.generators:
            r3 |= _used_idents_node(g.iterable)
            # The iteration variable is locally scoped to the comprehension —
            # do not treat it as a free variable of the enclosing function.
            tgt = g.target
            if isinstance(tgt, str):
                gen_vars.add(tgt)
            elif isinstance(tgt, (list, tuple)):
                for item in tgt:
                    if isinstance(item, str): gen_vars.add(item)
                    elif hasattr(item, 'name'): gen_vars.add(item.name)
            elif hasattr(tgt, 'name'):
                gen_vars.add(tgt.name)
        r3 -= gen_vars
        return r3
    if isinstance(node, (PassStmt, BreakStmt, ContinueStmt)):   return set()
    if isinstance(node, ReturnStmt):    return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, RaiseStmt):     return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, ExprStmt):      return _used_idents_node(node.value)
    if isinstance(node, AssertStmt):    return _used_idents_node(node.value)
    if isinstance(node, VarDecl):       return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, AssignStmt):    return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, AugAssignStmt): return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, MultiAssignStmt):
        r4 = _used_idents_node(node.value)
        for t in node.targets: r4 |= _used_idents_node(t)
        return r4
    if isinstance(node, IfStmt):
        r5 = _used_idents_node(node.condition)
        for s in node.then_body: r5 |= _used_idents_node(s)
        for _, eb in node.elifs:
            for s in eb: r5 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body: r5 |= _used_idents_node(s)
        return r5
    if isinstance(node, WhileStmt):
        r6 = _used_idents_node(node.condition)
        for s in node.body: r6 |= _used_idents_node(s)
        return r6
    if isinstance(node, ForStmt):
        r7 = _used_idents_node(node.iterable)
        for s in node.body: r7 |= _used_idents_node(s)
        return r7
    if isinstance(node, TryStmt):
        r8: set = set()
        for s in node.body: r8 |= _used_idents_node(s)
        for h in node.handlers:
            for s in h.body: r8 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body: r8 |= _used_idents_node(s)
        if node.finally_body:
            for s in node.finally_body: r8 |= _used_idents_node(s)
        return r8
    if isinstance(node, WithStmt):
        r9: set = set()
        for item in node.items: r9 |= _used_idents_node(item.expr)
        for s in node.body: r9 |= _used_idents_node(s)
        return r9
    return set()


# (what `_cpp_expr`'s LambdaExpr case below emits) has an ANONYMOUS,
# uniquely-generated closure type that can only be held as `auto` -- not
# storable in a variable DECLARED ahead of its initializer, which is how
# every local in this coroutine model is declared (`Type name; ... name =
# value;`, needed because Python allows reassigning a name to a
# differently-shaped value across control-flow branches -- see
# `_genops`'s own `getpos = data.tell` / `getpos = lambda: None` in the
# hard-bug doc). `std::function<...>` is a real, nameable type a native
# C++ lambda implicitly converts INTO, so it can be declared up front like
# every other scalar ctype here, and — since this coroutine codegen
# already unconditionally `#include <functional>` (gen_module's .cpp
# preamble) — needs no new preamble plumbing either.
#
# Fixed to a zero-argument, int64_t-returning signature: the two confirmed
# real occurrences (`pickletools.py`'s `getpos = data.tell` / `= lambda:
# None`, called as `getpos()`; `fsutil.py`'s `get_files = lambda *a, **k:
# ...`, blocked by the SEPARATE `*`/`**`-forwarding gap regardless — see
# bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md) only
# ever need a 0-arg callable returning a scalar. Not generalized to
# arbitrary arity/return type without a second real occurrence to justify
# it (this project's own "recurs >= 2 times" bar for generalizing a narrow
# fix — see CLAUDE.md).
_CPP_CALLABLE_CTYPE = 'std::function<int64_t()>'

# A SIBLING declared-type category, for a single-parameter callable value —
# the same reasoning as `_CPP_CALLABLE_CTYPE` above (a real, nameable C++
# type a native capturing lambda implicitly converts into), fixed to a
# single int64_t (boxed) parameter for the same "matches this codegen's own
# boxed-value convention, no real per-arg type inference needed" reason
# `_CPP_CALLABLE_CTYPE` itself already documents. Kept as a SEPARATE named
# constant rather than generalizing `_CPP_CALLABLE_CTYPE` into a single
# arity-parametrized helper: the 0-arg category has exactly one real
# consumer shape (a bound-method/no-arg-lambda VALUE, called later as a
# plain `name()`) and the 1-arg category has a different one (a `key=`
# sort-comparator callable, invoked from newly-added inline `sorted()`
# codegen, never stored in a `declared`-map local in the one confirmed
# occurrence that needs it) — a single generalized constant would need
# every one of `_CPP_CALLABLE_CTYPE`'s existing consumers (the
# `_infer_simple_expr_ctype`/`_cpp_is_callable_value_expr` call-result-type
# special-casing) to also thread an arity/signature through, for no shape
# either confirmed occurrence actually needs today — consistent with this
# project's own "don't generalize past what the real corpus needs" bar
# (see `_CPP_CALLABLE_CTYPE`'s own docstring). A real second 1-arg
# consumer shape showing up later would be the trigger to reassess.
# Added for `Lib/enum.py`'s `Flag._iter_member_by_def_`:
# `sorted(cls._iter_member_by_value_(value), key=lambda m: m._sort_order_)`
# — see bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md's
# "single-parameter lambda" follow-up.
_CPP_CALLABLE_CTYPE_1ARG = 'std::function<int64_t(int64_t)>'
