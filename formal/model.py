"""The formal backends' shared value model and calling convention.

The two formal targets (arm64 and x86-64) are separate code generators, but
they are ONE language implementation: the same Mojo program must mean the same
thing whichever one compiles it. Everything that decides *what a value is* —
rather than *which instruction computes it* — therefore lives here, and each
backend is left with instruction selection only.

What belongs here, and what does not:

  * HERE: the in-memory layout of a container, the rules for comparing and
    scanning keys, the order of incoming arguments, which operators exist at
    all, and the source constructs that are no-ops in the value flow.
  * PER-BACKEND: the registers, the encoders, the instruction forms, and the
    number of argument registers the platform's ABI has.

Why it matters, concretely: if arm64 scanned a dict's membership at stride 8
while x86-64 scanned at stride 16, the same `k in d` would answer differently
per architecture — a silent divergence between two backends of one compiler,
which is the failure mode this project cannot have. The same applies to the
argument order of a generic function: a callee's comptime parameters are
leading arguments on BOTH paths, so the caller and callee must agree on that
order in one place, not twice.
"""

import fire_compiler as F

# The value types a key element can have and still compare equal as a raw
# 64-bit word: interned string literals and integers.
CANONICAL_ELEM_TYPES = (F.IntLiteral, F.BoolLiteral, F.StringLiteral)

# ── Aggregate layout ──────────────────────────────────────────────────────
#
# A list/tuple is a blob:  [count:i64][elem0][elem1]…   (8-byte slots)
# A set lowers as a list. A dict is a PAIR blob:
#                            [count:i64][key0][val0][key1][val1]…
# A string is an interned char* with no header.
#
# The count is a PAIR count for a dict, which is why scanning one at the
# element stride only ever reaches the first half of it (slot i of a pair blob
# alternates key, value). `membership_stride` is the rule that keeps a
# membership test from making that mistake.

BLOB_HEADER_BYTES = 8      # the i64 count
ELEM_STRIDE = 8            # list element / pair slot stride
PAIR_STRIDE = 16           # key+value pair stride (also the key-address step)
VALUE_OFFSET = 8           # key -> value within a pair


def membership_stride(is_dict: bool) -> int:
    """Byte step between candidate elements of a `in` / `not in` scan.

    A dict is a pair blob, so a membership test must walk KEYS at the pair
    stride; at the element stride it would walk keys and values alternately
    and, bounded by the pair count, could only ever see half the dict."""
    return PAIR_STRIDE if is_dict else ELEM_STRIDE


def element_offset(index: int) -> int:
    """Byte offset of element `index` from a blob's base."""
    return BLOB_HEADER_BYTES + ELEM_STRIDE * index


def pair_key_offset(index: int) -> int:
    """Byte offset of pair `index`'s KEY from a pair blob's base."""
    return BLOB_HEADER_BYTES + PAIR_STRIDE * index


def pair_value_offset(index: int) -> int:
    """Byte offset of pair `index`'s VALUE from a pair blob's base."""
    return pair_key_offset(index) + VALUE_OFFSET


# ── Key comparison ────────────────────────────────────────────────────────
#
# Dict keys and list elements are compared as raw 64-bit words, which is
# *value* equality only for canonical values: interned string literals and
# integers. A tuple/list key is a BLOB POINTER, and two equal tuples built at
# two different points in a program are two different addresses — so the raw
# compare misses. When the key is a container literal whose elements are all
# canonical, comparing it element-wise is the only comparison here that means
# "equal tuple". Anything else keeps the raw compare, which is the documented
# behaviour rather than a silently wrong answer.

def static_key_elements(needle):
    """The element expressions of a statically-known container key, or None.

    None means "compare raw" — either the key is not a container literal, or
    one of its elements is computed and so has no canonical value to compare
    against."""
    if not isinstance(needle, (F.TupleExpr, F.ListExpr)):
        return None
    elems = list(needle.elements)
    if not all(isinstance(x, CANONICAL_ELEM_TYPES) for x in elems):
        return None
    return elems


