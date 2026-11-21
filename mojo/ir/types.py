"""Types of the gimple IR.

A type is an interned `Type` object, never a string.  Two types are the same
type exactly when they are the same object, so `a is b` is the equality test.

The rules GCC's GIMPLE verifier applies (`useless_type_conversion_p`,
gimple-expr.cc) live in `trivially_convertible`; `mismatch_class` names the
way two types disagree.  No other module may decide type compatibility.
"""
from __future__ import annotations


class Type:
    """One C type.

    kind    'void' | 'bool' | 'int' | 'float' | 'ptr' | 'struct' | 'fn'
    bits    width for bool/int/float (bool is 1), else 0
    signed  for 'int'
    name    canonical C spelling ('int64_t', 'MojoList *', ...)
    pointee for 'ptr'
    """

    def __init__(self, kind: str, name: str, bits: int, signed: bool):
        self.kind: str = kind
        self.name: str = name
        self.bits: int = bits
        self.signed: bool = signed
        self.pointee: Type = self  # replaced for 'ptr'; never None so it stays typed

    def is_int(self) -> bool:
        return self.kind == 'int'

    def is_bool(self) -> bool:
        return self.kind == 'bool'

    def is_float(self) -> bool:
        return self.kind == 'float'

    def is_ptr(self) -> bool:
        return self.kind == 'ptr'

    def is_void(self) -> bool:
        return self.kind == 'void'

    def is_struct(self) -> bool:
        return self.kind == 'struct'

    def is_void_ptr(self) -> bool:
        return self.kind == 'ptr' and self.pointee.kind == 'void'

    def __repr__(self) -> str:
        return self.name


_INTERN: dict[str, Type] = {}


def _mk(kind: str, name: str, bits: int, signed: bool) -> Type:
    t = _INTERN.get(name)
    if t is None:
        t = Type(kind, name, bits, signed)
        _INTERN[name] = t
    return t


VOID: Type = _mk('void', 'void', 0, False)
BOOL: Type = _mk('bool', '_Bool', 1, False)
I8: Type = _mk('int', 'char', 8, True)           # also int8_t: one 8-bit signed type
I16: Type = _mk('int', 'int16_t', 16, True)
INT: Type = _mk('int', 'int', 32, True)          # C `int`: runtime ABI only
I64: Type = _mk('int', 'int64_t', 64, True)
U8: Type = _mk('int', 'uint8_t', 8, False)
U16: Type = _mk('int', 'uint16_t', 16, False)
U32: Type = _mk('int', 'uint32_t', 32, False)
U64: Type = _mk('int', 'uint64_t', 64, False)
F16: Type = _mk('float', '__fp16', 16, True)
F32: Type = _mk('float', 'float', 32, True)
F64: Type = _mk('float', 'double', 64, True)
F128: Type = _mk('float', 'long double', 128, True)
FN: Type = _mk('fn', '<fn>', 0, False)             # a function designator


def ptr_to(t: Type) -> Type:
    name = t.name + ' *' if not t.name.endswith('*') else t.name + '*'
    p = _INTERN.get(name)
    if p is None:
        p = Type('ptr', name, 64, False)
        p.pointee = t
        _INTERN[name] = p
    return p


def struct_named(name: str) -> Type:
    """An aggregate (or opaque) type known only by name."""
    key = 'struct:' + name
    t = _INTERN.get(key)
    if t is None:
        t = Type('struct', name, 0, False)
        _INTERN[key] = t
    return t


VOIDP: Type = ptr_to(VOID)
CHARP: Type = ptr_to(I8)
FNP: Type = ptr_to(FN)

# C spellings that are one of the scalar types above.  LP64 (darwin-arm64,
# linux-x86_64): long == long long == 64 bits; they are distinct C types but
# the same GIMPLE type class (same mode, precision, signedness).
BASE_TYPES: dict[str, Type] = {
    'void': VOID, '_Bool': BOOL, 'bool': BOOL,
    'char': I8, 'signed char': I8, 'int8_t': I8,
    'unsigned char': U8, 'uint8_t': U8,
    'short': I16, 'short int': I16, 'int16_t': I16,
    'unsigned short': U16, 'unsigned short int': U16, 'uint16_t': U16,
    'int': INT, 'signed': INT, 'signed int': INT, 'int32_t': INT,
    'unsigned': U32, 'unsigned int': U32, 'uint32_t': U32,
    'long': I64, 'long int': I64, 'long long': I64, 'long long int': I64,
    'signed long': I64, 'signed long long': I64,
    'int64_t': I64, 'ssize_t': I64, 'intptr_t': I64, 'ptrdiff_t': I64,
    'off_t': I64, 'time_t': I64, 'intmax_t': I64,
    'unsigned long': U64, 'unsigned long int': U64, 'unsigned long long': U64,
    'unsigned long long int': U64, 'long unsigned int': U64,
    'uint64_t': U64, 'size_t': U64, 'uintptr_t': U64, 'uintmax_t': U64,
    'float': F32, 'double': F64, 'long double': F128,
    '__fp16': F16, '_Float16': F16,
    'pid_t': INT, 'mode_t': U16, 'uid_t': U32, 'gid_t': U32, 'socklen_t': U32,
}

