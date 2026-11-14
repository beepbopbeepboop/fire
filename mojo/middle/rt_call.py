"""Argument representation for calls to runtime (C) functions.

GCC does not type-check the arguments of a call in a `__GIMPLE` function and
does not convert them: an `int` variable passed to an `int64_t` parameter
arrives with garbage in its upper 32 bits, and an integer passed to a `double`
parameter arrives in the wrong register (doc/GIR.md, "the call-argument
hole").  So the emitter must convert, and to convert it must know two things
that no call site is trusted to state: the parameter's real C type (from the
runtime headers, `rt_sigs.RT_SIGS`) and the argument's declared C type.

This module answers "does this argument need a conversion statement?" for the
scalar representations.  It deliberately says nothing about pointers or about
int64_t-erased values: those are semantic conversions and belong to
`_emit_call`'s own ladder.
"""
from mojo.middle.rt_sigs import RT_SIGS

# C scalar spelling -> width in bits.
_SCALAR_BITS: dict[str, int] = {
    '_Bool': 1,
    'char': 8, 'int8_t': 8, 'uint8_t': 8,
    'int16_t': 16, 'uint16_t': 16,
    'int': 32, 'int32_t': 32, 'uint32_t': 32,
    'int64_t': 64, 'uint64_t': 64, 'long': 64, 'size_t': 64,
    'float': 32, 'double': 64,
}

# C scalar spelling -> 'bool' | 'int' | 'float'.
_SCALAR_CLASS: dict[str, str] = {
    '_Bool': 'bool',
    'char': 'int', 'int8_t': 'int', 'uint8_t': 'int',
    'int16_t': 'int', 'uint16_t': 'int',
    'int': 'int', 'int32_t': 'int', 'uint32_t': 'int',
    'int64_t': 'int', 'uint64_t': 'int', 'long': 'int', 'size_t': 'int',
    'float': 'float', 'double': 'float',
}


def rt_param_types(fname: str) -> list[str]:
    """Parameter C types of runtime function `fname` ('...' marks a variadic
    tail); [] when `fname` is not a runtime function or takes no parameters."""
    sig = RT_SIGS.get(fname)
    if sig is None:
        return []
    out: list[str] = []
    i = 1
    while i < len(sig):
        out.append(sig[i])
        i += 1
    return out


def arg_needs_repr_cast(param: str, declared: str) -> bool:
    """Must a variable declared `declared` be converted by its own cast
    statement before it is passed to a parameter of type `param`?

    True only when both are scalars of a different class or width.  Same
    width, different signedness is the same register and the same bits, so it
    needs nothing."""
    if param == declared:
        return False
    pc = _SCALAR_CLASS.get(param)
    dc = _SCALAR_CLASS.get(declared)
    if pc is None or dc is None:
        return False
    if pc == 'int' and dc == 'bool':
        # A `_Bool` variable holds 0 or 1 in a full register, so passing it
        # to an integer parameter is already the right bits.  Left alone on
        # purpose: tests pin `mojo_repr_bool (b)` with the `_Bool` itself.
        return False
    if pc != dc:
        return True
    return _SCALAR_BITS[param] != _SCALAR_BITS[declared]


def arg_needs_word_cast(param: str, declared: str) -> bool:
    """Is this a pointer parameter handed a variable DECLARED `int64_t` (a
    pointer travelling as a word), or an `int64_t` parameter handed a declared
    pointer?  Same register, same bits; the cast only makes the statement say
    what it does, so GIR's verifier (and a reader) can see it."""
    if param == declared:
        return False
    if param.endswith('*') and declared == 'int64_t':
        return True
    if param == 'int64_t' and declared.endswith('*'):
        return True
    return False