def key_compare_is_structural(needle) -> bool:
    """True when `needle` compares element-wise rather than as a raw word."""
    return static_key_elements(needle) is not None


# ── Calling convention ────────────────────────────────────────────────────
#
# On both formal paths a generic function's comptime parameters are ordinary
# LEADING arguments: the call site evaluates the bracket expressions and passes
# them first, so the body reads them through the normal parameter machinery.
# The ORDER is a language decision and lives here; how many arguments the
# platform can pass in registers is the backend's business (AAPCS gives 8,
# SysV gives 6).


def incoming_args(fn) -> list:
    """(name, type_or_None) for each incoming argument, in ABI order.

    Comptime parameters first (type None — they are already full words, with
    no declared width to normalize to), then the runtime parameters."""
    ct = []
    for p in (getattr(fn, "comptime_params", None) or []):
        if isinstance(p, str) and p.isidentifier():
            ct.append((p, None))
    return ct + list(getattr(fn, "params", None) or [])


def is_generic(fn) -> bool:
    return bool(getattr(fn, "comptime_params", None))


# ── Constructs that are no-ops in the value flow ──────────────────────────
#
# These name source constructs whose only meaning is to the compiler, so a
# backend can pass the operand/value straight through. They are no-ops in
# BOTH senses: nothing is computed, and nothing is lost.


def is_ownership_transfer(node) -> bool:
    """`x^` — Mojo's ownership transfer marker.

    A borrow-check annotation naming no runtime operation, so the value flows
    through unchanged. The gimple path makes the same call on its unary
    lowering ("Ownership transfer operator (^) - just pass the value through",
    mojo/backend_gimple/emit_exprs.py). Refusing it instead would reject every
    stdlib module that moves a value."""
    return (getattr(node, "op", None) == "^"
            and type(node).__name__ == "UnaryOp")


def is_ellipsis(node) -> bool:
    """A bare `...` — a declaration with no body, or a placeholder value.

    Emits nothing and yields 0, the same "nothing here" a None literal gets."""
    return type(node).__name__ == "EllipsisLiteral"


# ── Type constructors ─────────────────────────────────────────────────────
#
# `Int(x)`, `Int32(x)`, `String(s)` are CONVERSIONS, not calls: a value in this
# model is a 64-bit word, so constructing an integer type means normalizing the
# operand to that type's width and signedness, and a string is already a
# `char *`. Without this they lower to a BL against a symbol named `Int` — an
# extern nothing defines, so the image builds and then dies in dyld. That made
# `Int`, `String` and `Int32` the most common unresolvable imports in the
# stdlib, which is a self-inflicted wound rather than a linking requirement.
#
# The DECISION is here; the width normalization is the backend's (it owns the
# sign/zero-extend instructions). A container type (`List`, `Dict`, `SIMD`) has
# no representation on this path at all and is NOT in the table, so it stays an
# honest "unsupported" rather than a silent zero.

# Integer type constructors -> their width/signedness. Mirrors
# formal.types.TYPE_NAMES, which is the authority; this is the subset that is
# meaningful as a *value* conversion.
INT_TYPE_CTORS = {
    "int": (64, False), "Int": (64, True),
    "Int8": (8, True), "Int16": (16, True),
    "Int32": (32, True), "Int64": (64, True),
    "UInt8": (8, False), "UInt16": (16, False),
    "UInt32": (32, False), "UInt64": (64, False),
}

# Types whose construction is the identity on this path: a string already IS a
# `char *`, and a pointer is already a word, so constructing one is a no-op.
IDENTITY_TYPE_CTORS = ("String", "str", "StringLiteral", "StringSlice",
                       "Pointer", "UnsafePointer", "CPointer")

# Type names that are real types with NO representation on this path. Calling
# one used to emit a BL against a symbol named e.g. `Error` — an extern nothing
# defines, so the image built and then died in dyld. Naming them here turns
# that into the honest refusal this path prefers: a fat pointer (`Span`), a
# struct (`Error`) or a vector (`SIMD`) cannot be conjured out of one word, and
# saying so beats emitting a call that cannot be linked.
UNREPRESENTABLE_TYPE_CTORS = (
    "Span", "Error", "SIMD", "SIMDVector", "List", "Dict", "Set", "Tuple",
    "Optional", "StringRef", "DType", "InlineArray", "Array", "StaticTuple",
)


