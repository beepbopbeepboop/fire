"""Types of the gimple IR.

A type is an interned `Type` object, never a string.  Types are interned by C
SPELLING: `char` and `int8_t`, `long` and `int64_t`, `bool` and `_Bool` are
distinct objects, because the backend prints them differently.  Each carries
`cls`, the semantic type it is an instance of (`long.cls is int64_t`), and the
compatibility functions below compare classes.  `a is b` therefore means "the
same spelling"; `a.cls is b.cls` means "the same GIMPLE type".

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
    name    the C spelling ('int64_t', 'long', 'MojoList *', ...)
    pointee for 'ptr'
    cls     the semantic type this spelling is an instance of; `self` for the
            canonical spelling of a class (`I64.cls is I64`, `C_LONG.cls is I64`)
    ranked  the spelling is one the backend's usual-arithmetic lattice ranks
            (`int`, `int8_t` ... `uint64_t`, `unsigned int`, `__fp16`, `float`,
            `double`); `long`, `char`, `ssize_t` ... are scalars but not ranked
    """

    def __init__(self, kind: str, name: str, bits: int, signed: bool):
        self.kind: str = kind
        self.name: str = name
        self.bits: int = bits
        self.signed: bool = signed
        self.pointee: Type = self  # replaced for 'ptr'; never None so it stays typed
        self.cls: Type = self      # replaced for a non-canonical spelling
        self.ranked: bool = False

    def is_int(self) -> bool:
        return self.kind == 'int'

    def is_bool(self) -> bool:
        return self.kind == 'bool'

    def is_float(self) -> bool:
        return self.kind == 'float'

    def is_ptr(self) -> bool:
        return self.kind == 'ptr'

    def is_pointer(self) -> bool:
        """The spelling CONTAINS a `*` (TypeLattice.is_pointer's test).

        Deliberately not `is_ptr()`: a function-pointer spelling is a pointer
        spelling to the backend but not a `ptr` Type. Keeping this at the
        spelling edge lets stage 4 delegate without changing any answer.
        """
        return '*' in self.name

    def ends_in_star(self) -> bool:
        """The spelling ENDS in ` *` (TypeLattice.ends_in_star's test)."""
        return self.name.endswith(' *')

    def is_void(self) -> bool:
        return self.kind == 'void'

    def is_struct(self) -> bool:
        return self.kind == 'struct'

    def is_void_ptr(self) -> bool:
        return self.kind == 'ptr' and self.pointee.kind == 'void'

    # The backend's spelling vocabulary (`TypeLattice.is_*` in
    # mojo/middle/types.py adapts these).  Each answers for ONE spelling, by
    # identity: types are interned by spelling, so `is` is exact.
    def is_ranked_int(self) -> bool:
        return self.ranked and self.kind == 'int'

    def is_ranked_float(self) -> bool:
        return self.ranked and self.kind == 'float'

    def is_ranked_signed(self) -> bool:
        return self.ranked and self.kind == 'int' and self.signed

    def is_ranked_unsigned(self) -> bool:
        return self.ranked and self.kind == 'int' and not self.signed

    def is_word(self) -> bool:
        return self is I64

    def is_uword(self) -> bool:
        return self is U64

    def is_int_word(self) -> bool:
        return self is INT or self is I64

    def is_char(self) -> bool:
        return self is I8

    def is_u8(self) -> bool:
        return self is U8

    def is_c_long(self) -> bool:
        return self is C_LONG

    def is_c_bool(self) -> bool:
        return self is BOOL

    def is_cpp_bool(self) -> bool:
        return self is CPP_BOOL

    def is_double(self) -> bool:
        return self is F64

    def is_cstr(self) -> bool:
        return self is CHARP

    def is_mojo_str(self) -> bool:
        return self is MOJOSTR_P

    def is_mojo_span(self) -> bool:
        return self is SPAN_P

    def is_mojo_list(self) -> bool:
        return self is MOJOLIST_P

    def is_mojo_dict(self) -> bool:
        return self is MOJODICT_P

    def is_mojo_set(self) -> bool:
        return self is MOJOSET_P

    def is_mojo_bytes(self) -> bool:
        return self is MOJOBYTES_P

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
        if t.cls is not t:
            p.cls = ptr_to(t.cls)
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
MOJOSTR_P: Type = ptr_to(struct_named('MojoStr'))
SPAN_P: Type = ptr_to(struct_named('Span'))
MOJOLIST_P: Type = ptr_to(struct_named('MojoList'))
MOJODICT_P: Type = ptr_to(struct_named('MojoDict'))
MOJOSET_P: Type = ptr_to(struct_named('MojoSet'))
MOJOBYTES_P: Type = ptr_to(struct_named('MojoBytes'))

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

