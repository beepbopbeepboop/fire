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



# ── Numeric semantics ────────────────────────────────────────────────────
#
# What the family DOES compute, measured against the real Mojo compiler
# (`tools/mojo`, 2026-11-17):
#   * `e3m4` has comparisons and negation, `to_bits`, and construction from
#     a float, but NO arithmetic (`a + b` refuses: the operation converts
#     through f32, which `e3m4` has no rule for) and NO conversion to f32
#     (`Float32(a)` refuses). Its only float conversion is to bf16.
#   * The other five formats have arithmetic and conversions. Each result of
#     an operation is rounded to the format (`1.0 + 0.0625` in e4m3fn is 1.0).
#
# A format's values are fixed by four numbers and a kind: exponent bits,
# mantissa bits, bias, and how the top exponent is spent. `FLOAT8_FORMATS`
# is that single table; the compiled path passes the same four numbers to its
# runtime rounding routine, and the interpreter reads them here.

#: spelling -> (exponent bits, mantissa bits, bias, kind). The kinds:
#:   'ieee'  top exponent is inf / NaN                       (e3m4, e5m2)
#:   'fn'    no inf; the single all-ones pattern is NaN       (e4m3fn)
#:   'fnuz'  no inf, no negative zero; 0x80 is the only NaN   (e4m3fnuz, e5m2fnuz)
#:   'ue8m0' unsigned power of two; all-ones exponent is NaN  (e8m0fnu)
FLOAT8_FORMATS = {
    'f8e3m4':   (3, 4, 3, 'ieee'),
    'f8e4m3fn': (4, 3, 7, 'fn'),
    'f8e4m3fnuz': (4, 3, 8, 'fnuz'),
    'f8e5m2':   (5, 2, 15, 'ieee'),
    'f8e5m2fnuz': (5, 2, 16, 'fnuz'),
    'f8e8m0fnu': (8, 0, 127, 'ue8m0'),
}


def float8_format(spelling):
    """(ebits, mbits, bias, kind) for a lowered float8 spelling, or None."""
    return FLOAT8_FORMATS.get(spelling)


def has_arithmetic(spelling) -> bool:
    """Whether an operation on this float8 dtype has a rule (Modular's `e3m4`
    has none: arithmetic converts through f32, which it cannot)."""
    return spelling in FLOAT8_FORMATS and spelling != 'f8e3m4'


def has_float_conversion(spelling, target_spelling) -> bool:
    """Whether `float8 -> target_spelling` (a float dtype) has a rule. The only
    refused one is e3m4 to anything but bf16 (measured: e3m4 -> f32 refuses,
    e3m4 -> bf16 does not)."""
    if spelling != 'f8e3m4':
        return True
    return target_spelling == 'bf16'


def _decode(bits, fmt):
    """The real value of one bit pattern of a format, or None for a NaN."""
    ebits, mbits, bias, kind = fmt
    if kind == 'ue8m0':
        if bits == 0xFF:
            return None
        return 2.0 ** (bits - bias)
    total = 1 + ebits + mbits
    sign = -1.0 if (bits >> (total - 1)) & 1 else 1.0
    e = (bits >> mbits) & ((1 << ebits) - 1)
    m = bits & ((1 << mbits) - 1)
    if kind == 'fnuz':
        if bits == 0x80:
            return None
    elif kind == 'fn':
        if e == (1 << ebits) - 1 and m == (1 << mbits) - 1:
            return None
    elif kind == 'ieee':
        if e == (1 << ebits) - 1:
            return None if m else sign * float('inf')
    if e == 0:
        return sign * (m / (1 << mbits)) * 2.0 ** (1 - bias)
    return sign * (1.0 + m / (1 << mbits)) * 2.0 ** (e - bias)


def finite_values(spelling):
    """Every finite value of a format, ascending, each with the bit pattern
    that encodes it (the pattern's LSB decides ties, as round-to-even does)."""
    fmt = FLOAT8_FORMATS[spelling]
    total = 1 + fmt[0] + fmt[1] if fmt[3] != 'ue8m0' else 8
    out = {}
    for bits in range(1 << total):
        v = _decode(bits, fmt)
        if v is None or v in (float('inf'), float('-inf')):
            continue
        if v in out and out[v][0] <= bits:
            continue
        out[v] = (bits, v)
    return sorted(out.values(), key=lambda t: t[1])


def round_float8(x, spelling) -> float:
    """`x` rounded to the nearest value the format can hold, ties to even.

    NaN stays NaN. Above the largest finite value an IEEE-style format rounds
    to infinity (or NaN for the fn kinds, which have no infinity); an unsigned
    e8m0 has no zero and no negatives, so it rounds to the nearest power of
    two. This is the reference the compiled runtime's rounding must match.
    """
    import math
    if math.isnan(x):
        return float('nan')
    vals = _TABLE_CACHE.get(spelling)
    if vals is None:
        vals = [v for _, v in finite_values(spelling)]
        _TABLE_CACHE[spelling] = vals
        _TABLE_BITS[spelling] = {v: b for b, v in finite_values(spelling)}
    lo_v, hi_v = vals[0], vals[-1]
    kind = FLOAT8_FORMATS[spelling][3]
    if x > hi_v or x < lo_v:
        # Past the largest finite value: the next value up is one step beyond it,
        # so a value rounds to it only below the midpoint of the top step.
        top, step = (hi_v, hi_v - vals[-2]) if x > hi_v else (lo_v, vals[1] - lo_v)
        if abs(x - top) < step / 2 or (kind == 'ue8m0' and x > hi_v):
            return top
        if kind == 'ue8m0':
            return top
        if kind == 'ieee':
            return float('inf') if x > 0 else float('-inf')
        return float('nan')
    import bisect
    i = bisect.bisect_left(vals, x)
    if i < len(vals) and vals[i] == x:
        return x
    a, b = vals[i - 1], vals[i]
    da, db = x - a, b - x
    if da < db:
        return a
    if db < da:
        return b
    return a if _TABLE_BITS[spelling][a] % 2 == 0 else b


_TABLE_CACHE: dict = {}
_TABLE_BITS: dict = {}