BASE_WORDS: dict[str, bool] = {
    'void': True, '_Bool': True, 'bool': True, 'char': True, 'short': True,
    'int': True, 'long': True, 'signed': True, 'unsigned': True,
    'float': True, 'double': True, '__fp16': True, '_Float16': True,
}


def trivially_convertible(dst: Type, src: Type) -> bool:
    """May a `src` value be used where `dst` is expected with NO cast
    statement?  This is GIMPLE's `useless_type_conversion_p`."""
    if dst is src:
        return True
    if dst.kind != src.kind:
        return False
    if dst.kind == 'int':
        return dst.bits == src.bits and dst.signed == src.signed
    if dst.kind == 'float':
        return dst.bits == src.bits
    if dst.kind == 'ptr':
        # any data pointer converts to any data pointer; a function pointer
        # does not convert to or from a data pointer
        return (dst.pointee.kind == 'fn') == (src.pointee.kind == 'fn')
    return False


def same_pointee(dst: Type, src: Type) -> bool:
    """Stricter than GIMPLE: are two pointers the same pointer type, or is one
    of them `void *` / `char *` (the two generic pointers the runtime uses)?"""
    if dst is src:
        return True
    if dst.kind != 'ptr' or src.kind != 'ptr':
        return False
    if dst.pointee.kind == 'void' or src.pointee.kind == 'void':
        return True
    if dst.pointee.kind == 'int' and src.pointee.kind == 'int':
        return dst.pointee.bits == src.pointee.bits
    return False


def mismatch_class(dst: Type, src: Type) -> str:
    """Name the way `src` fails to be usable as `dst`.  '' means: fine.

    int-widen   narrower int into wider int  (GIMPLE-illegal, value-safe in C)
    int-narrow  wider int into narrower int  (silent truncation in C)
    int-sign    same width, different signedness
    bool-int    _Bool vs integer
    int-ptr     integer vs pointer           (the erased-pointer hazard)
    int-float   integer vs floating point
    float-width float vs double
    fn-ptr      function pointer vs data pointer
    ptr-kind    two different pointer types; GIMPLE allows it, we do not
    kind        anything else (struct by value, void, ...)
    """
    if dst is src:
        return ''
    dk = dst.kind
    sk = src.kind
    if dk == 'int' and sk == 'int':
        if dst.bits > src.bits:
            return 'int-widen'
        if dst.bits < src.bits:
            return 'int-narrow'
        if dst.signed != src.signed:
            return 'int-sign'
        return ''
    if (dk == 'bool' and sk == 'int') or (dk == 'int' and sk == 'bool'):
        return 'bool-int'
    if (dk == 'int' and sk == 'ptr') or (dk == 'ptr' and sk == 'int'):
        return 'int-ptr'
    if (dk == 'bool' and sk == 'ptr') or (dk == 'ptr' and sk == 'bool'):
        return 'int-ptr'
    if (dk == 'int' and sk == 'float') or (dk == 'float' and sk == 'int'):
        return 'int-float'
    if (dk == 'bool' and sk == 'float') or (dk == 'float' and sk == 'bool'):
        return 'int-float'
    if dk == 'float' and sk == 'float':
        if dst.bits != src.bits:
            return 'float-width'
        return ''
    if dk == 'ptr' and sk == 'ptr':
        if (dst.pointee.kind == 'fn') != (src.pointee.kind == 'fn'):
            if dst.pointee.kind == 'void' or src.pointee.kind == 'void':
                return ''
            return 'fn-ptr'
        if same_pointee(dst, src):
            return ''
        return 'ptr-kind'
    return 'kind'


# Which mismatch classes GCC's GIMPLE verifier rejects in a copy / operand /
# return position.  'ptr-kind' is legal GIMPLE and is our own, stricter rule.
GIMPLE_ILLEGAL: dict[str, bool] = {
    'int-widen': True, 'int-narrow': True, 'int-sign': True, 'bool-int': True,
    'int-ptr': True, 'int-float': True, 'float-width': True, 'fn-ptr': True,
    'kind': True,
}


def cast_is_legal(dst: Type, src: Type) -> bool:
    """Is `dst = (T) src` one legal GIMPLE conversion statement?"""
    dk = dst.kind
    sk = src.kind
    if dk == 'void' or sk == 'void' or dk == 'struct' or sk == 'struct':
        return dst is src
    if dk == 'ptr' and sk == 'float':
        return False
    if dk == 'float' and sk == 'ptr':
        return False
    return True