def type_constructor_kind(callee_name: str):
    """How to lower a call whose callee is the bare name `callee_name`, or None.

    'int' -> (width, signed): normalize the single operand to that type.
    'identity' -> pass the single operand through.
    'unsupported' -> a real type this path cannot represent; the backend turns
    that into a clear error rather than a dangling extern.
    None -> not a type constructor at all (a genuine function call)."""
    if callee_name in INT_TYPE_CTORS:
        return ("int", INT_TYPE_CTORS[callee_name])
    if callee_name in IDENTITY_TYPE_CTORS:
        return ("identity", None)
    if callee_name in UNREPRESENTABLE_TYPE_CTORS:
        return ("unsupported", None)
    return None


# ── Operator surface ──────────────────────────────────────────────────────
#
# Which augmented operators the formal paths lower at all. The SET is a
# platform/language decision; the mapping from operator to instruction is the
# backend's.

AUG_OPS = ("+", "-", "*", "/", "//", "%", "&", "|", "^", "<<", ">>", "**")
AUG_SHIFT_OPS = ("<<", ">>")
AUG_DIV_OPS = ("/", "//", "%")     # need the divide-by-zero exit, not a plain ALU


# ── structs ──────────────────────────────────────────────────────────────
# A formal value is ONE 64-bit word. A struct is representable exactly when
# its fields fit that word, which makes the field count the whole of the
# decision — there is no partial layout to attempt, and a struct that does not
# fit is refused by name and width rather than miscompiled. These predicates
# are shared because the answer must not differ between the backends that
# share this model.

def struct_fields(struct_def) -> list:
    return list(getattr(struct_def, "fields", None) or [])


def struct_field_count(struct_def) -> int:
    return len(struct_fields(struct_def))


def struct_fits_one_word(struct_def) -> bool:
    """True when the struct's whole state is a single word.

    Zero fields (a marker) and one scalar field are both exactly one word: for
    the single-field case the receiver IS the field, so `self.n` is `self` and
    no indirection is needed anywhere."""
    return struct_field_count(struct_def) <= 1


def method_function_name(struct_name: str, method_name: str) -> str:
    """The internal symbol a struct's method compiles to.

    Flat and module-agnostic, because it has to be callable from a direct BL
    within one image; the module-qualified ABI spelling is applied at the
    export boundary (see abi_method_symbol) where it is actually needed."""
    return f"{struct_name}_{method_name}"


def abi_method_symbol(module_prefix: str, struct_name: str,
                      method_name: str) -> str:
    """The boundary symbol for a struct method, per doc/ABI.md.

    Module-qualified, so two modules' same-named structs never collide in one
    library — the same reason a free function's export is qualified."""
    return f"{module_prefix}_{struct_name}_{method_name}"


def struct_methods(struct_def) -> list:
    return list(getattr(struct_def, "methods", None) or [])


def find_method_owner(structs: dict, method_name: str):
    """The struct that declares `method_name`, or None.

    Dispatch here is by name alone because that is all a `recv.m()` call site
    carries: the receiver's type is not inferred on this path. A method name
    declared by two structs in one module is therefore ambiguous, and the
    caller is expected to refuse it rather than pick one."""
    owners = [st for st in structs.values()
              if any(m.name == method_name for m in struct_methods(st))]
    if len(owners) == 1:
        return owners[0]
    return None


def method_owner_names(structs: list) -> dict:
    """{`<Struct>_<method>` function name: struct} for every declared method.

    The reverse of find_method_owner, for the compiler side: after a method is
    lifted to a function, this is what identifies which struct's layout the
    body is written against."""
    out = {}
    for st in structs:
        for m in struct_methods(st):
            out[method_function_name(st.name, m.name)] = st
    return out
