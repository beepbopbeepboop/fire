"""The float8 scalar dtypes this compiler has no conversion/arithmetic rule for.

One table, read by both engines: the interpreter's type table
(`myinterpreter.py`, where the family resolves and `size_of` answers one byte)
and the compiled path (`mojo.middle.types._mojo_type` / `_dtype_token_ctype`
resolve an annotation naming one, and the two refusals live in
`mojo.backend_gimple.emit_resolve._safe_coerce_emit` for a conversion out of
the dtype and `mojo.backend_gimple.emit_exprs._lower_binary_tail` for a binary
operation with it).

What exists here is the NAME and its width, not an implementation: a scalar
whose dtype has no conversion or arithmetic rule must be refused where it is
used, with Modular's own wording —

    conversion from 'f8e3m4' to 'f32' is not implemented
    operation with a type 'f8e3m4' is not implemented

— instead of computing on it silently. The family is the one the canonical
`op_with_unsupported_type_error.mojo` case uses (`Float8_e3m4`); the compiled
path has no float8 STORAGE, so a value of one lowers to `double` under a
private C typedef (`__mojo_f8e3m4`, emitted into every translation unit by
`module_gen`'s preamble). The typedef only has to hold the value between the
refusals: a conversion to the dtype is allowed (Modular has one), and the two
uses with no rule are refused before C is emitted.

`formal/model/types.py`'s `NARROW_FLOAT_TYPE_NAMES` is the formal path's copy
of the same dtype family; this module is the one both production engines read,
so the interpreter and the compiled path cannot drift apart.
"""

#: The float8 family in `DType` order.
FLOAT8_TYPE_NAMES = (
    'Float8_e3m4', 'Float8_e4m3fn', 'Float8_e4m3fnuz',
    'Float8_e5m2', 'Float8_e5m2fnuz', 'Float8_e8m0fnu',
)

#: The lowered (IR) spelling of each member of `FLOAT8_TYPE_NAMES`, same
#: order. Modular words its diagnostics in these, and the compiled path's
#: private C typedef appends one to `_FLOAT8_CTYPE_PREFIX`.
FLOAT8_TYPE_SPELLINGS = (
    'f8e3m4', 'f8e4m3fn', 'f8e4m3fnuz',
    'f8e5m2', 'f8e5m2fnuz', 'f8e8m0fnu',
)

#: The lowered spelling of every scalar type either engine can name, keyed
#: by the Mojo scalar type name. Used for the `to '...'` half of a conversion
#: diagnostic (`f32`, `f64`, `i64`, ...); a declared type outside the table
#: is worded with the raw text the source (or the C type) wrote.
SCALAR_TYPE_SPELLINGS = {
    'Int': 'i64', 'Int8': 'i8', 'Int16': 'i16', 'Int32': 'i32', 'Int64': 'i64',
    'UInt': 'u64', 'UInt8': 'u8', 'UInt16': 'u16', 'UInt32': 'u32', 'UInt64': 'u64',
    'Float': 'f64', 'Float16': 'f16', 'Float32': 'f32', 'Float64': 'f64',
    'BFloat16': 'bf16', 'Bool': 'bool',
    'Float8_e3m4': 'f8e3m4', 'Float8_e4m3fn': 'f8e4m3fn',
    'Float8_e4m3fnuz': 'f8e4m3fnuz', 'Float8_e5m2': 'f8e5m2',
    'Float8_e5m2fnuz': 'f8e5m2fnuz', 'Float8_e8m0fnu': 'f8e8m0fnu',
}

#: The C type a scalar spelling already lowered to, for the target half of a
#: conversion diagnostic raised where only the C type is in hand (the
#: compiled path's coercion chokepoint).
CTYPE_SPELLINGS = {
    'int8_t': 'i8', 'int16_t': 'i16', 'int32_t': 'i32', 'int64_t': 'i64',
    'int': 'i32', 'unsigned': 'u32', 'long': 'i64',
    'uint8_t': 'u8', 'uint16_t': 'u16', 'uint32_t': 'u32', 'uint64_t': 'u64',
    'float': 'f32', 'double': 'f64', '__fp16': 'f16', '_Bool': 'bool',
}

#: The compiled path's private C type name for a float8 value is this prefix
#: plus the lowered spelling (`__mojo_f8e3m4`).
_FLOAT8_CTYPE_PREFIX = '__mojo_'