# The spellings the backend's rank tables know (generated_dispatch._SIGNED,
# _UNSIGNED, _FLOAT); test_type_lattice_predicates.py pins the equality.
RANKED_SPELLINGS: dict[str, bool] = {
    'int8_t': True, 'int16_t': True, 'int32_t': True, 'int': True, 'int64_t': True,
    'uint8_t': True, 'uint16_t': True, 'uint32_t': True, 'unsigned int': True,
    'uint64_t': True, '__fp16': True, 'float': True, 'double': True,
}

BASE_WORDS: dict[str, bool] = {
    'void': True, '_Bool': True, 'bool': True, 'char': True, 'short': True,
    'int': True, 'long': True, 'signed': True, 'unsigned': True,
    'float': True, 'double': True, '__fp16': True, '_Float16': True,
}


def _spelled_scalar(name: str, base: Type) -> Type:
    """The `Type` spelled `name` whose class is `base`.  A spelling that is
    already the class's own name is `base` itself; any other (`long`,
    `int8_t`, `bool`, `ssize_t` ...) is its own object that shares `base`'s
    kind, bits and signedness, so the backend can still tell it apart."""
    if base.name == name:
        return base
    t = Type(base.kind, name, base.bits, base.signed)
    t.cls = base
    _INTERN[name] = t
    if name in RANKED_SPELLINGS:
        t.ranked = True
    return t


def type_named(name: str) -> Type:
    """The interned `Type` whose C spelling is `name`.

    The spelling comes from the backend, which still writes types as text
    (doc/GIR.md, stage 4), so this is the bridge the builder uses to put a
    type on a cast instruction.  A scalar spelling gets its real `Type`; a
    spelling ending in `*` is a pointer to whatever is before it; anything
    else is an aggregate known only by its name."""
    name = name.strip()
    t = _INTERN.get(name)
    if t is not None:
        return t
    base = BASE_TYPES.get(name)
    if base is not None:
        return _spelled_scalar(name, base)
    if name.endswith('*'):
        return ptr_to(type_named(name[:-1].strip()))
    return struct_named(name)


# The canonical spellings the rank tables name.  (The aliases among them,
# `int8_t`, `int32_t`, `unsigned int`, are marked when `type_named` makes them.)
INT.ranked = True
I16.ranked = True
I64.ranked = True
U8.ranked = True
U16.ranked = True
U32.ranked = True
U64.ranked = True
F16.ranked = True
F32.ranked = True
F64.ranked = True

# Spellings the backend distinguishes from their class (see `_spelled_scalar`).
C_LONG: Type = type_named('long')
CPP_BOOL: Type = type_named('bool')

# The spelling with no meaning: what `spelled` answers for text that is not
# already a type's own spelling.  Matches no predicate.
OPAQUE: Type = struct_named('<opaque>')


def spelled(name: str) -> Type:
    """`type_named(name)` for text that must BE a spelling.  `type_named`
    normalises (`char*` is `char *`, ` int` is `int`); the backend's
    predicates answer for exact spellings only, so text that `type_named` would
    rewrite is `OPAQUE` here."""
    t = type_named(name)
    if t.name != name:
        return OPAQUE
    return t


def trivially_convertible(dst: Type, src: Type) -> bool:
    """May a `src` value be used where `dst` is expected with NO cast
    statement?  This is GIMPLE's `useless_type_conversion_p`."""
    if dst.cls is src.cls:
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
    if dst.cls is src.cls:
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
    if dst.cls is src.cls:
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
        return dst.cls is src.cls
    if dk == 'ptr' and sk == 'float':
        return False
    if dk == 'float' and sk == 'ptr':
        return False
    return True
