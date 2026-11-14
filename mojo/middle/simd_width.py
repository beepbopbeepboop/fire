"""Mojo's SIMD lane-count rule, shared by the interpreter and the compiled path.

A `SIMD[dtype, width]` vector length must be a power of two in `[1, 2**15]`.
The interpreter (`myinterpreter._mojo_simd_width_is_valid`) rejects a bad
width when it constructs a `_MojoSIMD`, and the compiled path
(`mojo.middle.types._mojo_type` for annotations and
`mojo.backend_gimple.emit_calls._lower_call` for a `SIMD[...](...)`
constructor) rejects it before lowering. Both ask this module, so the rule
and its diagnostic exist once rather than once per engine.

The diagnostic quotes the LOWERED type spelling (`!kgen.simd<N, f32>`), which
is the shape Modular's own diagnostic uses and the canonical
`simd_bad_size_lowering.mojo` FileCheck matches, not the raw integer the
interpreter has in hand.
"""

#: The widest legal SIMD: Modular's `!kgen.simd` lane count is bounded at 2^15.
MAX_SIMD_WIDTH = 1 << 15

#: DType names (`DType.float32`, `.float32`, `Float32`) normalized to the
#: `!kgen` spelling Modular prints in its diagnostic. The scalar type names in
#: `_SCALAR_TYPE_NAMES` are the spellings `monomorphize` substitutes for a
#: `dtype: DType` parameter.
_SCALAR_TYPE_NAMES = {
    'Bool': 'bool',
    'Int': 'int', 'Int8': 'int8', 'Int16': 'int16', 'Int32': 'int32',
    'Int64': 'int64',
    'UInt': 'uint', 'UInt8': 'uint8', 'UInt16': 'uint16',
    'UInt32': 'uint32', 'UInt64': 'uint64',
    'Index': 'index',
    'Float16': 'float16', 'Float32': 'float32', 'Float64': 'float64',
    'BFloat16': 'bfloat16',
}

_KGEN_DTYPE_NAMES = {
    'bool': 'bool',
    'int': 'si64', 'int8': 'si8', 'int16': 'si16', 'int32': 'si32',
    'int64': 'si64',
    'uint': 'ui64', 'uint8': 'ui8', 'uint16': 'ui16', 'uint32': 'ui32',
    'uint64': 'ui64',
    'index': 'index',
    'float16': 'f16', 'float32': 'f32', 'float64': 'f64',
    'bfloat16': 'bf16',
}


def is_valid_width(width) -> bool:
    """True when `width` is an acceptable SIMD lane count.

    A non-int width (a symbolic/comptime parameter that is not folded here) is
    not rejected by this cheap guard: the caller only has a concrete integer
    when it can decide the question.
    """
    if isinstance(width, bool) or not isinstance(width, int):
        return True
    return 1 <= width <= MAX_SIMD_WIDTH and (width & (width - 1)) == 0


def concrete_width(text) -> int | None:
    """The integer a concrete width SPELLING denotes, or None.

    Used where the compiled path holds an annotation or a rendered bracket
    argument rather than an AST node. `int(text, 0)` accepts the decimal and
    `0x`/`0o`/`0b` spellings a Mojo source may write; an expression
    (`2**15`, `Self.size`, a parameter name) is not a concrete width and
    returns None so the caller keeps its existing lowering.
    """
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text
    try:
        return int(str(text).strip(), 0)
    except (TypeError, ValueError):
        return None


def kgen_dtype_spelling(dtype) -> str:
    """The `!kgen` element spelling for a DType value spelling.

    `DType.float32`, `.float32`, `Float32` and `f32` all answer `f32`. An
    unrecognized spelling is kept verbatim (minus a `DType.`/`.` qualifier)
    rather than guessed at: the diagnostic should name what the source wrote.
    """
    s = str(dtype).strip() if dtype is not None else ''
    if s.startswith('DType.'):
        s = s[len('DType.'):]
    elif s.startswith('dtype.'):
        s = s[len('dtype.'):]
    elif s.startswith('.'):
        s = s[1:]
    s = _SCALAR_TYPE_NAMES.get(s, s).lower()
    return _KGEN_DTYPE_NAMES.get(s, s)


def invalid_width_diagnostic(width, dtype) -> str:
    """The compile-time diagnostic for an illegal concrete lane count."""
    return ("error: SIMD vector length must be a power of two between 1 and "
            f"2^15, found '!kgen.simd<{width}, {kgen_dtype_spelling(dtype)}>'")


def reject_invalid_width(width, dtype) -> None:
    """Raise the compile-time diagnostic when `width` is an illegal lane count.

    `width` must be a concrete integer (the callers fold the bracket argument
    first); a symbolic width is not this guard's to reject.
    """
    if not is_valid_width(width):
        raise RuntimeError(invalid_width_diagnostic(width, dtype))