def _dtype_base(name) -> str:
    """`DType.float32`, `dtype.float32`, `.float32`, `Float32`, `f32` all
    normalize to the bare lowercase spelling (`float32` / `f32`)."""
    s = str(name).strip() if name is not None else ''
    if s.startswith('DType.'):
        s = s[len('DType.'):]
    elif s.startswith('dtype.'):
        s = s[len('dtype.'):]
    if s.startswith('.'):
        s = s[1:]
    return s.lower()


def float8_spelling(name) -> str | None:
    """The lowered spelling of `name` when it is a float8 dtype name, else None.

    Accepts every spelling the compiler's dtype readers accept: the scalar
    type name (`Float8_e3m4`, case-insensitive), the `DType.`/`dtype.`
    /leading-dot qualified form, and the lowered spelling itself (`f8e3m4`).
    """
    s = _dtype_base(name)
    if not s:
        return None
    i = 0
    while i < len(FLOAT8_TYPE_NAMES):
        if s == FLOAT8_TYPE_NAMES[i].lower() or s == FLOAT8_TYPE_SPELLINGS[i]:
            return FLOAT8_TYPE_SPELLINGS[i]
        i += 1
    return None


def float8_ctype(name) -> str | None:
    """The compiled path's C type for a float8 dtype name, or None.

    `float8_ctype('Float8_e3m4')` is `'__mojo_f8e3m4'`; nothing else returns
    a string. The token is distinct from `double` on purpose — it is what
    lets `_safe_coerce_emit` tell a store OF a float8 value (allowed) from a
    store OUT of one (the refused conversion).
    """
    sp = float8_spelling(name)
    if sp is None:
        return None
    return _FLOAT8_CTYPE_PREFIX + sp


def float8_spelling_of_ctype(ctype) -> str | None:
    """The lowered spelling when `ctype` is one of this module's C tokens."""
    s = str(ctype).strip() if ctype is not None else ''
    if not s.startswith(_FLOAT8_CTYPE_PREFIX):
        return None
    s = s[len(_FLOAT8_CTYPE_PREFIX):]
    i = 0
    while i < len(FLOAT8_TYPE_SPELLINGS):
        if s == FLOAT8_TYPE_SPELLINGS[i]:
            return s
        i += 1
    return None


def spelling_of_ctype(ctype) -> str:
    """The diagnostic spelling for a C type: its lowered dtype name when the
    table knows it (`float` -> `f32`), else the C type text itself."""
    s = str(ctype).strip() if ctype is not None else ''
    sp = float8_spelling_of_ctype(s)
    if sp is not None:
        return sp
    if s in CTYPE_SPELLINGS:
        return CTYPE_SPELLINGS[s]
    return s


def c_typedef_lines() -> list:
    """The preamble lines that name the compiled path's float8 C types.

    Every generated translation unit includes them (`module_gen`'s preamble),
    so an unguarded use still type-checks as the value's own `double`
    representation rather than failing with an unknown type name.
    """
    out = []
    i = 0
    while i < len(FLOAT8_TYPE_SPELLINGS):
        out.append('typedef double ' + _FLOAT8_CTYPE_PREFIX
                   + FLOAT8_TYPE_SPELLINGS[i] + ';')
        i += 1
    return out


def conversion_message(src_spelling, dst_spelling) -> str:
    """Modular's "no conversion rule" wording, without the `error:` prefix.

    The interpreter's diagnostics carry their own `file:line:col: error:`
    prefix (and the message field of a `mojo_record` is the bare text), while
    the compiled path raises the whole diagnostic as the exception text; both
    read this one wording.
    """
    return ("conversion from '" + str(src_spelling) + "' to '"
            + str(dst_spelling) + "' is not implemented")


def conversion_diagnostic(src_spelling, dst_spelling) -> str:
    """The compiled path's whole conversion diagnostic."""
    return 'error: ' + conversion_message(src_spelling, dst_spelling)


def operation_message(spelling) -> str:
    """Modular's "no arithmetic rule" wording, without the `error:` prefix."""
    return ("operation with a type '" + str(spelling) + "' is not implemented")


def operation_diagnostic(spelling) -> str:
    """The compiled path's whole operation diagnostic."""
    return 'error: ' + operation_message(spelling)

