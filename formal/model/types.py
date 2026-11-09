from . import *

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


def ellipsis_refusal(node):
    """The refusal for a `...` standing where a value belongs, or None.

    The generic `unsupported expression EllipsisLiteral on the formal <arch>
    path` names an AST node the author never wrote and says nothing about what
    to do instead, which is the definition of a useless diagnostic: a reader
    sent looking for an `EllipsisLiteral` in their source finds nothing. On
    x86-64 it was worse than useless, because `_unsupported_expr_message`
    appended "container and string values are not" to it — a claim that is
    false of a `...`, and one that sent the reader looking for a list.

    Arch-free and shared, for the same reason every other refusal here is: the
    two backends are one language implementation, and they had drifted on this
    one — a construct with two different messages, one of them wrong about the
    file.

    Measured, both architectures, so the scope claim is a measurement and not an
    assumption: a `...` in a plain `def`/`fn` body is refused whether or not
    the function is ever CALLED, because this path lowers every definition it is
    given; a `...` in a `trait` method builds, because a trait method is a
    declaration of an interface and there is no body to lower. So the advice is
    "give the function a body", and the escape hatch is a trait, not an
    unreferenced call."""
    if not is_ellipsis(node):
        return None
    return (
        "a `...` stands where this path needs instructions to emit, and there "
        "are none: a formal image is a compiled program, so every function it "
        "lowers must have a body. This is the language's own no-implementation "
        "marker — write the function, or declare it as a `trait` method, which "
        "is a declaration of an interface and so has no body to lower (a `...` "
        "in a trait method builds on both architectures, and a `...` in a plain "
        "function is refused whether or not anything ever calls it)")




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

# The subset of those that produce a STRING rather than an opaque word. Kept as
# a name of its own because `String(s)` is a char * — which is a fact a caller
# can act on (print formats it with %s) — while `Pointer(p)` is a word, and
# treating the two alike would mean handing printf an address to dereference.
# The same list as formal.types.STRING_TYPE_NAMES, named here so this module
# does not have to import types to say it.
STRING_TYPE_CTORS = ("String", "str", "StringLiteral", "StringSlice")

# Type names that are real types with NO representation on this path. Calling
# one used to emit a BL against a symbol named e.g. `Error` — an extern nothing
# defines, so the image built and then died in dyld. Naming them here turns
# that into the honest refusal this path prefers: a fat pointer (`Span`), a
# struct (`Error`) or a vector (`SIMD`) cannot be conjured out of one word, and
# saying so beats emitting a call that cannot be linked.
#
# `bytearray` and `bytes` are both here for the OTHER half of the same rule —
# they used to be absent, which did not refuse them, it made them look like
# ordinary function calls, and `type_constructor_kind`'s documented `None`
# means exactly that. So `bytearray()` reached the bind audit as a dangling
# extern named `bytearray` and the build failed with a message about a SYMBOL
# ("this image would bind 1 symbol(s) that nothing provides") about a fact that
# is a TYPE's.
#
# Being in this set is ROUTING, not a verdict — `("unsupported", None)` is what
# sends a bare name to `_emit_type_constructor`, and `List`, `Dict`, `Set` and
# `Tuple` are here for the same reason while building blobs every day. What
# tells the two apart is `empty_blob_constructor`, asked first inside that
# arm: `bytearray` is a `BYTE_BLOB_CTOR`, so it builds a blob of one-byte
# elements (`bytearray()` and a constant-size `bytearray(n)` both lower, on
# both backends), and `bytes` is not, so it gets the refusal below. The element
# width is therefore NOT the undecided thing this comment used to say it was:
# `bytes` on this path is the interned `char *` a bytes LITERAL is — measured on
# both architectures, `len(b"abc")` is 3 off `strlen` and `b"abc"[i]` is one byte
# at offset `i` — so a `bytes(n)` needs a blob whose SIZE is a runtime value,
# which is the reservation every runtime-sized container is refused for.
# So the pair is decided by MEASUREMENT rather than by preference, and the
# measurements are the two sentences above: the literal's `strlen`/byte-load
# pair, and a constructor's having to build a counted region. Every consumer
# reads the decision from `BYTE_BLOB_CTORS` (the widths) or from
# `empty_blob_constructor` (the routing), never from this tuple.
#
# **`StaticString` is here for a THIRD reason, and it is the one that costs a
# reader an hour.** It is a language builtin, so it is in NO table of DECLARED
# types: not in any `structs_by_name` this build compiles, and not among the 220
# `formal/imports.py::imported_struct_defs` reaches from `std/sys/arg.mojo`
# (measured on that file). And `type_constructor_kind`'s documented `None` means
# "not a type constructor at all", so a bracket ELEMENT spelled `StaticString`
# classified as a bare name this image cannot resolve — which is false about the
# language. It IS a type, and it is unrepresentable here for the ordinary reason
# (a compile-time string is not a `char *`, so one word does not carry it).
#
# Being in this tuple is what makes `Span[StaticString, ImmStaticOrigin]` —
# `std/sys/arg.mojo:51`, one refusal byte-identical on both architectures — take
# the MIXED branch of `_comptime_param_element_sentence`, which names `element
# 2 `ImmStaticOrigin`` alone instead of leaving the reader to choose between two
# candidates neither of which the build can resolve. A name missing from a table
# of types reads as a fact about the target, and this one is a fact about the
# table; `myinterpreter.py` already knows `StaticString` as a borrowed-string-view
# type, so the two halves of this compiler disagreed about whether it is a type.
BYTE_BLOB_TYPE_CTORS = ("bytearray", "bytes")

#: The IEEE float formats NARROWER than binary64, the fourth of the language's
#: four float type names, and the 128-bit unsigned integer — a CLOSED list, and
#: not a shape rule.
#:
#: It is closed because two tables are derived from it and one of them
#: (`type_value_name_space`, via `TYPE_VALUE_NAMES`) has to stay FINITE for
#: `type_value_tags_are_distinct` to be a proof over every pair rather than a
#: bound on a probability.  A rule that admitted any `float<width>_<format>`
#: would make that set unbounded, which is the whole of the condition.
#:
#: Measured over this repository and the stdlib checkout, these are every
#: float-format and 128-bit member either of them writes — `DType.float8_e4m3fn`
#: 26, `float8_e5m2fnuz` 21, `float8_e4m3fnuz` 20, `float8_e5m2` 19,
#: `float8_e8m0fnu` 14, `float6_e3m2fn` 11, `float6_e2m3fn` 11, `float4_e2m1fn`
#: 10, `uint128` 8, `float8_e3m4` 7 — so the list is the corpus rather than a
#: guess at the language's shape.  A tag for a format this path cannot HOLD is
#: not a lie: it is a word two programs comparing dtypes agree on, which is all a
#: dtype VALUE is on this path.  A member outside the list is still refused with
#: its own name (`_dtype_member_type` returns None), so the boundary is drawn
#: once, explicitly, and every member outside it keeps a refusal that says what
#: the admitted ones are.
#:
#: **This list is also where the CONSTRUCTOR half of `POINTEES_REFUSED` comes
#: from.**  `POINTEES_REFUSED` refuses `Float16` and `Float32` BY NAME at a
#: dereference, and the constructor `Float32(1.0)` had no name to be
#: refused by — it took `type_constructor_kind`'s documented `None` ("not a type
#: constructor at all"), emitted a `BL Float32`, and failed at the LINK AUDIT
#: with a message about a SYMBOL about a fact that is a TYPE's.
#: `NARROW_FLOAT_TYPE_CTORS` below derives from THIS list for that reason, and
#: `TYPE_VALUE_NAMES` derives from it too, so the two cannot disagree about
#: which formats exist.  **`Float64` is deliberately NOT here**: it is the one
#: float this path represents, so it is in neither the narrow list nor
#: `POINTEES_REFUSED` — a `Pointer[Float64]` LOADS.
NARROW_FLOAT_TYPE_NAMES = (
    "BFloat16",
    "Float16", "Float32",
    "Float4_e2m1fn", "Float6_e2m3fn", "Float6_e3m2fn",
    "Float8_e3m4", "Float8_e4m3fn", "Float8_e4m3fnuz", "Float8_e5m2",
    "Float8_e5m2fnuz", "Float8_e8m0fnu",
    "UInt128",
)

UNREPRESENTABLE_TYPE_CTORS = (
    "Span", "Error", "SIMD", "SIMDVector", "List", "Dict", "Set", "Tuple",
    "Optional", "StringRef", "DType", "InlineArray", "Array", "StaticTuple",
    "StaticString",
) + BYTE_BLOB_TYPE_CTORS + NARROW_FLOAT_TYPE_NAMES


def unrepresentable_type_ctor_refusal(callee_name: str) -> str:
    """Why a call whose callee is `callee_name` has no representation here.

    **The one wording, in the model, for both backends.** It used to be written
    out in `formal/arm64_codegen.py` and `formal/x86_64_codegen.py` as two
    copies of the same six sentences, which is two places for one diagnostic to
    drift — and a diagnostic a reader matches on is exactly the kind of string
    that has to be one thing.

    Two texts, and the split is a fact about the name rather than a preference.
    The generic one is about a type that cannot be conjured out of one word.
    `bytes` is a different problem, and it is the one this text is about: a
    `bytes` value on this path is the interned `char *` a bytes LITERAL is —
    measured on both architectures, `len(b"abc")` is 3 off `strlen` and
    `b"abc"[i]` is one byte at offset `i` — so the layout a `bytes(n)` has to
    build is a blob whose SIZE is a runtime value, which is the reservation
    every runtime-sized container on this path is refused for. It is NOT the
    undecided element width any more: `bytearray` is a blob with a one-byte
    element stride (`BYTE_BLOB_CTORS`), so the width question is answered and
    `bytes` is refused for what it actually needs. Saying THAT is what a reader
    can act on, and it names the answer that exists rather than the two that
    were open when this text was written.

    **A third, for the narrow float formats, and the generic text is FALSE of
    them.**  It says "this image has no declaration of X to construct", which is
    true of `Span` (nothing in hand declares one) and false of `Float32` — a
    `Float32` is a real type with a fixed 32-bit layout, and the image knows
    about it: `POINTEES_REFUSED` refuses it BY NAME at a dereference.  A reader
    who is told to go and declare the type finds nothing to declare, which is
    the failure mode this family documents itself as existing to prevent.  So
    the narrow formats get the fact that is actually true of them, and the text
    is shared with the one reader that already knows the format: the reason in
    `POINTEES_REFUSED` is about the LOAD's context and this one is about the
    VALUE, so they say the same half in different words rather than repeating
    it (see `narrow_float_ctor_refusal`).
    """
    if callee_name in BYTE_BLOB_TYPE_CTORS:
        return (
            f"constructing {callee_name} is refused on this path, and the "
            f"reason is a fact about the TYPE rather than about a symbol: a "
            f"{callee_name} here is the interned `char *` a bytes LITERAL is "
            f"— `len(b\"abc\")` answers 3 off `strlen` and `b\"abc\"[i]` is one "
            f"byte at offset `i`, both architectures — while a CONSTRUCTOR has "
            f"to build a counted region, and a counted region here is a blob "
            f"laid out `[count:i64][element 0]…`. The element width is "
            f"decided and it is not the obstacle: `bytearray` is that blob "
            f"with a one-byte element, and `bytearray()` and a constant-size "
            f"`bytearray(n)` both lower. What `bytes(n)` needs is a "
            f"reservation sized by a value this compiler does not have at "
            f"layout time, which is the same limit `List[Int](3)` has and the "
            f"same bargain every container here makes. The MUTABLE byte blob "
            f"is `bytearray`, and it is the spelling to reach for. (Emitting a "
            f"call to a symbol named {callee_name!r} that nothing defines is "
            f"not the alternative — that reached the bind audit as a dangling "
            f"extern and failed with a message about a SYMBOL rather than "
            f"about the type.)")
    if callee_name in NARROW_FLOAT_TYPE_NAMES:
        return narrow_float_ctor_refusal(callee_name)
    return (
        f"constructing {callee_name} has no representation on this path: "
        f"{callee_name} is a real type this path has no representation for "
        f"at all — this image has no declaration of {callee_name} to construct "
        f"— it is not a struct in this module or in anything it imports, so "
        f"there is no field list to bring up, and a formal value is one 64-bit "
        f"word. A name that IS declared as a struct here is decided by "
        f"`_emit_struct_constructor` instead, which asks the struct: a one-field "
        f"struct is a plain word and constructs. (Emitting a call to a symbol "
        f"named {callee_name!r} that nothing defines is not the alternative — "
        f"that built and then failed to load.)")


def narrow_float_ctor_refusal(callee_name: str) -> str:
    """Why a CONSTRUCTOR of a narrow float format has no value here.

    The sibling of `POINTEES_REFUSED`'s narrow-float rows, and not a copy of
    them.  That table answers a question about a LOAD — what a pointer
    dereference yields, and its kind being decided by the context it lands in —
    and its rows are read at the dereference.  This one answers a question about
    the VALUE: there is no word to put a `Float32`'s bits in, whatever the
    context does with it afterwards.  The shared half is that these formats are
    NOT a re-encoding of binary64, so "just widen it" is not available; the rest
    is a different sentence and repeating the table's would send the reader to a
    dereference they are not writing.

    **`Float64` is not in this table and that is the fact it states**: it is the
    one float kind `FLOAT_TYPE_CTORS` carries, `FLOAT_TYPE_NAMES` is its two
    spellings, and `FLOAT_KIND` is it.  Everything here is narrower than it or
    wider than one word, which is the whole of the boundary this document owns —
    `bugs/FORMAL_float_binary64_only.md`.
    """
    if callee_name == "UInt128":
        what = ("128 bits, and a formal value is one 64-bit word — so it is "
                "not a case of the wrong BITS IN one word but of two words")
        tail = ("`UInt128` is in this table for the WORD COUNT rather than for "
                "the float width: `UInt64(x)` is the conversion that lowers, "
                "and it is a different program — a `UInt128` product overflows "
                "where a `UInt64` one wraps.")
    elif callee_name.startswith("BFloat"):
        what = ("two bytes of bfloat16, the same exponent range as binary32 "
                "with a 7-bit significand, and this path's one float kind is "
                "binary64 — whose exponent bias and 52-bit significand are not "
                "a superset of that, so a word holding bfloat16 bits read as a "
                "double is a different number rather than an approximation")
        tail = (f"`{callee_name}(x)` is not an approximation of `Float64(x)` "
                f"that could be waved through: it rounds, which is the one "
                f"thing a wrong answer here would silently not do.")
    else:
        what = ("narrower than the IEEE binary64 this path's only float kind "
                "is, and the two are not re-encodings of one another: the "
                "exponent bias and the significand width both differ, so a "
                "64-bit word holding one format's bits read as the other is a "
                "different number rather than an approximation — which is why "
                "the honest answer here is a refusal and not a widening")
        tail = (f"`{callee_name}(x)` is not an approximation of `Float64(x)` "
                f"that could be waved through: it rounds, which is the one "
                f"thing a wrong answer here would silently not do.")
    return (
        f"constructing {callee_name} has no representation on this path, and "
        f"the reason is a fact about the FORMAT rather than about a symbol: "
        f"{what}. `FLOAT_KIND` is IEEE binary64 and the arithmetic both "
        f"backends lower is the SCALAR DOUBLE set (`FADD`/`FSUB`/`FMUL`/`FDIV`, "
        f"`ADDSD`/`SUBSD`/`MULSD`/`DIVSD`), so `float(x)`, `Float64(x)` and "
        f"`float64(x)` all lower and this does not. Naming the type as a VALUE "
        f"is a different question and is answered: the `DType` member spelling "
        f"of a narrow format is a tag, and a tag this path can hold is a word "
        f"two programs comparing dtypes agree on — so a dtype comparison over "
        f"these formats works today and a VALUE of one does not. The same fact "
        f"refuses a `Pointer[{callee_name}]` dereference, for the load's half "
        f"rather than this one. {tail}")


#: The keyword names a `String` conversion uses to SAY its operand is a raw
#: pointer — `String(unsafe_from_utf8_ptr=p)`, `std/os/env.mojo`'s own spelling.
#:
#: It matters because a named pointer's KIND on this path is the "a word is an
#: integer" default (`external_call["getenv", _CPointer[UInt8, …]]` bound to a
#: local classifies `int` — a call result is a fact about the callee and the
#: model's conservative answer is a word), so `string_conversion_refusal`'s
#: positive-evidence rule refuses a conversion whose operand is exactly what the
#: keyword says it is.  The conversion is the IDENTITY when the operand is a
#: pointer, so the keyword is the source's own statement that the identity is
#: the right lowering, and the whole-table read of "which keyword means a
#: pointer" is here rather than spelled into both backends.
STRING_POINTER_CONVERSION_KWARGS = frozenset({"unsafe_from_utf8_ptr"})


def string_conversion_pointer_intent(kwargs) -> bool:
    """True when a conversion's operand is passed as a raw-POINTER keyword.

    `kwargs` is the call's `[(name, value)]` list.  One reader so the two
    backends cannot disagree about which spelling states a pointer, and so the
    keyword name is a table row rather than a string in two emitters.
    """
    return any(n in STRING_POINTER_CONVERSION_KWARGS for n, _v in (kwargs or ()))


def string_conversion_refusal(callee_name: str, operand, operand_kind,
                              pointer_intent: bool = False) -> str:
    """Why `String(x)` / `str(x)` is refused when `x` is KNOWN not to be text.

    `IDENTITY_TYPE_CTORS` above makes `str(x)` the IDENTITY on the operand,
    which is right for exactly one operand: a value that already IS a `char *`.
    That is the whole of the property the comment there states ("a string
    already IS a `char *`, so constructing one is a no-op"), and an identity is
    a claim about the OPERAND's kind rather than about the callee's name — so
    the identity was applied to every operand, including an integer, and the
    integer came out of the conversion still an integer while every later step
    believed it was a pointer.

    **The consequence is a segfault, not a wrong number**, which is why this is
    a refusal and not a conversion. Measured on both architectures, 2026-10-04:

        def main(n): return len(str(n))       # n = 10: exit -11 (SIGSEGV)

    `len` of a string is `strlen` over the operand's bytes, and the operand is
    the integer 10, so libc walked the bytes at address 10. The same source with
    a string operand is right (`len(str("abcd"))` is 4 on both), and the same
    source with the conversion deleted is right (`len(bin(n))` is refused at
    build time, because an unlowered call's result is classified `int` and
    `len`'s integer row catches it — so the gap was reachable through the ONE
    name the model resolves as a type constructor).

    `operand_kind` is the emitter's own reader (`_expr_str_kind`, which is
    flow-sensitive and consults a parameter's annotation, a `comptime` binding
    and a struct field's declared type), and **only POSITIVE evidence refuses**:
    a kind that is not None and is not `STR_KIND`. A kind of None is the
    permissive direction, and it is load-bearing rather than convenient:

        String(unsafe_from_utf8_ptr=p.value())

    is how a raw pointer becomes a `char *` on this path
    (`nullable_pointer_unwrap`'s docstring has the measured history of that
    shape), `p.value()` classifies as nothing this build can name, and the
    identity is CORRECT there — a pointer already is what a string is. Refusing
    an unclassifiable operand would break that shape to catch a different one,
    and `int`'s parse asks the same question and reads the same direction
    permissively for the same reason (`_conversion_operand_is_text`).

    **The residual hole is named rather than papered over**: an operand this
    build cannot classify that turns out to hold a number at run time —
    `str(<call>)` whose result kind is unknown — is still the identity, and
    still faults at its first use. Closing that is not this rule's job: it needs
    the value model to classify call results, which is
    `bugs/FORMAL_string_value_model.md`'s subject and not a name in a table.
    """
    spelled_operand = member_chain_text(operand)
    if operand_kind is None or string_operand_is_string(operand_kind):
        return None
    if pointer_intent:
        # …and a conversion the SOURCE spelled as a raw-pointer one is exempt:
        # `String(unsafe_from_utf8_ptr=ptr)` names the operand's TYPE in the
        # call, so the identity is the lowering the source asked for, whatever
        # the operand's kind-table answer is.  A named pointer's kind is the "a
        # word is an integer" DEFAULT rather than a classification of what it
        # holds — `var ptr = external_call["getenv", _CPointer[UInt8, …]](…)` —
        # so without this the same `int` default that the DEREFERENCE exemption
        # below exists for refuses a conversion that is RIGHT.  Measured on both
        # architectures: `std/os/env.mojo`'s whole round trip
        # (`test_formal_external_call.py`'s `env_round_trip`) stopped building
        # when the positive-evidence rule landed, because its `getenv` spells
        # exactly this call with a NAMED pointer rather than a load.
        return None
    if deref_receiver(operand) is not None:
        # …and a DEREFERENCE is exempt, which is the one exemption and it is a
        # fact about the kind rather than about the spelling.  `p.value()` is a
        # LOAD, and the kind table's answer for a load is the "a word is an
        # integer" DEFAULT rather than a classification of the pointee — the
        # same reason `_own_shape_of` refuses to take a call result's word as
        # evidence — while the identity is exactly right for the one shape that
        # needs it:
        #
        #     String(unsafe_from_utf8_ptr=p.value())
        #
        # is how a raw C string becomes a `char *` on this path, and
        # `nullable_pointer_unwrap` carries the measured history of it (a
        # `char *` built out of the first BYTE of a string, SIGSEGV, before the
        # unwrap was taught to be the identity).  Refusing a load would break
        # that shape to catch a different one, and the difference between them is
        # whether the word is a pointer — which is the pointee's business and not
        # this table's.
        return None
    return (
        f"{callee_name}({spelled_operand}) is refused on this path: "
        f"{callee_name} is a string type constructor, and a string on this "
        f"path IS a `char *` — an interned, NUL-terminated literal — so "
        f"constructing one is the identity on a value that is already text and "
        f"nothing at all on one that is not, and this build classifies "
        f"{spelled_operand} as {operand_kind!r}. It used to pass the value "
        f"through unchanged, which is a number where every later step expects "
        f"a pointer: `len(str(n))` with n = 10 built, ran and died of SIGSEGV "
        f"(exit -11) on both architectures, inside `strlen` walking the bytes "
        f"at address 10. Give the value a spelling this path has — a literal, "
        f"or a value another step built as text — and the conversion is a "
        f"no-op that compiles and is right."
    )


def type_constructor_kind(callee_name: str):
    """How to lower a call whose callee is the bare name `callee_name`, or None.

    'int' -> (width, signed): normalize the single operand to that type.
    'to-float' -> the value becomes an IEEE double (SCVTF over an integer); the
      direction the operand's own kind then decides is
      `float_conversion_lowering`'s, because "is this operand already a double"
      is a question about the call SITE and not about the callee's name.
    'identity' -> pass the single operand through.
    'unsupported' -> a real type this path cannot represent; the backend turns
    that into a clear error rather than a dangling extern.
    None -> not a type constructor at all (a genuine function call)."""
    if callee_name in INT_TYPE_CTORS:
        return ("int", INT_TYPE_CTORS[callee_name])
    if callee_name in FLOAT_TYPE_CTORS:
        return (FLOAT_FROM_INT, None)
    if callee_name in IDENTITY_TYPE_CTORS:
        return ("identity", None)
    if callee_name in UNREPRESENTABLE_TYPE_CTORS:
        return ("unsupported", None)
    return None


# The container types whose EMPTY value this path can represent exactly.
#
# `BLOB_TYPE_CTORS` is the set of names whose *field annotation* means "a
# counted region" (a `len` off a slot declared `List[Int]`), and it is a
# different question from this one: this set is about the CONSTRUCTOR. A
# container's value on this path is a pointer to a blob laid out `[count:i64]
# [element 0]…`, so an empty one is a blob of exactly eight bytes whose count
# word is zero — which is the same eight bytes `_emit_list` reserves for `[]`,
# and the same layout `LEN_FROM_BLOB_FIELD` reads a length from. So
# `List[Int]()` is representable, and refusing it refused a program whose
# answer this path could state exactly.
#
# DERIVED rather than written out, and the derivation is the point: the set is
# `BLOB_TYPE_CTORS` minus the names this path has no blob layout for. A second
# hand-kept list is a list that goes stale the day `BLOB_TYPE_CTORS` gains a
# name — and the failure is silent in the worst direction, because the stale
# name is then refused as "no representation", which reads as a fact about the
# target when it is a fact about a table.
#
# The exclusions, and why each is a fact about the layout rather than a
# preference:
#   * `Optional` — a value OR the empty one, and the empty one is the integer
#     0, so an empty `Optional` is indistinguishable from `Some(0)`. This is
#     the one-word value model showing through, and it is
#     the pointer value model (landed in f69079be0)'s niche question, not a table entry.
#   * `StringRef` / `InlineArray` / `Array` / `StaticTuple` — each is a blob in
#     the *source* language with an element width or a pointer this path does
#     not carry, so "empty" for them is a statement about a layout nothing here
#     has. `BLOB_TYPE_CTORS` names them for the annotation question only.
EMPTY_BLOB_CTORS = frozenset(
    n for n in BLOB_TYPE_CTORS
    if n not in ("Optional", "InlineArray", "StaticTuple", "Array", "StringRef"))


def empty_blob_constructor(callee_name: str) -> bool:
    """Whether `callee_name()` denotes the empty container, i.e. a zero count.

    The half of the container question that is about REPRESENTATION, asked
    separately from `type_constructor_kind` because the two disagree on purpose:
    `type_constructor_kind("List")` answers `("unsupported", None)` — a `List` is
    not one word, and saying so is true — while the empty `List` IS eight bytes
    with a zero in them. A backend asks this one to lower the zero-operand
    form and keeps the other one for every form that has to hold a value.
    """
    return callee_name in EMPTY_BLOB_CTORS


def blob_constructor_with_operands_refusal(callee_name: str, nargs: int) -> str:
    """Why `List[Self.T](capacity=n)` is refused, given that `List()` is not.

    A separate diagnostic from `type_constructor_kind`'s "unsupported", because
    it is a DIFFERENT question and the difference is the whole reason the empty
    form became answerable. A blob's size is decided when the function is laid
    out, so an empty one is free; one that must hold `n` elements needs a frame
    reservation sized by a value the compiler does not have, and emitting it
    anyway would mean a blob whose capacity is whatever the allocator left —
    which is the X19 fall-through this path refuses everywhere else.

    **`capacity=` is no longer one of the refused shapes**, and
    `blob_constructor_lowering` is what says so instead. The paragraph above is
    about a blob that has to HOLD `nargs` ELEMENTS; a capacity says how much room
    to set aside, not what is in the container, and the two are not the same
    question. The limits of the answer are in that function's docstring and they
    are the reason this refusal is still reached for every other operand.
    """
    return (
        f"constructing {callee_name}[…](…) with {nargs} argument(s) has no "
        f"representation on this path, and the empty form is a different "
        f"question: a {callee_name} on this path is a pointer to a blob laid "
        f"out [count:i64][element 0]…, so {callee_name}() is eight bytes with a "
        f"zero count in them and lowers, while a blob that has to HOLD {nargs} "
        f"element(s) needs a frame reservation whose size is a value this "
        f"compiler does not have at layout time. (A `capacity=` operand is not "
        f"in that class — it is a reservation hint and lowers as the empty "
        f"container; see `model.blob_constructor_lowering`.) Build the container "
        f"in the caller and assign the field after construction, or append to a "
        f"{callee_name} literal, which reserves the room it needs")


# The keyword a container's RESERVATION is spelled with, and the only one. A
# narrow name on purpose: this is the stdlib's spelling (`List[Self.T](capacity=
# capacity)` in `std/collections/binary_heap.mojo`, `List(capacity=n)` everywhere
# else) and a second accepted spelling would be a guess about a keyword this
# compiler has never seen.
BLOB_CAPACITY_KEYWORD = "capacity"

# The answers, named rather than spelled at the two emitters separately.
BLOB_LOWER_EMPTY = "empty"
BLOB_LOWER_RESERVED = "reserved"
BLOB_LOWER_SIZED = "sized"


class BlobCtorLowering(NamedTuple):
    """What a lowered blob constructor builds, for the emitters that build it.

    A record rather than a bare string because the SIZED form carries a number
    the emitter cannot re-derive: `bytearray(3)` has to RESERVE three bytes and
    write a count of 3 into the header, and the only place that knows the 3 is
    the argument the source wrote. Returning the string and leaving the emitter
    to read `e.args[0]` would put the decision (this argument is a compile-time
    count) in two files, and the one that is wrong is the one that reserves the
    wrong number of bytes.

    Every reader that only wants "does this lower" asks `is None`, which is why
    a record is safe here: six call sites test exactly that and none compared
    against the string constants.
    """
    form: str
    elem_count: int = 0     # BLOB_LOWER_SIZED only; 0 means "no count is known"


def blob_constructor_lowering(callee_name: str, positional=(),
                              keywords=()):
    """How to lower `List[…](…)` / `bytearray(…)`, or None when it cannot.

    ONE decision for both architectures and for every caller that needs to know
    whether a container construction produces a blob — the emitters, and
    `_value_materializes_blob`'s question about a constructor store. The last of
    those is why this is a function and not an emitter arm: a kind claimed for a
    slot has to come from the same rule the emitter applied, or
    `struct_field_kind` would open a door the emitter shuts.

      * `BLOB_LOWER_EMPTY` — no operands. Eight bytes with a zero count, which is
        `_emit_empty_blob` and is the same blob `[]` builds.
      * `BLOB_LOWER_RESERVED` — every operand is the keyword `capacity`.
        `blob_constructor_with_operands_refusal`'s own paragraph is about a blob
        that has to HOLD n ELEMENTS, and a capacity is not that: it says how much
        room to set aside, and the container it builds is EMPTY either way. So
        the value is the empty container and the reservation is not modelled.
      * `BLOB_LOWER_SIZED` — ONE positional operand that is a compile-time
        integer, and the element count it states. `bytearray(3)` is three zero
        bytes in CPython, so a blob with a count of 3 and three zero elements is
        that value exactly, and reserving it is what a list literal of three
        words reserves. **Only for a byte blob**, because `List[Int](3)` is not a
        thing the language has: a list literal says its elements, and a list
        constructor that had to HOLD three of them would be three values this
        compiler has no expression for.
      * None — anything else, refused by name.

    **The limits of `BLOB_LOWER_RESERVED`, because an answer with unstated limits
    is the thing this codebase keeps refusing to ship.** What is dropped is the
    RESERVATION and nothing else: `len` of the result is 0 and stays 0 until a
    statement appends, and the count word is a real word in a real eight-byte
    blob. What is NOT claimed is that appending to it will work: `append` into a
    blob this path did not reserve the room for is refused by name already
    (`list.append() is not lowered … the receiver is not a list literal`), so the
    dropped reservation cannot turn into a write past a blob. And a program that
    can OBSERVE a capacity is not one this path can run either way —
    `List.capacity` is not a lowered method and `unsafe_ptr` is refused — so
    there is no construct whose answer this changes from right to wrong.

    **Measured, on both architectures, on the stdlib file this was found on.**
    `std/collections/binary_heap.mojo` declares
    `def __init__(out self, *, capacity: Int): self._data =
    List[Self.T](capacity=capacity)`, and that ONE store is what kept
    `model.ctor_establishes_slot` shut for the whole file — the other four
    hundred lines' worth of constructor evidence were already in order. With this
    answer, `len(self._data)` in `__len__` lowers and `binary_heap.mojo` stops
    refusing on it.
    """
    if not empty_blob_constructor(callee_name):
        return None
    positional = list(positional or ())
    keywords = list(keywords or ())
    if not positional and not keywords:
        return BlobCtorLowering(BLOB_LOWER_EMPTY)
    if positional:
        n = _static_byte_blob_count(callee_name, positional, keywords)
        if n is None:
            return None
        return BlobCtorLowering(BLOB_LOWER_SIZED, n)
    if all(name == BLOB_CAPACITY_KEYWORD for name, _v in keywords):
        return BlobCtorLowering(BLOB_LOWER_RESERVED)
    return None


def _static_byte_blob_count(callee_name: str, positional, keywords):
    """The element count `positional` states for a byte blob, or None.

    A byte blob is the ONE container whose size an argument can state: a byte
    blob's element is one byte, so `bytearray(3)` is a request for three of them
    and the count word is the 3 itself. Everything else stays refused, and each
    refusal here is a different question rather than a shorter list:

      * not a byte blob (`List[Int](3)`) — a word blob's constructor has no
        spelling for "three of them", because three values is not an expression
        this IR has;
      * a computed argument (`bytearray(n)`) — the reservation is sized when the
        function is laid out and `n` is not known then. This is
        `blob_constructor_with_operands_refusal`'s own paragraph;
      * a keyword operand (`bytearray(length=3)`) — refused rather than guessed
        at, and `BLOB_CAPACITY_KEYWORD` is the one keyword this path knows;
      * a negative literal (`bytearray(-1)`) — CPython raises `ValueError` here,
        and a blob with a negative count is a blob whose bounds check every
        index fails.
    """
    if callee_name not in BYTE_BLOB_CTORS or keywords:
        return None
    if len(positional) != 1:
        return None
    arg = positional[0]
    if not isinstance(arg, F.IntLiteral):
        return None
    value = _int_literal_value(arg)
    if value is None or value < 0:
        return None
    return value


def subscript_callee_names(call) -> list:
    """The names a call's SUBSCRIPT callee consumes, or `[]` when it has none.

    `List[Int]()` and `f[a, b](x)` are the same shape and the same answer: the
    call names `List[Int]` / `f[a, b]`, so the base is a SYMBOL the call is
    dispatched on and the bracket is its compile-time argument list. Neither is
    a read of a value, and `build.py`'s name-placement walk already says so
    about a BARE callee (`f(x)` collects `f` and does not try to place it);
    this is the same rule one level up, and it is asked here so the walk, both
    backends and any future reader have ONE recogniser of the shape rather than
    three.

    THE NAMES RETURNED ARE NODES, not strings, and that is deliberate. The walk
    exempts by node identity because `iter_nodes` has no parent and a name can
    legitimately be placed in one position and not in another: the same `List`
    is a type in `List[Int]()` and an unplaceable value in `len(List)`. Keying
    on the string would exempt every read of that name in the function, which
    is the silently-wrong direction this whole pass is arranged to refuse.

    Deliberately NOT gated on the base being a known type name, and the reason
    is that the gate would have to be a name list, and a name list is a second
    copy of `type_constructor_kind` / `POINTEE_WIDTHS` / `BLOB_TYPE_NAMES` that
    rots the day one of them grows. A subscript in CALLEE position on a bare
    name is a type application or a generic specialization, and in BOTH the
    base is not a value — so the position itself is the evidence. The one thing
    this does give up is a name that is a genuine value AND is subscripted AND
    is called (`xs[0](f)`), which nothing in this backend lowers either way; it
    now reaches the emitter instead of the allocator, which is a better place
    for that answer to come from.
    """
    func = getattr(call, "func", None)
    if not isinstance(call, F.CallExpr) or not isinstance(func, F.SubscriptExpr):
        return []
    base = func.obj
    if isinstance(base, F.IdentExpr):
        out = [base]
    elif isinstance(base, F.MemberExpr):
        out = []
        node = base
        while isinstance(node, F.MemberExpr):
            node = node.obj
        if isinstance(node, F.IdentExpr):
            out.append(node)
    else:
        return []
    for node in iter_nodes(func.index):
        if isinstance(node, F.IdentExpr):
            out.append(node)
    return out




# ── a TYPE as a VALUE ──────────────────────────────────────────────────────
#
# A formal value is one 64-bit word, and a TYPE is not one thing a word can
# hold — which is why every name in the tables above used to be refused with
# "'Int32' has no home", a sentence that is false about the program: `Int32` is
# not a name that was left without a register, it is a TYPE, and the source
# says so in the position it stands in. `bugs/FORMAL_dtype_object_as_a_value.md`
# is the long form.
#
# The answer here is that a type IS a word on this path, and the word is a TAG:
# one number per type, the same number in every unit of the image, so
# `t == Int32` is an integer comparison and a type crosses a dylib boundary
# without a registry on either side. Three things have to be true of that tag
# and each one is a separate decision:
#
#   * it must be a function of the TYPE and not of the spelling that reached
#     it, or `Int32` and `DType.int32` — the same type, two spellings, and the
#     interpreter's own answer is that they are the same object — would be two
#     words. `type_value_name` is that function, and it is the only reader.
#   * it must be the same on both sides of a dylib boundary, so it cannot be an
#     index into a per-unit discovery order. It is a hash of the canonical
#     name, which is why it survives a build in which two units never meet.
#   * it must be DISTINCT for distinct types, and that is not a probability
#     argument: the tag is only ever asked about a name in the closed set
#     `type_value_name_space()`, and `type_value_tags_are_distinct` (asked by
#     `test_formal_run.py`) proves every pair in that set differs. A collision
#     is therefore absent from the name space this path admits, not unlikely.
#
# DERIVED, not hand-kept, wherever a table already says what a name is — a
# second list of type names is a list that goes stale the day one of the five
# grows, and it goes stale in the worst direction: the new name is then refused
# as "not a type", which reads as a fact about the language and is a fact
# about a table. The two names that are in NO table are named here, with the
# reason each is not in one.
#
# `UNREPRESENTABLE_TYPE_CTORS` is in the union BELOW and it already carries
# `NARROW_FLOAT_TYPE_NAMES` (the narrow float formats, `BFloat16` and
# `UInt128`), so that list is not re-spelled here: a second copy of a closed
# list is a second thing to forget, and this one had already been spelled twice
# — once in `POINTEES_REFUSED` for the dereference and once in the union below
# for the tag — which is how the CONSTRUCTOR of one of them came to be refused
# at the LINK AUDIT instead of by name.
TYPE_VALUE_NAMES = frozenset(
    POINTEE_WIDTHS                                   # a width, for a pointee
) | frozenset(POINTEES_REFUSED) | frozenset(
    POINTEE_FLOAT_NAMES) | frozenset(
    INT_TYPE_CTORS) | frozenset(
    IDENTITY_TYPE_CTORS) | frozenset(
    UNREPRESENTABLE_TYPE_CTORS) | frozenset(
    POINTER_TYPE_CTORS) | frozenset(
    # `Self` is in no table because every table here answers a question about
    # a type this path can REPRESENT, and `Self` is the one name whose type
    # is the enclosing declaration — which is a fact about the read, not about
    # the name. It is still a type, and `t == Self` is a question a program
    # can ask, so it gets a tag like every other.
    ("Self",
     # `bool` beside `Bool`; `Int` and `UInt` are already in POINTEE_WIDTHS.
     # `bool` is the SPELLING Python and CPython use for the same type, so a
     # program written in the shared subset (`f(bool)`) has to have an answer
     # here as well as in the interpreter — which binds `bool` to Python's own
     # `bool`, so both agree that `f(bool)` is handed the same object.
     "bool"),
)


# A `DType` member whose name is not its type's name. `DType.int` is the 64-bit
# signed type whatever its width says, and so is `DType.index`; `DType.uint` is
# the unsigned one. Three entries against the ~20 a member-by-member table
# needs — see `_dtype_member_type`.
_DTYPE_MEMBERS = {
    "int": "Int64", "index": "Int64", "uint": "UInt64",
}

# The SPELLING convention, and the reason `_dtype_member_type` is a table of
# prefixes rather than a table of members. Mojo writes a `DType` member in
# lower case and the type in upper case, and the upper-casing is not "the first
# letter": `uint8` is `UInt8`, where the capital `U` is the unsigned marker and
# `Int` is the type word. So the mapping is a FAMILY, and a family is five
# entries however many widths Mojo adds to it — the alternative is one entry per
# member, which is a list that goes stale the day a width is added and fails in
# the direction that reads as a fact about the language.
#
# The order is not load-bearing and is not relied on: no two of these are
# prefixes of one another at the same position (`bfloat16` starts with `b`, so
# only `bfloat` can match it, and `uint8` with `u`, so only `uint` can). Listed
# longest-first because that is the order that would matter if Mojo ever added
# one that did overlap.
_DTYPE_MEMBER_PREFIXES = (
    ("bfloat", "BFloat"),
    ("uint", "UInt"),
    ("int", "Int"),
    ("float", "Float"),
    ("bool", "Bool"),
)


def _dtype_member_type(member: str) -> str | None:
    """The type `DType.<member>` names, or None if this path has no such member.

    `DType.int32` is a VALUE of type `DType` naming the type `Int32`, and it has
    to be the same word `Int32` is — `std/testing/prop/random.mojo:295` writes
    `Scalar[Self.dtype].MIN.cast[DType.int64]()` beside `dtype: DType`, so the
    corpus puts two spellings of one type in the same expression, and the
    interpreter binds them to the same object (its `DType` namespace holds the
    `Int64` instance itself as `.int`, `.int64` and `.index`).

    Two steps, in this order, and the order is the design: a member whose name
    is not its type's name (`int`, `index`, `uint` — all three name `Int64` /
    `UInt64` whatever their spelling suggests) is the exception table, and
    everything else is the SPELLING, so every width and every format suffix
    Mojo writes is covered by five prefixes rather than by a member list. The
    answer is admitted only if it is a name this path knows, which is what
    keeps the name space a tag is asked about FINITE and therefore checkable.

    THE FAMILY IS CLOSED, and that is the condition rather than a detail: the
    spellings the corpus writes are admitted by NAME in `TYPE_VALUE_NAMES` (the
    float8/float6/float4 formats and `UInt128`, with their measured counts
    there), and a member outside that list is still refused with its own name.
    A rule that admitted any `float<width>_<format>` would make the name space a
    tag is asked about unbounded, which is exactly what
    `type_value_tags_are_distinct` needs it not to be — so the boundary is drawn
    once, explicitly, and every member outside it keeps a refusal that says what
    the admitted ones are.
    """
    over = _DTYPE_MEMBERS.get(member)
    if over is not None:
        return over
    for lower, upper in _DTYPE_MEMBER_PREFIXES:
        if member.startswith(lower):
            spelled = upper + member[len(lower):]
            return spelled if spelled in TYPE_VALUE_NAMES else None
    return None


def type_value_name_space() -> frozenset:
    """Every canonical type name a tag can be asked for — the CLOSED set.

    `TYPE_VALUE_NAMES` plus the exception table's own values, which is what
    makes the distinctness argument a fact about a finite set rather than a
    bound on a probability: the spelling rule in `_dtype_member_type` only ever
    produces a name that is ALREADY in `TYPE_VALUE_NAMES` (it returns None for
    any member whose type name this path does not know), so the only names it
    adds are the three a member's own spelling cannot reach.
    """
    return frozenset(TYPE_VALUE_NAMES) | frozenset(_DTYPE_MEMBERS.values())


def _tag_of_text(text: str | None) -> int | None:
    """The tag of the type a type EXPRESSION's text names, or None.

    The one place a spelling is read, because the two readers that need it have
    different inputs and must not disagree: `type_value_tag` has an AST node and
    `type_tag_for_name` has a bare name (which is all `_load_var` ever has).
    """
    if not text:
        return None
    base, dot, member = text.partition(".")
    if dot:
        # A dotted spelling is a MEMBER access, and only `DType.<member>` names a
        # type; `Self.T` and `pkg.thing` are not type values at all.
        canonical = _dtype_member_type(member) if base == "DType" else None
    elif text == "DType" or text not in TYPE_VALUE_NAMES:
        # `DType` is the type OF a type — `dtype_object_refusal` — and a name
        # this path does not know as a type is not one.
        canonical = None
    else:
        canonical = text
    return None if canonical is None else type_tag(canonical)


def type_value_tag(node) -> int | None:
    """The tag of the type `node` names as a value, or None if it names none.

    The one reader both backends ask for an EXPRESSION, so the two architectures
    cannot disagree about what a type is — which for a tag is not a diagnostic
    that differs but a comparison that comes out differently on one side.
    """
    return _tag_of_text(type_expr_text(node))


def type_tag_for_name(name: str) -> int | None:
    """`type_value_tag` for a reader that has the NAME and not the node.

    `_load_var` is handed a name, and it is the right place for the tag — see
    its own note — so this is the spelling it asks. A dotted name is never a
    type here: a `DType.<member>` reaches the backends as a `MemberExpr`, and
    every other dotted name is a field.
    """
    return None if "." in name else _tag_of_text(name)


def type_tag(name: str) -> int:
    """The word the type `name` IS on this path: a 63-bit FNV-1a of the name.

    FNV-1a because it is three lines, has no table to keep, and is a function
    of the STRING alone — which is the whole requirement. A tag has to be the
    same number in every unit of the image, including two units that were
    compiled apart and meet only at the dylib boundary, and it has to be the
    same on both architectures. Anything derived from a discovery order, a
    per-unit counter or an address fails the first of those; a hash of the name
    passes all three by construction.

    The top bit is cleared so the tag is a non-negative 63-bit number: the
    word is printed by `printf("%d")` in a diagnostic and compared as a signed
    value by a program, and neither should have to know that a type's tag can
    come out negative. Distinctness over the admitted name space is proved by
    `type_value_tags_are_distinct`, not assumed — see the note above.
    """
    h = 0xcbf29ce484222325
    for byte in name.encode("utf-8"):
        h = ((h ^ byte) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h & 0x7FFFFFFFFFFFFFFF


def type_value_tags_are_distinct() -> list:
    """Every collision among the tags of the admitted type names, as lists.

    The correctness argument for a hash being a value here, in the form a test
    can ask: the tag function is only ever asked about a name in the closed set
    `type_value_name_space()`, so if no two names in it share a tag then no
    program this path admits can observe one type as another. Empty is the only
    passing answer, and it is a fact about a FINITE set rather than a bound on
    a probability.
    """
    seen: dict = {}
    for name in sorted(type_value_name_space()):
        seen.setdefault(type_tag(name), []).append(name)
    return [names for names in seen.values() if len(names) > 1]


def dtype_member_is_a_type(member: str) -> bool:
    """Whether `DType.<member>` names a type this path gives a tag to.

    The public reader of the spelling rule, for the one caller that has a
    `MemberExpr`'s member and not the node: `formal/build.py`'s name walk sees
    the `DType` IdentExpr and never the member, so it asks this rather than
    reaching into `_dtype_member_type`.
    """
    return _dtype_member_type(member) is not None


def dtype_object_refusal(spelled: str) -> str:
    """Why a bare `DType` in a value position is not a type.

    `DType` names the type OF a type, so `DType` as a value would be the
    runtime type object — the thing `DType(Int32)` builds and `dtype.name`
    reads — and this path has no such object: a formal value is one word, and
    there is nothing in the image that a word naming "a type" could point at.
    The two things that DO work are the ones a reader can use: a member
    (`DType.int32`), which is a type this path gives a tag to, or a declared
    `dtype: DType` parameter, whose value arrives as that same tag from
    whoever passed it.
    """
    return (f"{spelled} is the type OF a type, and a type object is not "
            f"something this path has: a formal value is one 64-bit word, and "
            f"there is nothing in this image for a word to point at that "
            f"would answer 'what type is this'. A DType MEMBER names a type "
            f"and is a value here ({spelled}.int32 is the same word Int32 is) "
            f"— so spell the member you mean, or take the type as a parameter "
            f"annotated `DType`, whose value is the member's tag by the "
            f"caller's doing")


def is_dtype_member_access(node) -> bool:
    """Whether `node` is `DType.<member>` — the shape, whatever the member.

    Asked by the two backends' member arms, after `type_value_tag` has declined,
    so that a member this path has no type for is refused as the missing type
    name it is rather than as a field read off a struct. It is a SHAPE test and
    not a table lookup on purpose: the whole point is to name a member that is
    not in any table.
    """
    return (isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr)
            and node.obj.name == "DType")


def dtype_member_refusal(spelled: str, member: str) -> str:
    """Why `DType.<member>` is not a type value, given that other members are.

    A different diagnostic from `dtype_object_refusal` because it is a
    different fact: the bare `DType` is a type object and there is none, while
    this is a member that names a real Mojo type whose NAME is in no table on
    this path — a float format or a width outside the closed list in
    `TYPE_VALUE_NAMES`. Saying "a field access through 'DType'" instead (which
    is what the emitter's own fallback says, and did say, for all of them)
    sends the reader to look for a struct field where there is a missing table
    entry.

    The corpus's own spellings are no longer in that state: the float8/float6/
    float4 formats and `UInt128` are named in `TYPE_VALUE_NAMES`, so this
    refusal is now only reachable for a member no file in this repository or its
    stdlib checkout writes, and it says which names do work.
    """
    return (f"DType.{member} names a type, and this path has no value for it: "
            f"a type is a word here — its tag — and the tag is computed from "
            f"the type's NAME, which for DType.{member} is a name no table in "
            f"formal/model.py lists, so there is nothing to compute it from. "
            f"The members that do work are the ones whose type name this path "
            f"knows: DType.int8 … DType.int64, DType.uint8 … DType.uint64, "
            f"DType.float16/float32/float64/bfloat16, the DType.float8_*/"
            f"float6_*/float4_* formats, DType.uint128 and DType.bool, each of "
            f"which is the same word the bare type name is. Naming the type "
            f"instead of the member (Int8 rather than DType.int8) is the same "
            f"value and always works")


def call_is_string_frame_reading(call) -> bool:
    """Whether the build pass marked this call node as the FRAME reading of a
    zero-argument `String()` (`frames.string_frame_reading_calls`, step 10)."""
    return bool(getattr(call, "_string_frame_reading", False))


def call_lowers_as_framed_construction(callee: str, structs: dict, nargs: int,
                                       functions=(), call=None) -> bool:
    """Whether a call to `callee` reaches `_emit_struct_constructor` on EITHER
    backend.

    The emitters route a call in one order and it is worth writing the order down
    once, here, because the build pass has to answer the SAME question the
    emitter answers and the two disagreeing about it is the collision in
    `bugs/FORMAL_string_constructor_collision`:

    ```
    if name not in functions and not type_constructor_prefers_local_struct(…)
       and type_constructor_kind(name) is not None:   # a type CONVERSION
    if name in structs:                                # a struct CONSTRUCTION
    ```

    So the answer is "a struct construction" exactly when the name is a local
    declaration AND the type-constructor interception did not take it first.  A
    file that declares `struct String` and calls `String()` is the case the whole
    function exists for: `String` is in the STRING and IDENTITY tables, the
    interception is not overridden for those two (deliberately — see
    `type_constructor_prefers_local_struct`'s second bullet), so the emitter
    produces the address of an interned `char *` while the build pass's
    `_constructor_bindings` sees a call to a name in `framed_struct_names` and
    makes the target a three-slot frame HOLDER.  The store then lands in
    read-only text and the program dies with SIGBUS, exit 138, on both
    architectures.

    `functions` is the image's compiled function names, and it is the one input
    the emitter reads that is not a table: a name that is BOTH a function and a
    struct skips the interception and falls through to the construction branch.
    It is a parameter rather than a module global because the same predicate is
    asked by the build pass (which has the function list) and by nobody else,
    and a module-level table for one caller's list would be a second thing to
    keep in step.

    A name that is not a local declaration is `False` and not a refusal here: a
    call to a type this module does not declare is not a construction of
    anything, and the emitter's own answer about it is unchanged.
    """
    if call is not None and call_is_string_frame_reading(call):
        return True
    if (structs or {}).get(callee) is None:
        return False
    if callee in (functions or ()):
        return True
    if type_constructor_prefers_local_struct(callee, structs, nargs):
        return True
    return type_constructor_kind(callee) is None


def type_constructor_prefers_local_struct(callee_name: str, structs: dict,
                                          nargs: int) -> bool:
    """Whether THIS MODULE's own `struct N` beats `N`'s place in
    `UNREPRESENTABLE_TYPE_CTORS`.

    `UNREPRESENTABLE_TYPE_CTORS` is a hand-kept list of NAMES, and a name in it
    was refused outright — "constructing DType has no representation on this
    path" — without anybody asking what the file being compiled says about
    `DType`.  In a file that DECLARES `struct DType`, that declaration is the
    only thing in hand that says what the name means, and the hand-kept list
    was overriding it.  That is the defect: the list is a statement about types
    this path cannot represent *abstractly*, and a struct of one field is a
    plain word, which is the most representable thing there is.

    So the rule that was masked is the ordinary one, and ARITY is what applies
    it: a call whose argument count matches the local declaration's field count
    is a construction of that struct, and one that does not match is not — which
    leaves the name's own reading standing for every other arity, so this can
    never reclassify a call the tables already handled well.

    Two deliberate exclusions, both measured:

      * only `UNREPRESENTABLE_TYPE_CTORS` is overridden, never the identity or
        the integer tables.  `Pointer` is a struct some files in this
        repository declare AND an identity conversion, and
        `Pointer(to=stat)` over a struct's frame is the one hand-off in the
        whole family that is correct (a pointer wants the address, and a frame
        address is one).  Preferring the local declaration there would turn a
        working identity conversion into a construction, which is a change of
        MEANING rather than a change of verdict — the one direction this
        function must never go;
      * the field count must match, so `Error()` in a file that declares a
        two-field `Error` keeps the unrepresentable refusal.  That file is not
        in the corpus, and the point is that the rule does not need it to be:
        arity decides, and an unmatched call is left exactly as it was.

    Everything here is a change of VERDICT in one direction only: the
    'unsupported' branch is a refusal today, so preferring the local struct can
    turn a refusal into a lowering and can never change the meaning of a program
    that already built.

    The ZERO-ARGUMENT form is the second half of the answer, and it is the one
    that was still wrong. `S()` — no arguments — is not an arity to match
    against a field count: it is Mojo's own struct syntax, the shape
    `_emit_struct_constructor` was written for and the only one that used to
    exist. So for a name this image knows as a struct, `S()` is a construction
    of that struct and the struct's own field count decides whether it is
    representable — which is the whole of the rule everywhere else in this
    file. Left as it was, `struct DType: var _mlir_value: Int` — ONE field,
    and a formal value is one 64-bit word, so a `DType` is as representable as
    anything here — was refused with the sentence "a formal value is one 64-bit
    word, and DType is not one thing", which is false, while the identical
    program with the struct renamed built on both architectures. The arity test
    also masked the rule that actually stops the neighbouring case: `DTypeX(7)`
    is refused by the shape rule (`DTypeX(...) takes no arguments on this
    path`), not by anything about representability, and the name list got there
    first and said something else.
    """
    if callee_name not in UNREPRESENTABLE_TYPE_CTORS:
        return False
    st = (structs or {}).get(callee_name)
    if st is None:
        return False
    return nargs == 0 or nargs == len(struct_frame_slots(st))


# The subset of `IDENTITY_TYPE_CTORS` that ASKS FOR AN ADDRESS rather than
# yielding a `char *`: the identity constructors over an opaque word.  A
# pointer is already one word and constructing one is a no-op on this path
# (`type_constructor_kind` answers `("identity", None)`), so `Pointer(to=x)`
# yields the word it was handed — and for a multi-field struct that word is the
# frame's base address, which is exactly what a pointer to the object means.
#
# Derived, not written out, because the question this table answers is "does
# this callee DEREFERENCE its argument" and that is precisely what
# `IDENTITY_TYPE_CTORS` minus `STRING_TYPE_CTORS` already says.  A hand-written
# copy is how the two would come apart: a name added to the identity set and not
# to this one gets refused with a message whose reasoning is inverted, which is
# the defect `Pointer` was carrying.
#
# MEASURED, both architectures, rather than inferred from the tables. Three
# two-field objects in one function, each constructor's address taken with
# `Pointer(to=…)`, come out 16 and then 32 bytes apart — the frame size — so
# these are three consecutive frames and not three unrelated leftover words.
# With the frame-escape refusal in place the same program is refused, which is
# the unjustified refusal this removes.
#
# The consumer is `frame_receiver_escape_refusal`, whose FIRST branch is this
# table: a hand-off to one of these names is not a refusal at all. What it does
# not make safe is a DEREFERENCE through the result, and that is already refused
# by name and for its own reasons — `DEREFERENCE_METHODS` covers `value` and
# `unsafe_value`, and says why in terms a reader can act on (an 8-byte load
# over-reads a `UInt8` pointee by seven bytes and can fault on a page boundary;
# for a struct pointee there is nothing at the address to load, because a
# struct's value on this path IS a frame address). So the word that escapes here
# is one that nothing on this path dereferences.
FRAME_ADDRESS_CTORS = tuple(
    n for n in IDENTITY_TYPE_CTORS if n not in STRING_TYPE_CTORS)




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


def struct_bracket_param_names(struct_def) -> frozenset:
    """The names the struct's BRACKET declares, which are never storage.

    `struct Tagged[T, origin: Int]` declares two compile-time parameters: `T`
    is a TYPE and `origin` is a value supplied at the application
    (`Tagged[Int, 7]`).  Neither has a slot in an instance — the value is
    substituted into the template's body when the instantiation is built, which
    is why `formal/monomorph.py::instantiate` drops the whole head.

    `fire_compiler._parse_struct_params_as_fields` nevertheless puts the
    ANNOTATED ones in `StructDef.fields` (the interpreter's member read is
    written against that shape), so a reader that answers "what is this
    struct's storage" has to subtract exactly these names and nothing else.
    `struct_field_names` is that reader, and the report is the one-field
    instantiation whose segment faulted when a free function took it:
    the unapplied TEMPLATE measured one field wider than its one-field
    instantiation, so a free function taking `Tagged[Int, 7]` was compiled as
    a FRAME receiver while the caller passed the field by value, and the
    program segfaulted on both architectures.

    Empty for a struct with no bracket, and for every struct parsed before this
    list existed (`getattr` default), which is the direction that leaves an
    existing answer where it was."""
    return frozenset(getattr(struct_def, "bracket_params", None) or ())


def struct_field_name(field) -> object:
    """The name this one `StructDef` field introduces, or None if it has none.

    A field arrives in either of the two shapes fire_compiler's parser puts in
    `StructDef.fields` — everything in a struct body that is a `VarDecl` or an
    `AssignStmt` is a field, because a class-level assignment IS a field with a
    default on this path:

      * `VarDecl` — written as an annotation, `x: int` (or `x: int = 0`, which
        the parser keeps as an `AssignStmt` carrying `type_ann`); the name is
        `field.name`.
      * `AssignStmt` — written as a plain class-level assignment, `x = 1` or
        `__slots__ = (...)`; the name is `field.target.name`.

    So the two shapes carry the name in different places, and every reader has
    to ask here. Reaching for `.name` directly works for the first and raises
    `AttributeError` on the second, which is how `__slots__ = (...)` in a
    one-field struct used to abort a build with a Python traceback instead of a
    diagnostic. None means the field binds no name at all (a class-level
    `obj.attr = 1`); callers that need a name must treat that as a real error
    rather than guess one."""
    if isinstance(field, F.VarDecl):
        return field.name
    if isinstance(field, F.AssignStmt) and isinstance(field.target, F.IdentExpr):
        return field.target.name
    return None


# The class-level assignment that DECLARES fields rather than making one, and
# the two names a `__slots__` tuple may carry that are not storage at all
# (Python adds them itself to a class that wants weak references or a
# `__dict__`). Counting either would make a one-field `__slots__` class look
# like a two- or three-field one, i.e. refuse a struct that is representable.
SLOTS_FIELD = "__slots__"
_PSEUDO_SLOTS = ("__dict__", "__weakref__")


def _slots_names(value) -> list:
    """The field names a `__slots__ = (...)` value declares; [] if it is not one.

    `__slots__` is the one class-level assignment that is a declaration rather
    than a definition: it names fields instead of storing into one, and it is
    the only place a class can name a field it never assigns. Reading it is
    what keeps `__slots__ = ("it",)` in a class whose `__init__` does
    `self.it = ...` from being counted as two fields (`it` and `__slots__`)
    rather than the one field it is."""
    if not isinstance(value, (F.TupleExpr, F.ListExpr)):
        return []
    out = []
    for el in getattr(value, "elements", None) or []:
        if isinstance(el, F.StringLiteral) and isinstance(el.value, str) \
                and el.value not in _PSEUDO_SLOTS:
            out.append(el.value)
    return out


def _assignment_targets(node) -> list:
    """The targets one assignment statement binds, in source order.

    Three AST shapes and no fourth: `a = b` and `a += b` are an `AssignStmt` /
    `AugAssignStmt` with a `target`, and a chained `a = b = v` is a
    `MultiAssignStmt` with `targets` — so a scan reading only `target` misses
    every target past the first in the chained spelling.

    **`DelStmt` is deliberately NOT here.** `del self.x` is not a store, so it
    establishes no instance attribute, and the question this feeds asks whether
    one exists. A `del` over a name this struct also declares as a METHOD
    therefore leaves the name demotable, which is the right answer: the source
    says the attribute is not there.
    """
    if isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
        return [node.target]
    if isinstance(node, F.MultiAssignStmt):
        return list(node.targets or [])
    return []


def receiver_target_names(target, receivers) -> list:
    """The field names one assignment target binds, or [] if none does.

    A target is a field access only when its base is a receiver NAME, so
    `self.x`, `(self.x, self.y)` and `self.x, = v` are fields and `p[i]`, `a.b`
    and a bare local are not — the last of which is what keeps `self.x = y` from
    claiming a field named `y`.

    Module-level rather than a closure over one `receivers`, because three
    separate questions ask it and each had its own copy: what `__init__`
    assigns (`_init_field_assignments`), and what ANY method of the struct
    stores (`struct_receiver_stores`, which is what decides whether a name that
    is also a method name is an instance attribute or a bound method). Three
    copies of the target shapes is three places for a fourth spelling to be
    added to one of them.
    """
    if isinstance(target, F.MemberExpr):
        return ([target.member]
                if isinstance(target.obj, F.IdentExpr)
                and target.obj.name in receivers else [])
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return [n for el in getattr(target, "elements", None) or []
                for n in receiver_target_names(el, receivers)]
    return []


# Node types that are NOT statements and still hold some: a compound
# statement's own container is not itself a statement of the enclosing block, but
# its list fields are full of them. Measured over the 712 `.py`/`.mojo` files of
# this repository and the stdlib — every non-statement node type with a LIST
# field that holds a statement directly, which is the whole of the set:
#
#   FunctionDef.body   68 974      a nested def, and a method of a nested class
#   ExceptHandler.body  1 880      `except E:` / `finally:` arms
#   MatchCase.body        253      `case p:` arms
#   StructDef.fields      383      a class body's field declarations
#
# and no non-statement node type with a SCALAR field holding one, which is the
# fact the descent below depends on. `LambdaExpr` is in the set although the
# corpus never puts one there: `LambdaExpr.body` is typed `object`, so a lambda
# whose body parses as a statement list is representable, and a walk that cannot
# see it would lose an assignment silently rather than loudly. Its other list
# fields hold strings, so descending into it costs nothing.
#
# `tools/formal_field_walk_differential.py` is what keeps this tuple honest: it
# compares the walk against `iter_nodes` per struct over the whole corpus, and
# the first version of this walk, without the tuple, was caught by it on four
# structs — `fire_compiler.py`'s `TestSuite` (a nested class inside a method),
# `std/iter`'s `_ChainedIterator` (an `except` arm) and two more.
_STATEMENT_CONTAINERS = (F.FunctionDef, F.StructDef, F.MatchCase,
                         F.ExceptHandler, F.LambdaExpr, F.Module)


def _is_statement_node(node) -> bool:
    """True when `node` is a STATEMENT, by the parser's own naming convention.

    `fire_compiler.py` has no base class for statements — `ExprStmt`,
    `AssignStmt`, `ComptimeIfStmt` and the rest are independent dataclasses — so
    "is this a statement" is a NAME question, and this is the one place it is
    asked. The suffix rather than an enumerated set, deliberately: a node type
    added later is a statement by construction and belongs in the walk, while an
    enumerated set is a list somebody has to remember to edit, and the only way
    it is discovered to be out of date is that a field stopped being found.

    A FALSE POSITIVE is harmless and a false negative is not, and that asymmetry
    is what the choice rests on: yielding and descending into a non-statement is
    what `iter_nodes` does everywhere anyway, so naming one a statement costs
    nothing; missing a statement hides an assignment, and a hidden assignment is
    two real fields aliased into one slot.
    """
    return hasattr(node, "__dataclass_fields__") \
        and type(node).__name__.endswith("Stmt")


def iter_statement_nodes(node, *, enter_nested_defs=True):
    """Every STATEMENT in a statement tree, and nothing else.

    The descent is through LIST- and TUPLE-valued fields, through statement
    nodes and through `_STATEMENT_CONTAINERS`, and it stops at the first node
    that is neither — which is the whole of the saving. A statement's
    sub-statements are always reached through a list (`IfStmt.then_body`,
    `ForStmt.body`, `TryStmt.handlers`, `MatchStmt.cases`; an `ExprStmt` is a
    leaf), while its EXPRESSIONS hang off scalar fields and off the arguments of
    expression nodes, and an expression subtree cannot contain a statement. So a
    walk that stays inside statements reaches every assignment and visits none
    of the expressions, and the two walks agree by construction rather than by
    luck.

    **`enter_nested_defs=False` stops at a nested `def`, which is a FRAME
    boundary and not a shape.** `formal/build.py::_flatten_closures` turns a
    nested `def` into a lifted function of its own, so its body is a separate
    function's body with its own parameters, its own stores and its own
    `nonlocal` declarations — and a question asked of the ENCLOSING function
    about "does this body store `x`" gets the nested function's stores as its
    own. `nonlocal_write_refusal` is the caller that needs the boundary, and the
    flag is here rather than a second walker because the descent rules above are
    the whole of what makes this walk correct over 712 corpus files, and a copy
    would be a second thing to keep true of them.

    **The precondition is a corpus result and the differential is what keeps it
    one.** Over the 712 `.py`/`.mojo` files of this repository and the stdlib:
    every sub-statement is reached through a list field of a statement or of a
    `_STATEMENT_CONTAINERS` node, and there is no statement behind a scalar
    field anywhere. That is also why the walk is safe against a node type added
    later: a new STATEMENT is a `…Stmt` and is yielded, a new CONTAINER is the
    one thing that needs the tuple above edited, and the differential says so
    rather than a field quietly disappearing from a struct.

    **This is the third caller's complaint about `struct_receiver_stores`, at 2.05 s
    of the 3.4 s left in a `myinterpreter.py` build: that derivation visits
    6 160 632 nodes to find the few thousand assignments it exists for, and it is
    asked once per (struct, question), so the walk multiplies by every struct in
    the module.
    """
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from iter_statement_nodes(x, enter_nested_defs=enter_nested_defs)
        return
    names = _node_subtree_fields(node) if hasattr(node, "__dataclass_fields__") \
        else None
    if names is None:
        return
    if _is_statement_node(node):
        yield node
        if not enter_nested_defs and _is_function_def(node):
            return
    elif not isinstance(node, _STATEMENT_CONTAINERS):
        return
    for name in names:
        value = getattr(node, name, None)
        if isinstance(value, (list, tuple)):
            yield from iter_statement_nodes(value,
                                            enter_nested_defs=enter_nested_defs)


def _is_function_def(node) -> bool:
    """Whether `node` is a nested `def` — the one FRAME boundary in a body.

    A name rather than `isinstance(node, F.FunctionDef)` because the statement
    walk is reached from tables that hold nodes by class NAME (this file's own
    `type(node).__name__ != "NonlocalStmt"` arms do the same, for the same
    reason: the AST classes are re-created by every importer, so an
    `isinstance` against one module's copy is an identity test that a re-parsed
    module fails).
    """
    return type(node).__name__ == "FunctionDef"


def struct_receiver_stores(struct_def, receivers) -> set:
    """Every `<receiver>.<name>` ANY method of this struct stores into.

    The write half of Python's own rule that a read of a method name has to
    answer by, and the reason it is asked over the WHOLE struct rather than
    over one method: `__init__` writes `self.helper` and `size` reads it back,
    so the read's own method carries no evidence either way.

    **A STATEMENT walk and not `iter_nodes`, and the reader is
    `iter_statement_nodes` because an assignment is a statement.** This is the
    last per-node cost in this derivation, and it is asked 2 245 times over
    `myinterpreter.py` — once per (struct, question) — so the walk multiplies by
    every struct in the module. `_assignment_targets` decides whether a node is
    an assignment at all, so every expression node the full walk visits is a node
    this one looks at and rejects; that was 6 160 632 nodes for the few thousand
    assignments found, 2.05 s of the build's remaining 3.4 s.

    The obvious cheaper move — test the node's CLASS once instead of calling
    `_assignment_targets` per node — was measured and is NOT what is here: it
    bought 2.11 s → 2.05 s, inside the run-to-run noise, because the cost was
    never the call. Reaching the assignments through ~8x fewer nodes is what
    moved it, and it needs a corpus measurement to be sound at all, which is
    `tools/formal_field_walk_differential.py`'s job.
    """
    out = set()
    for method in struct_methods(struct_def):
        for node in iter_statement_nodes(getattr(method, "body", None)):
            for target in _assignment_targets(node):
                out.update(receiver_target_names(target, receivers))
    return out


def struct_demoted_method_names(struct_def, receivers) -> set:
    """The names this struct declares as a METHOD and no method of it stores into.

    The demotion set of Python's own shadowing rule, in one place, because two
    questions ask it (`struct_method_receiver_reads` below, which subtracts it
    from what a body reaches, and `formal/build.py`'s
    `check_value_position_method_reads`, which refuses a read of one) and each
    of them used to derive it from `struct_receiver_stores` on its own — a
    census over EVERY method's body, so a question asked per method asked it
    once per method squared.
    """
    methods = {m.name for m in struct_methods(struct_def)
               if getattr(m, "name", None)}
    return methods - struct_receiver_stores(struct_def, receivers)


def struct_method_receiver_reads(struct_def, receivers) -> list:
    """`[(method, reached, fields)]` per method of this struct.

    `reached` is `_receiver_names` — every name the method spells as
    `<receiver>.<name>` — and `fields` is that less the demotion: every name
    that is a METHOD of this struct and that no method of it stores into. A
    demoted name is not a field at all: `self.helper` in a value position is
    the bound method, which is not a word, so counting it invents a slot that
    nothing ever writes and every read of it returns zero.

    **The rule is Python's own, and both halves of it matter.** An instance
    attribute SHADOWS the class's method, so a name this struct both declares
    as a method and stores into IS a field and stays one — that is what
    `struct_receiver_stores` above establishes. A name it only READS is the
    method.

    …and a name that is neither is untouched, which is why the demotion is a
    subtraction of a set this struct's own declarations produce rather than a
    filter on everything: `self.x = 1` in a class with no method `x` is a
    field, and the overwhelming majority of fields are exactly that.

    **ONE census and ONE walk per method for the whole struct, which is why this
    is a list and not a question about one method.** Both halves of the answer
    are properties of the struct, and asking either per method re-walked every
    method's body once per method: `analyze_benchmarks_types.py`'s
    `build --formal` made 15,618 whole-struct walks for 18 distinct structs,
    322M node visits, and 91% of the build's time — which is why 361 of the 644
    files in the 2026-10-02 sweep had no verdict at all (every one a timeout at
    `-t 30`, not one a memory kill). Measured after: that file's build went
    65.9s to 4.8s of CPU and `std/builtin/int.mojo`'s 30.1s to 3.9s, same
    verdict from both. Both in-tree callers take the whole list.

    **Both sets are returned, not just the demoted one**, because
    `_split_declaration` needs the union of the UNDEMOTED reads for its
    class-level clause (a name the class body DECLARED is storage the language
    spells out, so a method that reads it makes it a field even when the name
    is also a method) and the per-method demoted sets for the undeclared ones.
    Returning one walk's two answers is what keeps that from being two walks
    over every method body, which is what it was: the same
    `_receiver_names` result was derived once for the union and again per
    method."""
    demoted = struct_demoted_method_names(struct_def, receivers)
    out = []
    for method in struct_methods(struct_def):
        reached = _receiver_names(getattr(method, "body", None), receivers)
        out.append((method, reached, reached - demoted))
    return out


def _self_field_names(node, out: set, receivers=("self",)) -> None:
    """Add to `out` every name reached as `<receiver>.<name>` under `node`.

    A field access either way round declares a field: `self.x = 1` writes one,
    and a bare `self.x` reads one that some other method (or the caller) filled
    in. A Python class that only ever READS a field declares it just as really
    as one that assigns it, and a width computed from the assignments alone
    would call such a class a zero-field marker and then compile a read of
    storage that nothing ever wrote.

    A method call is not a field access. `self.helper()` names a method, and
    counting it would add a field to every class that calls one of its own
    methods — enough to make a genuinely one-word class measure wide. So a
    `CallExpr` whose callee is `<receiver>.<name>` contributes nothing and its
    callee is not descended into, while its arguments still are (a method can
    be handed `self.x` as an argument, which is a real field access).

    **The same is true of a method call THROUGH BRACKETS**, `self.helper[T](x)`,
    and getting that wrong was a silent wrong answer on the stdlib's most-used
    type rather than a refusal. A generic's comptime parameters are written as a
    subscript on the callee, so the callee of that call is a `SubscriptExpr`
    over the very `MemberExpr` this guard tests, and the guard did not match:
    the walk fell through to the generic arm, found `MemberExpr(self,
    helper)`, and added `helper` to the field set. The name is a METHOD, so
    nothing ever writes the slot it now occupies, and every read of that slot is
    zero.

    Measured on `std/collections/optional.mojo`, where `Optional` has exactly one
    instance field (`_value`) and one private method reached through brackets:

        self._write_to[is_repr=False](writer)      # write_to's body
        ->  struct_field_names(Optional) == ['_value', '_write_to']
        ->  struct_field_count 2, so struct_is_framed True

    and the consequence was that `Optional` — a ONE-word value whose receiver IS
    its field — became a two-field struct, so every `Optional` receiver became a
    frame address and the `builtin_slice.mojo` row was refused for a
    struct-typed field the source says is a single slot. That shape is
    `test_formal_method_param_field.py`'s "a struct-typed FIELD, initialised
    from a constructor ARGUMENT" case, and the field-representation question
    behind it is `formal/model.py::struct_field_names`.
    The SIBLING shape — a bare `self.helper` in VALUE position, which is not a
    call at all — is not this guard's business and is not settled here either;
    `struct_method_receiver_reads` is what decides it, by demoting a name the struct
    declares as a method and never stores into.

    The subscript's own base is unwrapped for the guard and the brackets are
    then walked, so a subscript on a FIELD (`self.items[0]`) still contributes
    `items`: only the callee position is exempt. The bracket expressions and the
    call arguments are walked as before, because a method can be handed
    `self.x` in any of the three positions.

    A nested `FunctionDef` is not descended into either: its `self`, if it has
    one, is a different binding from the struct's receiver.

    `receivers` is every spelling this struct's own methods bind their receiver
    to — `self` plus each method's first parameter (see `struct_receivers`).
    It was `self` alone, which missed a class written `def __init__(this)` or a
    `@classmethod def is_float(cls, …)`: their `this.n` / `cls._SIGNED` were
    invisible here, so a field written only that way looked unwritten. Missing
    a field is the direction that aliases two real fields into one slot, so the
    receiver set is a superset of the obvious spelling rather than just it.

    **The sequence clause is `(list, tuple)`, and `list` alone was a blind spot
    over EVERY keyword argument.** `CallExpr.kwargs` is `list[tuple[str, Expr]]`
    — a list of PAIRS — so the `list` arm matched it, each `x` was a tuple, and
    the walk fell through to the generic arm, where a `tuple` has no
    `__dataclass_fields__` and contributes nothing at all. So
    `self._untyped_callee` in

        reason = M.string_binary_refusal(op, …, untyped_callee=self._untyped_callee)

    never reached the field set, on the one path this rule exists to get right:
    a field missed is two real fields aliased into one slot. `iter_nodes`, a few
    lines below, reads `(list, tuple)`, so the file had two node-walkers that
    disagreed about what a tuple is — which is what `iter_nodes` is shared for
    and says so in its own docstring. It is the last of three such spellings
    this function has had to be taught; the bracketed method call in this
    docstring is the second. The third — the value-position method reference,
    which this walker deliberately KEEPS counting and `struct_method_receiver_reads`
    demotes — is the other half of the pair, and both are pinned together by
    `test_formal_bracketed_method_field_set.py`'s field-set group, which is where
    a change to either has to show up."""
    if isinstance(node, (list, tuple)):
        for x in node:
            _self_field_names(x, out, receivers)
        return
    if isinstance(node, F.FunctionDef):
        return
    if isinstance(node, F.CallExpr):
        # `method_callee_base` is the ONE recogniser for "this call's callee is
        # a member of a receiver", over both spellings — the same relationship
        # `formal/build.py`'s `_method_call_target` walks when it rewrites the
        # call, so the field set and the rewrite cannot come to disagree about
        # which calls are method calls.
        base = method_callee_base(node)
        if isinstance(base, F.MemberExpr) and isinstance(base.obj, F.IdentExpr) \
                and base.obj.name in receivers:
            if not isinstance(node.func, F.MemberExpr):
                for br in _subscript_brackets(node.func):
                    _self_field_names(br, out, receivers)
            for a in node.args or []:
                _self_field_names(a, out, receivers)
            for _k, v in (node.kwargs or []):
                _self_field_names(v, out, receivers)
            return
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr) \
            and node.obj.name in receivers:
        out.add(node.member)
        return
    for fname in _node_subtree_fields(node) or ():
        _self_field_names(getattr(node, fname, None), out, receivers)


def method_callee_base(call):
    """The member a call reaches, over BOTH spellings of a method call.

    `recv.m(x)` and `recv.m[T](x)` are the same call — the second is the first
    with a generic's comptime parameters written as brackets on the callee — so
    anything asking "is this call a method call?" has to answer the same for
    both. It was `formal/build.py`'s `_method_call_target` alone, and a name walk
    recognising only the bare spelling therefore read the bracketed one as a
    FIELD access (`_self_field_names`, where the effect was `Optional` measuring
    two fields because of `self._write_to[is_repr=False](writer)`).

    Returned UNWRAPPED, so each caller decides what the brackets mean: a call
    rewrite passes them on as the callee's leading comptime arguments, and a
    field walk skips them because the member itself is what it was looking for.

    **Five readers, and the number is the argument for it being here** (2026-10-03
    added the last three): `formal/build.py`'s `_method_call_target` (which lifts
    the call), its `_receiver_shape_refusal` (which refuses the lift that did not
    happen, and which read `call.func` directly until then — so `recv.m[T](x)`
    never reached it at all), its `_call_receivers` (the frame analysis's census
    of call positions), and `_self_field_names` below. Four of the five had each
    written the strip themselves; the fifth was the one that made the two
    SPELLINGS of a call two different questions with two different answers, which
    is the failure this function exists to make impossible.
    """
    func = getattr(call, "func", None)
    if isinstance(func, F.SubscriptExpr):
        func = func.obj
    return func


def _subscript_brackets(sub) -> list:
    """The expressions inside a subscript's brackets, flattened, in source order.

    `a[x]`, `a[x, y]` and `a[k=v]` all land here: `SubscriptExpr` keeps the
    positional index in `index` and the keyword ones in `attrs`, and a field
    read can be written in either. One flat list, because the caller is walking
    "everything a node reaches" and one shape to iterate is what keeps the three
    positions from being handled three times.
    """
    out = []
    for node in (getattr(sub, "index", None),
                 *(getattr(sub, "attrs", None) or [])):
        if isinstance(node, tuple):
            out.extend(x for x in node if x is not None)
        elif node is not None:
            out.append(node)
    return out


def _decorator_names(method) -> set:
    """The decorator names on a method, as bare strings.

    `@staticmethod` / `@classmethod` are spelled bare in the source and arrive
    as the string; a call form (`@functools.wraps(f)`) arrives as a CallExpr
    and contributes only its callee, which is enough to keep it from matching
    the two names that matter here."""
    out = set()
    for d in getattr(method, "decorators", None) or []:
        if isinstance(d, str):
            out.add(d)
        elif isinstance(d, F.IdentExpr):
            out.add(d.name)
        elif isinstance(d, F.CallExpr) and isinstance(d.func, F.IdentExpr):
            out.add(d.func.name)
    return out


def struct_receivers(struct_def) -> set:
    """Every name this struct's own methods bind their receiver to.

    `self` — the overwhelmingly common spelling — plus the first parameter of
    every method that HAS a receiver, which is the same binding written
    differently: `def __init__(this)` stores into `this.n`, and a
    `@classmethod def is_float(cls, …)` reads the class through `cls`. Both are
    real member accesses, and a receiver set that recognised only the literal
    `self` could not see them, so a field written only that way looked
    unwritten — and a field that looks unwritten is the one error this whole
    rule is built to avoid.

    A `@staticmethod`'s first parameter is NOT a receiver; it is an ordinary
    argument, and treating it as one made `myinterpreter.Interpreter` measure 34
    fields instead of 10 (every `node.<attr>` an `@staticmethod` helper read
    became a field of the class it happened to live in). That is the safe
    direction and a useless one — a census that calls an argument a field stops
    being a census — so the decorator decides, and an unrecognised decorator
    form is treated as HAVING a receiver."""
    out = {"self"}
    for m in struct_methods(struct_def):
        name = method_receiver_name(m)
        if name is not None:
            out.add(name)
    return out


def method_receiver_name(method) -> object:
    """The name ONE method binds its receiver to, or None if it takes none.

    The per-method half of `struct_receivers`, and a function rather than an
    inline copy of its loop because a caller that needs the receiver of the
    method it is looking at — not of the struct, which has as many methods as it
    has receiver spellings — must not answer a slightly different question. It
    answers the receiverless case too, which is the one the class-wide set
    cannot: `def first():` declares a method with no receiver at all, and
    nothing about it is a member access.
    """
    if "staticmethod" in _decorator_names(method):
        return None
    params = list(getattr(method, "params", None) or [])
    if params and isinstance(params[0], (tuple, list)) and params[0]:
        first = params[0][0]
        if isinstance(first, str):
            return first
    return None


def method_declares_receiver(method) -> bool:
    """Whether this method's DECLARATION spells a receiver as its first parameter.

    The question `method_receiver_name` above answers "which name", and this one
    answers "is it a receiver at all" — which is a different question and the
    source of an argument-binding defect.

    `method_receiver_name` returns the first parameter's name whatever it is
    called, which is what makes `def __init__(this)` and `@classmethod def
    is_float(cls, …)` work: `this` and `cls` are receiver SPELLINGS, and the
    name is not how the language recognises a receiver, the first parameter's
    position is. But a first parameter called `x` is not a receiver in any
    spelling this language has, and treating it as one is not a harmless
    generality:

    * `formal/build.py`'s `_rewrite_method_calls` prepends the receiver to the
      call's argument list for every method this returns True for, and
      `function_param_shape` / `incoming_args` read `fn.params` verbatim. For a
      method that DECLARED its receiver those agree — `params[0]` is the
      receiver's slot and the prepended word lands in it. For a method that did
      not, they do not: the prepended receiver lands on the first DECLARED
      parameter and every argument after it is off by one, with one argument
      too many.
    * The safe direction held only by luck. Measured on this tree,
      `struct Box: def run(x: Int, r: R)` called `bx.run(0, r)` is refused —
      first by `check_holder_agreements` ("`r` … every call site hands it
      something else: passes the literal 0", which is false: it passes `r`),
      and, for the specialized spelling, by `bind_call_arguments` ("too many
      positional arguments (3 for 2 parameter(s))"), which is also false. Both
      are refusals for reasons that are not operating, on a program whose only
      real problem is spelled in its own source.

    **What the corpus says about the cost of refusing**, measured by walking
    every `.mojo` file in the tree and asking this of every method that HAS
    parameters: 118 files, 6 such methods, and all 6 spell the receiver `self`
    (`bootstrap_test_classes.mojo`, `class_jit.mojo`,
    `formal/examples/wide_recv.mojo`). A `@staticmethod` is excluded by its
    decorator rather than by its first parameter, which is the shape
    `std/python/python.mojo`'s `import_module` is (`FORMAL_staticmethod_is_compiled_
    as_an_instance_method.md`'s other half). So refusing costs 0 files here.

    The answer is deliberately about the SPELLING rather than about the count,
    because a count cannot distinguish `def m(self, x)` from `def m(x, y)` and
    the count is the thing that is already believed twice.
    """
    if "staticmethod" in _decorator_names(method):
        return False
    params = list(getattr(method, "params", None) or [])
    if not params or not isinstance(params[0], (tuple, list)) or not params[0]:
        return False
    return params[0][0] in RECEIVER_PARAMETER_SPELLINGS


def method_without_a_receiver_parameter_refusal(struct_name: str,
                                                member: str) -> str:
    """Why a method with parameters and no receiver parameter is not lowered.

    The refusal for the shape `method_declares_receiver` rules out, and it
    exists because both of the answers this path had for it were wrong in the
    same direction: bind the receiver as if the method took one and every
    argument after the first is off by one, or bind it as if the method took
    none and the caller's receiver is silently dropped. Neither is a question
    about the program, and a reader sent to either is sent to fix an argument
    list that is correct.

    The advice is the one that makes the program work, and it is spelled as the
    source change rather than as a rule: put the receiver back.
    """
    return (f"{struct_name}.{member}() is declared with parameters and no "
            f"receiver: its first parameter is an ordinary argument, so this "
            f"path cannot tell whether a call passes the receiver before it "
            f"or not — bind the receiver as an ordinary word would shift every "
            f"argument after it by one, and ignore it would drop it. A method "
            f"here takes its receiver as its FIRST parameter, named "
            f"{'/'.join(sorted(RECEIVER_PARAMETER_SPELLINGS))}, which is the "
            f"same program with an argument list this path can read")


# The spellings a receiver parameter is written with. `struct_receivers`
# derives the field-reading set from them and `method_declares_receiver` below
# requires one, so the two cannot come apart; a method that writes it some
# other name is refused by name rather than half-supported.
RECEIVER_PARAMETER_SPELLINGS = frozenset({"self", "this", "cls"})


def struct_declared_names(struct_def) -> list:
    """The class body's own names, in declaration order, `__slots__` expanded.

    The `fields` list minus the `__slots__` bookkeeping, kept as a function
    because the demotion rule below needs the ORDER (a positional constructor
    fills fields in declaration order) and because `struct_field_names` needs
    the same list without recomputing it."""
    out, seen = [], set()
    for field in struct_fields(struct_def):
        slots = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        for name in (slots or [struct_field_name(field)]):
            if isinstance(name, str) and name not in seen:
                seen.add(name)
                out.append(name)
    return out




# ── Telling a class-level CONSTANT from per-instance state ───────────────
#
# `struct_field_names` counts a class-level assignment as a field, because it
# has no type information and cannot tell `x = 1` (a constant every instance
# shares) from `x: int` (a slot per instance). Counting both is the safe
# direction — a constant counted as a field can only cause a refusal, never a
# wrong answer — and for a long time it was also the ONLY direction. The
# conservative direction is only free while it costs nothing, and here it cost
# the whole arm64 sweep's headline number: `GimpleGen` was reported as a
# 263-field receiver whose first fields were `BUILTIN_VALUE_MAP,
# _KNOWN_EXCEPTION_NAMES, _KNOWN_SIGS`, i.e. the diagnostic led with its lookup
# tables, and 15 of the 263 were not fields at all.
#
# So the rule is a real one, derived from the whole translation unit rather
# than from the class body, and it is deliberately lopsided: EVERY doubt
# resolves to "field". Naming an instance field a constant is the catastrophic
# error on this path — the receiver is then treated as narrower than it is, two
# real fields collapse into one slot, and the program builds, runs, and returns
# the wrong number. Naming a constant a field is a refusal with a good message.
# Nothing below may resolve a doubt the other way.
#
# The rule: a class-level name is a CONSTANT — not per-instance state — when
# every one of these holds.
#
#   1. It is declared in the class body and NOT named by `__slots__`.
#      `__slots__` is a declaration of instance storage in the language itself,
#      so a name it lists is a field whatever else is true of it.
#   2. No method of this struct reaches it through the receiver (`self.NAME`,
#      `this.NAME`, `cls.NAME` — see struct_receivers). A read through the
#      receiver is what the member-access lowering turns into a local slot
#      spelled `self.<name>`, and nothing here can prove such a slot is not
#      this struct's own storage, so it stays a field.
#      This one is not only conservative, it is what makes the `self.CONST`
#      spelling CORRECT: a one-field struct's receiver IS its field, so
#      `return self.A` with `A = 3` reads the word `A()` left there, and
#      `struct_default_word` is what put the 3 there. Demote `A` instead and
#      the read falls to a slot nothing ever writes, which is 0 — so the
#      materializing rewrite in formal/build.py would have to reach the
#      receiver spelling too. Keeping the name a field gets it right for free,
#      and the existing `struct_default_word_int` case is that program.
#      …and this clause is the one a `comptime` binding is exempt from, for the
#      reason the carve-out at the end of this section gives: a `comptime`
#      binding has no word behind it, so there is no slot to keep.
#   3. Nothing in the translation unit WRITES it through any object —
#      `obj.NAME = …`, `obj.NAME += …`, `for obj.NAME in …`, `del obj.NAME`
#      (see `unit_field_evidence`). This is the load-bearing clause, and the
#      reason the rule is sound: on this path a field that is never written
#      through a receiver can only ever READ as the same value in every
#      instance (an unwritten local slot, which is 0), so it carries no
#      per-instance state to lose. A class that merely NAMES a field without
#      writing it is clause 6's business, not this one's.
#   4. Nothing in the translation unit fills it by NAME — a keyword argument
#      (`Point(x=1)`) or a positional argument to this struct's constructor
#      (which fills declared fields in declaration order). A dataclass whose
#      fields are all set in its own constructor is full of names that clause 3
#      alone would demote, and demoting them is precisely the aliasing bug:
#      `Point(x=1, y=2)` writes two fields that no `obj.x` ever appears to.
#   5. The unit has no name-less attribute write this census cannot see —
#      `setattr(o, name, v)` with a computed name, a `__dict__` subscript with
#      a computed key, `globals()[…] = …`. Then NO name in the unit is demoted
#      (see the `dynamic` flag), because a write nobody can name is a write to
#      everything.
#   6. It is declared WITH a value. `LIMIT = 10` defines a value every instance
#      shares; `var limit: Int` declares storage and nothing else. The second
#      is a field even when no code in the unit ever writes it, because the
#      moment anything reads one of two such fields they would share a word —
#      and `struct Pair: var a: Int; var b: Int` is refused by name for exactly
#      that reason (test_formal_imports.py asserts it). A declaration with no
#      initializer is the one shape in which "nothing writes it" is a statement
#      about the PROGRAM rather than about the DECLARATION.
#
# And the rule has a SECOND input, which is not one of the class-level names
# above: a `comptime NAME = expr` binding, which the parser keeps out of
# `StructDef.fields` entirely and which was therefore classified by nothing until
# this. It is a class value by the language's own construction — one value,
# evaluated once at struct-definition time, identical for every instance — so it
# is a constant unless clauses 3 and 5 say this program stores into it, and when
# they do it is a FIELD with a slot, because then the value really is
# per-instance. Clause 2 does not apply to it, and the reason is the whole
# point: a `self.NAME` read of a `comptime` member is a read of the CLASS's
# value rather than of storage, so the receiver spelling is a read site the
# substitution materializes (or refuses by name) instead of a slot to count.
# Left to the receiver sweep below it was counted as a field and read as the zero
# an unwritten slot gives — measured, a one-word struct printing 0 where the
# source says 10, on both architectures. See `struct_comptime_aliases`.
#
# Two things this deliberately does NOT do. It does not resolve a bare read:
# `X` inside a method does not see the class body's scope in Python or Mojo, so
# a bare read is a global (or a local), never this rule's constant — there is
# nothing here to decide. And it does not demote on a name's NAME, however
# constant-looking (`_SIGNED = 1` and `self.n = 0` differ in spelling and in
# nothing else a typeless scan can see); it decides on where the name is
# WRITTEN, which is the one property that separates the two.
#
# What it is worth, measured: of 232 structs in the repository 11 get narrower,
# by exactly the names the rule identifies, and NONE gets wider. What it does
# NOT buy is a receiver that has real instance state: `GimpleGen` has 248 of
# those, so the sixteen files refused on it are still refused, and the honest
# summary of that half is in the sweep's own numbers rather than here.
#


# ── The one name this rule does NOT decide: a `comptime` binding ───────────
#
# `comptime NAME = …` in a class body is not one more class-level name for this
# rule to weigh. The PARSER has already decided it, in the shape of the tree:
# `fire_compiler.py`'s `_parse_struct` moves every `ComptimeVarStmt` of the body
# into `StructDef.comptime_aliases` and leaves it out of `StructDef.fields`
# entirely, so the name is not in any of the tables above even before this
# rule runs — it is in no table at all, which is the defect
# `struct_comptime_aliases` below exists to close.
#
# Two consequences follow, and they are why this is a carve-out rather than a
# clause:
#
#   * CLAUSE 2 does not apply to it. Clause 2 keeps a name that a method reaches
#     through the receiver (`self.NAME`) a FIELD, because for a class-level
#     assignment the receiver may BE the field — a one-field struct's receiver is
#     its field, `struct_default_word` put the value there, and demoting the name
#     would leave the read falling to a slot nothing writes. A `comptime` binding
#     has no such word: there is no slot for it, which is exactly why the parser
#     kept it out of `fields`, and a `self.NAME` read of one is the binding's
#     value (myinterpreter's `_eval_member_of` resolves `obj._mojo_class.
#     comptime_aliases[member]` for exactly that name, after the instance fields
#     and the methods and before raising). So the alias is decided by the
#     LANGUAGE here, not by evidence, and the evidence rule takes over only for
#     the direction the rule is lopsided towards: a unit that WRITES the name, or
#     one whose writes cannot be read at all, still gets it as a field.
#   * Its VALUE is not necessarily a literal. `comptime rank = Self.element_types
#     .length` and `comptime is_flat = Self.rank == Self.flat_rank` are both real
#     new-modular stdlib (`utils/coord.mojo:214,220`), and a computation is not
#     something a read can inline without a comptime evaluator this path has not
#     got. So "is a class-level constant" and "can a read of it be answered" stay
#     two separate questions: the first is answered here, the second by
#     `class_constant_word` at the read, which refuses by name.
#
# A name in BOTH places — `comptime X = 1` in a body that also declares
# `var X: Int` — is a FIELD. The declaration is the stronger evidence, it is what
# the positional-constructor rule fills slots from, and it is the direction every
# doubt in this section resolves.

# The name-less attribute writers, and what to do about each. `setattr` and
# `delattr` with a string LITERAL name are readable, and the name is added to
# the evidence; with a computed name they are not, so the whole unit is treated
# as dynamic. `globals`/`locals`/`vars`/`eval`/`exec` can manufacture a write
# out of nothing and are therefore dynamic outright.
_DYNAMIC_WRITERS = ("globals", "locals", "vars", "eval", "exec")
_STRING_NAMED_WRITERS = ("setattr", "delattr")
# `o.__dict__` / `o.__dict__[k]` / `o.__dict__.update(...)` — a dict of
# attributes under a name this scan can read, so it is decoded rather than
# distrusted; a computed key is not decodable and is dynamic.
_DICT_CHAIN_METHODS = ("update", "setdefault", "pop")


def _dict_chain_key(node):
    """What a `__dict__` read or write names: an attribute name, "" or None.

    An attribute name for `o.__dict__["n"]` and for `.update`/`.setdefault`/
    `.pop` called on a `__dict__` with a string literal; "" for a node that has
    nothing to do with `__dict__` at all (which is nearly every subscript in the
    repository — `d[k]`, `a[i]` — and must not be confused with one that does);
    None for a `__dict__` chain whose key is computed, which is the one thing
    here the caller cannot resolve, so it turns the whole unit dynamic."""
    if isinstance(node, F.SubscriptExpr):
        if not _rooted_at(node.obj, "__dict__"):
            return ""
        idx = node.index
        if isinstance(idx, F.StringLiteral) and isinstance(idx.value, str):
            return idx.value
        return None
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
            and node.func.member in _DICT_CHAIN_METHODS:
        if not _rooted_at(node.func.obj, "__dict__"):
            return ""
        for a in list(node.args) + [v for _k, v in (node.kwargs or [])]:
            if isinstance(a, F.StringLiteral) and isinstance(a.value, str):
                return a.value
        return None
    return ""


def _rooted_at(node, member: str) -> bool:
    """True when `node` is `….<member>` or a subscript/attribute chain on one."""
    while True:
        if isinstance(node, F.MemberExpr):
            if node.member == member:
                return True
            node = node.obj
            continue
        if isinstance(node, F.SubscriptExpr):
            node = node.obj
            continue
        return False


def unit_field_evidence(stmts) -> tuple:
    """`(names, dynamic)` — what one translation unit says about instance state.

    `names` is every name this unit could possibly write into a field, by any
    spelling that carries the name: a member-assignment target, a
    keyword-argument name, a string literal handed to `setattr`/`delattr`/
    `__dict__`, and — for a call to a struct declared in the same unit — each
    positional argument, which fills that struct's declared fields in
    declaration order.

    `dynamic` is True when the unit contains a write whose NAME this scan
    cannot read. It is a blunt instrument on purpose: one `setattr(o, k, v)`
    with a computed `k` means no name in the unit can be trusted as unwritten,
    and the cost of being wrong in that direction is a silent wrong answer
    rather than a refusal."""
    declared = {}
    for st in iter_struct_defs(stmts):
        names = struct_declared_names(st)
        if names:
            declared[getattr(st, "name", None)] = names
    names, dynamic = set(), False

    def walk(node):
        nonlocal dynamic
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not hasattr(node, "__dataclass_fields__"):
            return
        # a member in ASSIGNMENT position — the only write that makes a field
        # per-instance state. `targets` covers MultiAssignStmt and DelStmt,
        # which is where `a, b.x = …` and `del b.x` land.
        for tgt in [getattr(node, "target", None)] \
                + list(getattr(node, "targets", None) or []):
            if isinstance(tgt, F.MemberExpr):
                names.add(tgt.member)
        if isinstance(node, F.CallExpr):
            for k, _v in (node.kwargs or []):
                if isinstance(k, str):
                    names.add(k)
            callee = node.func
            if isinstance(callee, F.IdentExpr):
                if callee.name in _DYNAMIC_WRITERS:
                    dynamic = True
                elif callee.name in _STRING_NAMED_WRITERS:
                    if len(node.args) >= 2 and isinstance(node.args[1],
                                                          F.StringLiteral) \
                            and isinstance(node.args[1].value, str):
                        names.add(node.args[1].value)
                    else:
                        dynamic = True
                else:
                    for i, _a in enumerate(node.args or []):
                        if i < len(declared.get(callee.name, ())):
                            names.add(declared[callee.name][i])
        key = _dict_chain_key(node)
        if key is None:
            dynamic = True
        elif key:
            names.add(key)
        for fname in node.__dataclass_fields__:
            if fname in ("line", "col"):
                continue
            walk(getattr(node, fname, None))

    walk(stmts)
    return (frozenset(names), dynamic)


def struct_field_evidence(struct_def):
    """The `(names, dynamic)` evidence attached to this struct, or None.

    None means NO evidence — not "no evidence against". A struct nobody
    attached evidence to keeps every class-level name as a field, which is
    exactly the pre-rule behaviour; that is what a caller that cannot see the
    whole unit gets, and it is why attaching it is the pipeline's job rather
    than an optimisation."""
    return getattr(struct_def, "_field_evidence", None)


def attach_field_evidence(struct_defs, evidence) -> None:
    """Give every one of `struct_defs` this evidence, in place.

    On the struct rather than passed down, because the two backends ask the
    model about a struct they were handed, with no unit in hand: a width that
    depended on a caller-supplied argument could differ between the build pass
    and the codegen pass, which is the one divergence this shared model exists
    to make impossible (see this module's docstring).

    `struct_defs` is the unit's OWN declarations, which is also what the
    INHERITANCE resolution below needs: a base can only contribute fields if
    this unit declares it, so the table it resolves against is exactly the
    list this function is given. That is why the two are attached together and
    not by two callers in two places — a struct whose evidence was attached
    without its inherited fields, or the reverse, is a struct measured two
    different ways depending on which caller got there first."""
    for st in struct_defs or []:
        setattr(st, "_field_evidence", evidence)
    attach_inherited_fields(struct_defs)




# ── INHERITANCE: the fields a struct has because a BASE declares them ──────
#
# A class body's fields are not the class's fields. `class Sub(Base)` has
# Base's storage as well as its own, every reader of this file agrees, and for
# two rounds nothing here did: `struct_field_names` walked the OWN body, so a
# base's fields were in no layout, in no arity and in no slot index — and the
# three symptoms that follow are all silent. A construction's arity refused
# with "no fields at all" for a class that inherits them; a field read through
# the subclass was refused with a sentence claiming the program raises an
# AttributeError, which is false of a program that inherits the field; and a
# subclass that declared none of its own measured as a ONE-WORD struct, so it
# got the convention (`self` IS the field) that the base's methods — compiled
# from the base's own declaration — do not agree with.
#
# **THE ORDER IS CPython's dataclass order and it is load-bearing**: the base's
# fields first, its own after. Which value lands in which slot is decided by
# the order, so this is not "prepend the base's names" as a convenience but the
# one order the language has. A name the subclass REDECLARES keeps the base's
# position and the subclass's initializer, which is what CPython's generated
# `__init__` does with it (`dataclass_transform.inheritance_refusal` says so
# where the dataclass path refuses a base for the other reason it has).
#
# **A base this image does not declare contributes nothing, and the two
# messages that used to describe the result as the subclass's own fault now
# name it.** 1217 of the 1223 `class X(Y)` declarations in this repository and
# the stdlib name a base declared nowhere near them — a Mojo trait
# (`Copyable`, `Sized`), a Python builtin (`dict`, `int`, `str`), or a CPython
# exception — and none of those has positional instance fields for a
# constructor to fill, so contributing nothing is right. What is NOT right is
# reporting the consequence as if the class had no base at all, which is what
# `construction_arity_refusal` and `member_read_without_a_field` did.
CPYTHON_EXCEPTION_BASES = frozenset({
    # Every class CPython's `builtins` defines as an exception, and nothing
    # else. Generated from the interpreter this compiler runs on —
    # `[n for n, v in vars(builtins).items() if isinstance(v, type) and
    # issubclass(v, BaseException)]` — because the answer is a fact about
    # CPython rather than about this backend, and a hand-kept list of the ones
    # somebody remembered is a list that goes stale silently.
    #
    # They are here at all because of ONE field every one of them has:
    # `BaseException.__new__` fills `args` from the caller's arguments, so
    # `raise ValueError("boom")` carries its message with no declaration
    # anywhere in the subclass. Modelling that as a field is what gives the
    # message a SLOT: a class whose body is a docstring and nothing else has
    # nowhere to put one otherwise, and the construction was refused for
    # exactly that (`bugs/FORMAL_an_exception_constructed_with_its_message_has_
    # no_field_to_hold_it.md`, whose fix this is).
    "ArithmeticError", "AssertionError", "AttributeError",
    "BaseException", "BaseExceptionGroup", "BlockingIOError",
    "BrokenPipeError", "BufferError", "BytesWarning",
    "ChildProcessError", "ConnectionAbortedError", "ConnectionError",
    "ConnectionRefusedError", "ConnectionResetError",
    "DeprecationWarning", "EOFError", "EncodingWarning",
    "EnvironmentError", "Exception", "ExceptionGroup",
    "FileExistsError", "FileNotFoundError", "FloatingPointError",
    "FutureWarning", "GeneratorExit", "IOError", "ImportError",
    "ImportWarning", "IndentationError", "IndexError",
    "InterruptedError", "IsADirectoryError", "KeyError",
    "KeyboardInterrupt", "LookupError", "MemoryError",
    "ModuleNotFoundError", "NameError", "NotADirectoryError",
    "NotImplementedError", "OSError", "OverflowError",
    "PendingDeprecationWarning", "PermissionError",
    "ProcessLookupError", "PythonFinalizationError", "RecursionError",
    "ReferenceError", "ResourceWarning", "RuntimeError",
    "RuntimeWarning", "StopAsyncIteration", "StopIteration",
    "SyntaxError", "SyntaxWarning", "SystemError", "SystemExit",
    "TabError", "TimeoutError", "TypeError", "UnboundLocalError",
    "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeError",
    "UnicodeTranslateError", "UnicodeWarning", "UserWarning",
    "ValueError", "Warning", "ZeroDivisionError",
    "_IncompleteInputError",
})

# What a base from that table contributes. ONE entry, and it is a field rather
# than anything cleverer because `args` is where CPython puts the message: a
# `raise E(msg)` fills it, and `str(e)` reads it. A subclass that DECLARES
# `args` itself (`formal/x86_64_decode.py`'s `DecodeError`) keeps its own
# declaration and its own position, which is CPython's behaviour for a
# re-declared field and one name rather than two slots for one word.
BUILTIN_EXCEPTION_FIELDS = ("args",)


def builtin_base_fields(base: str) -> tuple:
    """The instance fields a base THIS IMAGE does not declare contributes.

    Empty for everything but CPython's exception hierarchy, and that is the
    whole of the rule rather than a first case: a Mojo trait (`Copyable`,
    `Sized`, `RegisterPassable`) is a compile-time protocol with no instance
    storage, and a builtin container (`dict`, `list`, `str`) is a word this path
    already represents whole. Neither has a positional field list for a
    constructor to fill, so there is nothing to merge and inventing something
    would change a layout on the strength of a name."""
    if base in CPYTHON_EXCEPTION_BASES:
        return BUILTIN_EXCEPTION_FIELDS
    return ()




# ── the EXCEPTION KIND TABLE: one small integer per class this image can name ──
#
# Shared infrastructure for the unwinder, landed on its own and fixing nothing
# by itself — which is the honest description and the reason it is worth having
# separately. `bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md` §4
# designs the convention: one callee-visible word per function meaning "an
# exception is in flight", holding the KIND of the current exception, and §5
# step 2 is this. The dispatch, the raise sites, the CFG and the Lean model are
# steps 3-6 and are not attempted; **nothing reads this table yet**, and a
# reader should not mistake it for a working unwinder.
#
# **TWO DISJOINT RANGES, and that is the whole requirement.** Both backends and
# both proof generators must agree about which integer means `ValueError`,
# because the word is written by one and read by another; and the agreement has
# to survive an image DECLARING a class of its own, because a dylib and the
# executable that links it are two `_prepare_functions` runs with different
# declared sets and the same CPython half. Measured on the first version of this
# function, which numbered one sorted set: adding `class MyErr` moved
# `ValueError` from 38 to 69, so a word written by the library would have meant
# nothing in the caller's image.
#
# So the ranges are separate: `CPYTHON_EXCEPTION_BASES` occupies 1..N by sorted
# name, and a class THIS IMAGE declares occupies N+1.. by sorted name. Adding a
# declaration cannot move a builtin, and adding a builtin cannot move a
# declaration's relative order. 0 is reserved for "no exception in flight", so a
# zeroed frame is a frame with nothing to dispatch and every real kind is
# distinguishable from it without a second flag.
_EXCEPTION_KINDS: dict = {}


def exception_kind_table(structs=None) -> dict:
    """`{exception class name: kind}` for every class THIS IMAGE can name.

    The names are `CPYTHON_EXCEPTION_BASES` plus the classes `structs` declares,
    in the two disjoint ranges the block comment above states. A name in both
    takes the CPython range — it IS the same class by name, and one name must
    not have two integers.

    **`structs` is the image's own class table and it is `None`-tolerant**,
    because the emitters and the proof generators hold the class table under
    different names and a caller with none must still get CPython's half — which
    is the half two images built from the same sources always agree on.

    **A class the image cannot name has no entry, and that is what the callers
    must treat as the interesting case rather than as absence.** §4's third
    bullet: an image whose `raise` or `except` names a class from outside
    `CPYTHON_EXCEPTION_BASES` and outside its own declarations is an UNMODELLED
    base, and §4's answer for it is a kind that is real but not matchable by
    name. This function deliberately does NOT invent that kind — it cannot, it
    does not know which class is meant — and `exception_kind_for` is where a
    caller asks the question that has an answer.
    """
    builtins = sorted(CPYTHON_EXCEPTION_BASES)
    table = {name: i + 1 for i, name in enumerate(builtins)}
    # The declared half, from the top of the reserved space and in name order,
    # skipping any name CPython already numbers. Written as one pass with the
    # membership test FIRST because the alternative — a `setdefault` that both
    # inserts and leaves the counter un-advanced for a shadowing name — is
    # exactly the off-by-one that shows up as two images disagreeing about one
    # class's integer, which is the failure this split exists to prevent.
    nxt = len(builtins) + 1
    for name in sorted(str(s) for s in (structs or {})):
        if name in table:
            continue
        table[name] = nxt
        nxt += 1
    return table


def publish_exception_kinds(table: dict) -> None:
    """Install `table` as this image's kind numbering.

    REPLACES, for `publish_module_symbols`'s reason and not
    `publish_non_ascii_strings`'s: this is one property of ONE image, and two
    images built in one process must not see each other's numbering. The
    clear is at the top of the image beside the other two.
    """
    global _EXCEPTION_KINDS
    _EXCEPTION_KINDS = dict(table or {})


def exception_kinds() -> dict:
    """The published `{class: kind}` table. Empty before a publish."""
    return dict(_EXCEPTION_KINDS)


def clear_exception_kinds() -> None:
    """Start a NEW IMAGE's kind numbering over.

    The third of the three per-image tables, and it exists for the same reason
    as the other two: without it the second program a harness builds inherits
    the first one's numbering, and an image whose declared classes differ gets
    the first one's integers. `formal/build.py::compile_formal` is the one
    caller that is not a test.
    """
    global _EXCEPTION_KINDS
    _EXCEPTION_KINDS = {}


def exception_kind_for(name: str, kinds: dict = None):
    """The kind `name` has in this image, or None when the image cannot name it.

    **None is the ANSWER for an unmodelled base, not a failure to look.** §4's
    third bullet is exactly this case — a `raise` of, or an `except` for, a class
    from outside CPython's hierarchy and outside this image's declarations — and
    §4 says it "gets kind 1 and is not matchable by name, which is honest rather
    than convenient". So a caller that has a class it cannot name asks here and
    is told so; what it does with that (refuse the arm, or give the exception a
    single unmatchable kind) is the design question §4 records as still open,
    and it is NOT decided here.

    `kinds` defaults to the published table, so a proof generator holding `info`
    and an emitter holding nothing answer the same question the same way.
    """
    table = exception_kinds() if kinds is None else kinds
    return table.get(str(name)) if name else None




# ── §4's SUPERCLASS question, ANSWERED: the table grows a base relation ──────
#
# `bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md` §4 asks for the one
# design decision in that document with no answer in the code, and §5 step 1
# says to decide it BEFORE the emitters are written: "either the kind table
# grows a `SUPERCLASS_OF` bit, or the word is a pointer and the base walk moves
# into the dispatch".
#
# **It grows the base relation, and here is why that is the answer rather than
# the other one.** The word stays one 64-bit word because it has to: it is
# written by a callee into its own frame and read by a call site that must also
# leave the value in the return register, so a second return value is not
# available (§4's own reason for a word rather than a pair). The alternative —
# make it a POINTER to an exception object — turns one convention into two
# frame questions at once, because `except A as e:` then needs an object to
# bind and an object is a FRAME on this path (`model.BUILTIN_EXCEPTION_FIELDS`
# is `("args",)`, so one per raise site is a `_blob_cap` question). That is §4's
# THIRD open question, and taking it on at the same time as the first is how a
# design ends up with two unsolved halves instead of one solved one.
#
# **The base relation is a BUILD-TIME fact on both halves, which is what makes
# the word enough.** CPython's hierarchy is a constant of the interpreter (the
# same provenance as `CPYTHON_EXCEPTION_BASES`, and generated the same way), and
# a class this image DECLARES has a base the source writes down. So
# `except A:` is discharged at run time by comparing the word against A's kind
# and against each of A's ancestors' kinds — a finite list computed here, once,
# per build — and the dispatch emits one compare per distinct kind rather than a
# base walk in the image.
#
# **And the one case the word genuinely cannot answer is now stated instead of
# papered over.** A class outside CPython's hierarchy and outside this image's
# declarations is an UNMODELLED base (§4's third bullet), and nothing can say
# whether it is an `Exception`, because nothing here knows its bases. A kind for
# it would be real but unmatchable, so `handler_arm_kinds` answers **None**
# rather than a set, and a caller must treat that as "cannot decide" — which is
# a refusal of the arm, not a silent non-match. Returning an empty set instead
# would make `except Exception:` quietly stop catching it, which is the exact
# wrong answer this project refuses everywhere else.

#: CPython's own exception hierarchy: `{class: its direct base(s)}`, restricted
#: to classes in `CPYTHON_EXCEPTION_BASES`. Generated from the interpreter this
#: compiler runs on —
#: `{n: tuple(b.__name__ for b in v.__bases__ if
#:           issubclass(b, BaseException))
#:   for n, v in vars(builtins).items()
#:   if isinstance(v, type) and issubclass(v, BaseException)}`
#: — for `CPYTHON_EXCEPTION_BASES`'s reason: the answer is a fact about CPython
#: and a hand-kept list is a list that goes stale silently.
#:
#: **A base outside the set is dropped, and that is not a gap.** `object` is the
#: only one CPython has, and `BaseException` is the hierarchy's root; `object`
#: is not an exception, so an `except` arm can never name it.
#: **A class with TWO bases keeps both** — `ExceptionGroup` derives from
#: `BaseExceptionGroup` and `Exception`, and CPython's `issubclass` says yes to
#: both, so a matcher that kept one would be wrong about half of them.
CPYTHON_EXCEPTION_BASE = {
    "ArithmeticError": ('Exception',),
    "AssertionError": ('Exception',),
    "AttributeError": ('Exception',),
    "BaseException": (),
    "BaseExceptionGroup": ('BaseException',),
    "BlockingIOError": ('OSError',),
    "BrokenPipeError": ('ConnectionError',),
    "BufferError": ('Exception',),
    "BytesWarning": ('Warning',),
    "ChildProcessError": ('OSError',),
    "ConnectionAbortedError": ('ConnectionError',),
    "ConnectionError": ('OSError',),
    "ConnectionRefusedError": ('ConnectionError',),
    "ConnectionResetError": ('ConnectionError',),
    "DeprecationWarning": ('Warning',),
    "EOFError": ('Exception',),
    "EncodingWarning": ('Warning',),
    "EnvironmentError": ('Exception',),
    "Exception": ('BaseException',),
    "ExceptionGroup": ('BaseExceptionGroup', 'Exception'),
    "FileExistsError": ('OSError',),
    "FileNotFoundError": ('OSError',),
    "FloatingPointError": ('ArithmeticError',),
    "FutureWarning": ('Warning',),
    "GeneratorExit": ('BaseException',),
    "IOError": ('Exception',),
    "ImportError": ('Exception',),
    "ImportWarning": ('Warning',),
    "IndentationError": ('SyntaxError',),
    "IndexError": ('LookupError',),
    "InterruptedError": ('OSError',),
    "IsADirectoryError": ('OSError',),
    "KeyError": ('LookupError',),
    "KeyboardInterrupt": ('BaseException',),
    "LookupError": ('Exception',),
    "MemoryError": ('Exception',),
    "ModuleNotFoundError": ('ImportError',),
    "NameError": ('Exception',),
    "NotADirectoryError": ('OSError',),
    "NotImplementedError": ('RuntimeError',),
    "OSError": ('Exception',),
    "OverflowError": ('ArithmeticError',),
    "PendingDeprecationWarning": ('Warning',),
    "PermissionError": ('OSError',),
    "ProcessLookupError": ('OSError',),
    "PythonFinalizationError": ('RuntimeError',),
    "RecursionError": ('RuntimeError',),
    "ReferenceError": ('Exception',),
    "ResourceWarning": ('Warning',),
    "RuntimeError": ('Exception',),
    "RuntimeWarning": ('Warning',),
    "StopAsyncIteration": ('Exception',),
    "StopIteration": ('Exception',),
    "SyntaxError": ('Exception',),
    "SyntaxWarning": ('Warning',),
    "SystemError": ('Exception',),
    "SystemExit": ('BaseException',),
    "TabError": ('IndentationError',),
    "TimeoutError": ('OSError',),
    "TypeError": ('Exception',),
    "UnboundLocalError": ('NameError',),
    "UnicodeDecodeError": ('UnicodeError',),
    "UnicodeEncodeError": ('UnicodeError',),
    "UnicodeError": ('ValueError',),
    "UnicodeTranslateError": ('UnicodeError',),
    "UnicodeWarning": ('Warning',),
    "UserWarning": ('Warning',),
    "ValueError": ('Exception',),
    "Warning": ('Exception',),
    "ZeroDivisionError": ('ArithmeticError',),
    "_IncompleteInputError": ('SyntaxError',),
}


#: CPython's 71 exception NAMES are 69 class OBJECTS, and the two that are not
#: are aliases: `EnvironmentError` and `IOError` are `OSError`. Generated from
#: the interpreter by identity (`v is w`), because the consequence is not
#: cosmetic — `issubclass(BlockingIOError, IOError)` is True in CPython, and a
#: matcher that walks a NAME hierarchy answers False for all 18 of `OSError`'s
#: subclasses under an `except IOError:` arm. Measured over every ordered pair
#: of the 71 names: 5041 comparisons, 36 disagreements, every one of them under
#: an alias. This table is what makes that zero, and it is the reason
#: `exception_base_chain` canonicalises a name before walking it.
CPYTHON_EXCEPTION_ALIAS = {"EnvironmentError": "OSError", "IOError": "OSError"}


def _declared_exception_base(name, structs) -> tuple:
    """The base names this IMAGE's own declaration of `name` gives, or None.

    A declared class's bases are written in the source, so they are the one part
    of the hierarchy that is not a constant — and they WIN over
    `CPYTHON_EXCEPTION_BASE` for the same reason `raise_class_name` lets
    `structs` win: `class ValueError(Exception)` is this image's class, and
    reading its base from CPython's table would be reading a different
    declaration.

    `None` for a class this image does not declare, which is the ordinary case
    and not a failure: the CPython table answers it.
    """
    decl = (structs or {}).get(str(name)) if hasattr(structs or {}, "get") else None
    if decl is None:
        return None
    return tuple(str(b) for b in (getattr(decl, "bases", None) or []))


def _canonical_exception_name(name, structs) -> str:
    """`name` with a CPython ALIAS resolved, unless this image declares it.

    One reader of that rule, because `exception_base_chain` and both matchers
    have to agree about it and a second spelling is how they would not.
    """
    text = str(name)
    if (structs or {}) and hasattr(structs, "get") and text in structs:
        return text
    return CPYTHON_EXCEPTION_ALIAS.get(text, text)


def exception_base_chain(name, structs=None) -> tuple:
    """`(ancestors, unresolved)` — `name`'s base chain, and where it stops being
    knowable.

    `ancestors` starts at `name` itself and walks UP, breadth-first over
    multiple bases, so an arm for a class matches every class below it.
    `unresolved` names the bases the walk could not follow — a class outside
    CPython's hierarchy and outside this image's declarations — and is the
    reason a caller cannot conclude "this arm matches exactly these kinds".

    **Cycles terminate** rather than hanging, because a source-level cycle is a
    program this path already refuses elsewhere and a hang in a matcher is worse
    than an answer about a prefix of the chain. A name repeated in the walk is
    dropped, so the result is finite whatever the declaration says.

    **A CPython ALIAS is canonicalised before the walk** (`CPYTHON_EXCEPTION_ALIAS`),
    so `except IOError:` and `except OSError:` are the same arm — which is what
    CPython says, since they are the same class object. A DECLARED class is never
    canonicalised: `class IOError(...)` in this image is a different class from
    the builtin by that name, and `raise_class_name` already gives a declaration
    precedence over the builtin for the same reason.
    """
    root = _canonical_exception_name(name, structs)
    seen, order, todo = set(), [], [root]
    unresolved = []
    while todo:
        cur = todo.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        order.append(cur)
        declared = _declared_exception_base(cur, structs)
        if declared is not None:
            bases = declared
        elif cur in CPYTHON_EXCEPTION_BASE:
            bases = CPYTHON_EXCEPTION_BASE[cur]
        else:
            unresolved.append(cur)
            continue
        todo.extend(b for b in bases if b not in seen)
    return tuple(order), tuple(unresolved)


def handler_arm_kinds(name, kinds=None, structs=None):
    """The KINDS an `except <name>:` arm's dispatch has to compare against, or
    **None** when that list cannot be fixed at build time.

    **The direction is DESCENDANTS, not ancestors, and getting it backwards is
    the mistake this docstring exists to prevent.** The word holds the kind of
    the class actually raised, so `except ArithmeticError:` catching a
    `ZeroDivisionError` means the word says `ZeroDivisionError` and the ARM has
    to know that `ZeroDivisionError` is below it — an ancestor walk would answer
    the opposite question and report a non-match.

    So the set is `{kind(C) for every class C this image can name with
    `name ∈ ancestors(C)`}`, and it is exactly the compare list the dispatch
    emits — one compare per distinct kind, which is why §4's "the word is not a
    pointer" answer does not need a base walk in the image.

    **None is the answer for the two cases where the list is not a fact about
    the ARM ALONE, and both must be refusals upstream rather than a guess:**

      * the chain reaches a base this image cannot follow (an unmodelled base),
        so `name` may have subclasses nothing here knows;
      * `name` is a DECLARED class with a DECLARED subclass. A dylib and the
        executable that links it are two images whose declared sets differ, and
        the two-numbering argument in `exception_kind_table`'s block comment is
        why a declared class's kind is not the same integer in both. A compare
        list built from one image's declared subclasses is therefore a list that
        means something else in the other image — the exact failure the disjoint
        ranges exist to prevent, one level up.

      A CPython arm is safe from the second by construction: its whole
      descendant set lives in `CPYTHON_EXCEPTION_BASE`, which is a constant of
      the interpreter and identical in every image.
    """
    chain, unresolved = exception_base_chain(name, structs)
    table = exception_kinds() if kinds is None else kinds
    root = _canonical_exception_name(name, structs)
    if unresolved or root not in table:
        return None
    declared = set()
    for cls in (structs or {}):
        cchain, c_unresolved = exception_base_chain(cls, structs)
        if c_unresolved:
            return None
        if root in cchain and cchain[0] != root:
            declared.add(cls)
    if declared:
        return None
    out = set()
    for cls in table:
        cchain, c_unresolved = exception_base_chain(cls, structs)
        if c_unresolved:
            return None
        if root in cchain:
            out.add(table[cls])
    # An EMPTY set is the answer to nothing: every class is its own subclass, so
    # a name that matched none of them did not resolve. Returning `set()` here
    # would make the dispatch compare against nothing and silently never take an
    # arm, which is the worst of the three answers.
    return frozenset(out) if out else None


def handler_arm_matches(arm_name, flying_name, kinds=None, structs=None):
    """Would CPython's `except <arm_name>:` catch a `<flying_name>` exception?

    `True`, `False`, or **None** for "cannot be decided" — the three answers are
    kept apart because a dispatch has to tell a non-match (fall through to the
    next arm) from an undecidable one (refuse the image), and a boolean would
    collapse them into a silently wrong catch.

    **The two halves need different evidence and that is the whole reason both
    of them exist.** The test is membership of the ARM's name in the RAISED
    class's chain, so `True` and `False` need only that chain — the arm's own
    ancestry never enters, which is why an arm whose own base is unmodelled is
    still decidable here. What is NOT decidable is a raised class whose chain
    stops at an unmodelled base: `except Exception:` does not catch a
    `class Mine(ExternalBase)` whose own bases nothing here knows, and answering
    `False` there would drop an exception CPython catches.

    This is the question the SOURCE answers and the one `handler_arm_kinds` does
    not: it says what CPython would do, which is what the model's `except` needs,
    while the other says what the image can compare, which is what the dispatch
    needs. Pinning both is what keeps §4's design question from being answered
    twice and differently.
    """
    if arm_name is None:
        return None
    fly_chain, fly_unresolved = exception_base_chain(flying_name, structs)
    if fly_unresolved:
        return None
    return _canonical_exception_name(arm_name, structs) in fly_chain




# ── what a `raise` of an exception CLASS lowers to ─────────────────────────
#
# `raise E(...)` / `raise E` where `E` names a CPython builtin exception class
# has no image at all: there is no declaration of `ValueError` here, so the
# emitter's call path used to reach the extern path and emit `BL ValueError`,
# which the link audit then refused ("the image would bind 1 symbol(s) that
# nothing provides"), and a BARE `raise E` reached the name reader and was
# refused as "'E' has no home". Both refusals name a SYMBOL and neither names
# the construct, and both are wrong about what is missing: the class is not
# missing, the backend has no unwinder, so there is nothing for an instance to
# be handed to.
#
# What CPython's contract actually is for an UNCAUGHT one is short and is the
# whole of this table: the ARGUMENT EXPRESSIONS run for their side effects (so
# `raise ValueError(g())` calls `g`), the enclosing `finally` clauses run, and
# the process leaves with status 1 and everything it printed already flushed.
# Nothing observes the instance — there is no handler to bind it to and no
# `except` arm in the image — so building one and discarding it would be an
# allocation whose only purpose is to be dropped.
#
# So the rule is ONE function, in this file, that both emitters read: it
# classifies the raised expression and says what to run and what status to
# leave. `SystemExit` is the one member of the hierarchy whose status is not 1,
# and `model.raise_exit_status` is where that is decided rather than in either
# backend.

#: `raise E` where `E` is a name: `(mode, arg_exprs, exc_name)`.
#: `mode` is `"args"` — run each of `arg_exprs` for its effects, then leave.
RAISE_CLASS_MODE = "args"

#: `raise <expr>` that is not a bare class reference: emit `expr` as written,
#: then leave. The existing `_emit_diverge` path.
RAISE_EXPR_MODE = "expr"


def raise_class_name(value, structs: dict | None = None) -> str | None:
    """The exception class `raise <value>` names, or None when it names none.

    The two spellings CPython accepts for a class rather than an instance, and
    the answer is a NAME so both backends can agree on it:

      * `raise ValueError('boom')` — a `CallExpr` on a bare `IdentExpr`;
      * `raise ValueError` — the bare `IdentExpr` itself.

    `structs` is this image's own class table and it WINS over
    `CPYTHON_EXCEPTION_BASES`, because a name both declare means the
    declaration: `class ValueError: ...` is a struct to construct, not a
    builtin to leave behind, and reading it as the latter would silently
    discard fields the program set. That is the same precedence
    `builtin_base_fields` reads the other way round (a base the image declares
    contributes nothing, because the declaration already has the fields), so
    the two together are one rule rather than two.

    `None` for everything else, and that is a refusal rather than a guess: an
    `except` arm the image cannot see has already been refused by name
    (`refuse_dropped_handler_arm`), so the only `raise`s left are ones whose
    value the program can observe — an instance it built, a call's result, a
    subscript — and those keep the existing `RAISE_EXPR_MODE` path, which emits
    the expression."""
    if isinstance(value, F.CallExpr):
        func = getattr(value, "func", None)
        if not isinstance(func, F.IdentExpr):
            return None
        name = func.name
        arg_exprs = list(getattr(value, "args", None) or [])
        arg_exprs += [v for _k, v in (getattr(value, "kwargs", None) or [])]
    elif isinstance(value, F.IdentExpr):
        name = value.name
        arg_exprs = []
    else:
        return None
    if structs and name in structs:
        # Declared here: a real class with a real layout, so `raise` of it is a
        # CONSTRUCTION plus a leave. The construction is not this table's
        # business — the emitter's own constructor path already handles a
        # declared class, and `raise MyErr()` builds today.
        return None
    if name not in CPYTHON_EXCEPTION_BASES:
        return None
    return name


def raise_arg_exprs(value) -> list:
    """The argument EXPRESSIONS of `raise E(...)`, in source order.

    Split out from `raise_class_name` because the two callers need different
    halves of the same walk: the classification needs the NAME and this needs
    the expressions to evaluate. Positional arguments first, then the keyword
    values, which is the order CPython evaluates them in (the call's own
    argument-passing order), so a `raise E(f(), g())` runs `f` before `g`."""
    args = list(getattr(value, "args", None) or [])
    args += [v for _k, v in (getattr(value, "kwargs", None) or [])]
    return args


def integer_literal_value(e) -> int | None:
    """The `int` a SIGNED integer LITERAL node holds, or None.

    One reader for the question "is this whole expression a constant the build
    can see, and what is it", asked by three callers that each used to spell it:

      * `formal/arm64_codegen.py::_static_int` and x86-64's copy of it, which
        decide a shift amount and a `**` exponent;
      * `raise_exit_status` below, which reads a `SystemExit` status;
      * `_cfg_int_value`'s negated-literal arm.

    **A negated literal is a literal.** `-1` parses as `UnaryOp('-', IntLiteral
    1)` and not as an `IntLiteral`, so a reader that stops at `IntLiteral` calls
    it computed — which is how `raise SystemExit(-1)` came to leave status 1
    where CPython leaves 255. A unary minus applied to a literal is the one
    negation a build can fold, because the value is in the text.

    `None` for everything else, and that is a refusal and never a zero: `n - 1`
    is not a literal even when `n` is a constant the caller knows, because the
    caller knows it about a DIFFERENT program (a concrete run) and this reader
    is asked about the one being emitted.

    `bool` is read as the integer it is, deliberately. `True` reaches
    arithmetic as an `IntLiteral` in this parser, and for every question this
    reader is asked — a shift amount, a `**` exponent, a `SystemExit` status —
    CPython's answer is the integer, so `raise SystemExit(True)` is 1 here and 1
    in CPython and the distinction has nothing to decide. A caller that needs
    "a bool is not an int here" asks `isinstance(e, F.IntLiteral) and
    isinstance(e.value, bool)` itself, because that is a fact about ITS
    question."""
    if isinstance(e, F.IntLiteral):
        return int(e.value)
    if isinstance(e, F.UnaryOp) and e.op == "-":
        inner = integer_literal_value(getattr(e, "operand", None))
        return None if inner is None else -inner
    return None


#: How many bits of a `SystemExit` status survive into the process's exit
#: status. CPython's is `exit()`'s, which keeps the low BYTE, and both backends
#: read the same number from here so a computed status cannot be masked on one
#: machine and not the other — the asymmetry is invisible in the answer and is
#: exactly what `test_formal_exceptions.py`'s negative and out-of-range rows are
#: for.
EXIT_STATUS_BITS = 8


def raise_exit_status(exc_name: str, value=None,
                      argument_is_int: bool = False) -> int | None:
    """The status an uncaught `raise` of `exc_name` leaves behind, or None.

    1 for the whole hierarchy, and that is CPython's rule rather than this
    backend's convenience: an uncaught exception makes the interpreter report
    the traceback on stderr and exit 1.

    **`SystemExit` is the one exception to the exception**, and it is the
    reason this is a function rather than a constant. `SystemExit` is not a
    failure — it is how a program says "stop with this status", so CPython
    never prints a traceback for it and the status is its ARGUMENT:

        raise SystemExit        -> 0
        raise SystemExit(0)     -> 0
        raise SystemExit(3)     -> 3
        raise SystemExit(-1)    -> 255   (the C library masks to a byte)
        raise SystemExit("msg") -> 1, and `msg` on stderr
        raise SystemExit(f())   -> f()   (computed; see below)

    Measured on the interpreter this compiler runs on, all five. The two
    cases that are not a plain small non-negative integer are the reason the
    rule is stated and not guessed: a non-integer argument is the "print it and
    fail" form, and a negative or out-of-range one is truncated by
    `exit(3)`'s `status & ((1 << EXIT_STATUS_BITS) - 1)`, which is a fact about
    the C library rather than about this backend — so it is reproduced rather than refused, because
    a program's own exit status is the one thing a caller can observe.

    Only an integer LITERAL is read, a NEGATED one included: `raise
    SystemExit(-1)` is 255 and not "computed", because `-1` is in the text (see
    `integer_literal_value`).

    **`None` means COMPUTED, and it is the whole of what the deleted document
    `FORMAL_a_computed_systemexit_status_is_not_the_programs_own.md` asked for**
    (fixed by this function's own change; the document was removed with its fix,
    so the ask is recorded here rather than cited). A non-integer argument is
    NOT computed: CPython's answer there is 1
    whatever the object is, so a string literal stays 1 and a computed value
    that this path cannot classify as a non-integer ALSO stays 1 — refusing to
    be clever about a value whose type it cannot see is the direction every
    other rule in this file takes. `None` is returned only where the argument
    is an INTEGER the build cannot fold: a call, a name, an arithmetic
    expression over either. Both emitters branch on the `None` and put the
    argument's own value in the exit-status register, so `sys.exit(n)` — the
    ordinary spelling, and the one every real script uses — stops being a
    status of 1 and becomes the program's own.

    **`argument_is_int` is the emitter's own answer to "is it an integer"**
    (`raise_status_argument_is_an_integer`), passed IN rather than recomputed
    here because both emitters already hold the function being emitted and this
    function is also asked from `model.py` code that does not. It defaults to
    False, which is the answer that leaves today's status 1 in place — so a
    caller that forgets it gets the old behaviour and not a crash.

    **Why the API change and not a second reader.** This used to return 1 for
    the computed case, and a caller could only tell "1" from "1" by asking
    `integer_literal_value` again — which is how two backends would have come
    to disagree about what `None` means. The `None` is decided here, once, and
    both emitters ask this.
    """
    if exc_name != "SystemExit":
        return 1
    args = raise_arg_exprs(value) if value is not None else []
    if not args:
        return 0
    status = integer_literal_value(args[0])
    if status is not None:
        # A literal is masked HERE rather than at the point of delivery, because
        # there is nothing else to mask: the value is in the text and both
        # backends put it in the exit register whole. A COMPUTED value is
        # masked at the point of delivery instead, because that is where the
        # value exists — and the two differ on the negative case, which is why
        # the negative row is an ORACLE row in `test_formal_exceptions.py`
        # rather than a claim about this function.
        return status & ((1 << EXIT_STATUS_BITS) - 1)
    if argument_is_int:
        return None
    # A non-integer argument is CPython's "print the object and exit 1" form.
    # The exit status is 1 either way, so this needs no further reading.
    return 1


def raise_status_argument_is_an_integer(e, vk=None) -> bool:
    """True when `raise SystemExit(e)`'s argument is an INTEGER this build can
    compute but not fold.

    **The gate on `raise_exit_status`'s `None`, and it is deliberately narrow.**
    The question is "can this path put `e`'s own value in the exit register",
    and the honest answer is only for a value the KIND model calls an integer:
    a literal (which is folded instead and never reaches here), an arithmetic or
    comparison form whose operands are integers, a call whose result kind is an
    integer, and — the case the doc's reproducer is — a NAME whose kind says
    integer.

    Everything else answers False and so keeps status 1, which is CPython's
    answer for a non-integer argument and the safe direction here: putting a
    `char *` in an exit-status register would leave a number nothing in the
    source wrote. **Measured on that case rather than argued**: a
    `def code() -> str: return "boom"` with `raise SystemExit(code())` left 220
    on arm64 and 200 on x86-64 where CPython leaves 1, when this gate was
    reached through a bare `ValueKinds` with no `func_kind` hook — so the hook
    is not optional and building a fresh `ValueKinds` here is not an option.

    **`vk` is the emitter's OWN `ValueKinds`** (`self._vkinds`, built by
    `_scan_value_kinds` with this backend's `func_kind`/`int_names` hooks), not
    one built here, and that is the whole of what keeps the string case right:
    a callee's result kind is this backend's question and it is already
    answered. A `None` answers False, which is the status 1 that was there
    before — so a caller with nothing to ask loses nothing.
    """
    if e is None or vk is None:
        return False
    if isinstance(e, F.UnaryOp):
        if e.op in ("not", "-", "+", "~"):
            return True
        return False
    if isinstance(e, F.BinaryOp):
        # A comparison and a boolean connective are 0/1 wherever they appear,
        # and every arithmetic operator on two integers is an integer. What is
        # NOT here is `/` on the float kinds, which this path lowers as an
        # integer division anyway, so both spellings agree here.
        return True
    if isinstance(e, F.TernaryExpr):
        return True
    kind = vk.kind_of(e)
    return kind is not None and kind not in (STR_KIND, FLOAT_KIND) and (
        kind == INT_KIND or kind.endswith(":int"))


def raise_declared_class_name(value, structs: dict | None = None) -> str | None:
    """A class this image DECLARES that `raise <value>` names, or None.

    **The bare spelling only.** `raise MyErr` in CPython instantiates `MyErr`
    and raises the instance — CPython's own rule, and the same one that makes
    `raise MyErr` and `raise MyErr()` the same program. So this path has to run
    the class's CONSTRUCTOR, which means going through the emitter's ordinary
    construction arm rather than skipping it the way a builtin exception class
    is skipped, and it means a class whose `__init__` has a body is refused by
    the refusal that already names `__init__` — measured: `class MyErr` with a
    `print` in `__init__` then `raise MyErr()` is refused on both backends, and
    `raise MyErr` must not become a way around it, because CPython prints.

    The called spelling (`raise MyErr('m')`) is deliberately NOT answered here.
    It already lowers — `_emit_struct_constructor` handles it — so re-deriving
    it here would be a second implementation of a decision the emitter already
    makes. The case that was filed against it (a subclass of a builtin base
    that built and then died at run time) is closed by `357e3b5c`, which
    refuses a `try` that has an `except` arm at all: the symptom needed a
    handler to be reached, and a program with one no longer builds.

    `None` for a builtin exception class: `raise_class_name` owns that half,
    and the two halves are asked in that order because a name both tables
    contain means the DECLARATION (see `raise_class_name`)."""
    if not isinstance(value, F.IdentExpr):
        return None
    if structs and value.name in structs:
        return value.name
    return None


def raise_zero_arg_construction(name: str, line: int = 0) -> F.CallExpr:
    """`F.CallExpr(func=F.IdentExpr(name), args=[])` — what `raise C` means.

    One constructor rather than each emitter spelling it, for the reason the
    rest of this group has one reader: a synthesised node that two backends
    build separately is two places for them to differ about a field, and the
    field that matters here is `args` being empty rather than absent.

    The node is a fresh object on every call, which is what makes it safe to
    hand to an emitter that may store it — `id()` is how the name walk keys
    the nodes it must not re-read, and a shared instance would make two
    different `raise C` statements in one function look like one node."""
    return F.CallExpr(func=F.IdentExpr(name=name, line=line, col=0),
                      args=[], kwargs=[], line=line, col=0)


def raised_exception_class_nodes(body, structs: dict | None = None) -> set:
    """`id()`s of the `IdentExpr` nodes that NAME an exception class in a `raise`.

    For `check_module_symbols`' name walk, which asks about every `IdentExpr` in
    a function body and refuses one nothing places. `raise ValueError` — the
    bare spelling, and the one `raise_class_name` answers — is such a read, and
    it is refused as "'ValueError' has no home: … the register allocator
    collected no home for it", which is a true statement about a node that is
    never read as a value: the emitter consumes the whole `RaiseStmt` and the
    name only has to be RECOGNISED.

    So the walk skips exactly these, and the exemption is keyed on
    `raise_class_name` rather than on a spelling — the same reader the emitters
    ask, so a name this accepts and the name walk skips cannot come to disagree,
    which is the failure mode a second spelling test would introduce.

    `raise ValueError('m')`'s `IdentExpr` is the CALLEE of a call, and is not
    in this set: it is in `callees`, which the walk already exempts, and
    leaving it there keeps this about the one shape that had no exemption."""
    out = set()
    for stmt in iter_nodes(body):
        if not isinstance(stmt, F.RaiseStmt):
            continue
        value = getattr(stmt, "value", None)
        if not isinstance(value, F.IdentExpr):
            continue
        if raise_class_name(value, structs) is not None \
                or raise_declared_class_name(value, structs) is not None:
            out.add(id(value))
    return out


def raise_float_divides_by_zero_is_an_exception() -> bool:
    """CPython raises `ZeroDivisionError` for `x / 0.0` on doubles, and so must
    this path.

    Not the same rule as the INTEGER divide's, and the difference is the whole
    reason this exists as a function rather than being read off the integer
    guard. IEEE-754 divides by zero without trapping — `1.0/0.0` is `+inf` and
    `0.0/0.0` is NaN — so an emitted `FDIV` answers a NUMBER for a program
    CPython refuses, and the program then continues past the line that should
    have stopped it: measured on both backends, `x = 1.0/0.0` printed `b` and
    exited 0 where CPython prints `a` and exits 1.

    So the FLOAT divide needs the zero guard the integer one already has
    (`_emit_div_shift_pow`'s `div0_label`), and both backends ask THIS function
    so that the two cannot come to disagree about whether the language raises
    here."""
    return True


def _merged_field_names(struct_def, by_name: dict, memo: dict,
                        active: set) -> tuple:
    """`(names, unresolved bases, inherited defaults)` — the recursion.

    `memo` is keyed by `id`, because two StructDefs can share a name across
    modules and the table this resolves against is the unit's, so a name is
    not an identity. `active` is the cycle guard: `class A(B)` / `class B(A)`
    parses, and a fixpoint over a cycle has to answer something rather than
    recurse forever — it answers no fields, which is the conservative
    direction, since a cycle contributes storage nobody can order.

    The defaults are the base's class-level initializer nodes, because a
    subclass that adds no field of its own still gets the base's defaults:
    `struct_field_default` reads this after the class body and finds nothing
    there for an inherited name. Substituting 0 instead would be a wrong
    answer rather than a refusal — `Base.x = 5` / `class Sub(Base): pass` /
    `Sub().x` is 5 in CPython — so the node travels with the name."""
    key = id(struct_def)
    if key in memo:
        return memo[key]
    if key in active:
        return ((), (), {})
    active.add(key)
    inherited, unresolved, defaults = [], [], {}
    for base in (getattr(struct_def, "bases", None) or []):
        if not isinstance(base, str):
            continue
        declared = by_name.get(base)
        if declared is None:
            fields = builtin_base_fields(base)
            inherited.extend(fields)
            if not fields:
                unresolved.append(base)
            continue
        base_inherited, base_unresolved, base_defaults = _merged_field_names(
            declared, by_name, memo, active)
        unresolved.extend(base_unresolved)
        # The base's WHOLE merged list, not its own body: a grand-parent's
        # fields are this struct's fields too, and taking the base's merged
        # list is what makes the order base-of-base first without this
        # function knowing how deep the chain goes.
        inherited.extend(base_inherited)
        inherited.extend(_own_field_names(declared))
        for name, node in base_defaults.items():
            defaults.setdefault(name, node)
        for node in struct_fields(declared):
            fname = struct_field_name(node)
            if isinstance(fname, str):
                defaults.setdefault(fname, getattr(node, "value", None))
    active.discard(key)
    merged, seen = [], set()
    for name in inherited:
        if name not in seen:
            seen.add(name)
            merged.append(name)
    for name in _own_field_names(struct_def):
        if name not in seen:
            seen.add(name)
            merged.append(name)
    memo[key] = (tuple(merged), tuple(unresolved), defaults)
    return memo[key]


def attach_inherited_fields(struct_defs) -> None:
    """Resolve every struct in `struct_defs`'s BASES, in place.

    Attached rather than passed down for the reason `attach_field_evidence`
    gives: the two backends ask the model about a struct they were handed. What
    is attached is `(merged field names, bases this unit does not declare, the
    bases' default nodes)`, and each is consumed by name —
    `struct_field_names` by the first, `struct_unresolved_bases` by the two
    refusals that have to stop describing an undeclared base as a subclass with
    no fields, and `struct_field_default` by the third."""
    by_name = {}
    for st in struct_defs or []:
        name = getattr(st, "name", None)
        if isinstance(name, str) and name not in by_name:
            by_name[name] = st
    memo = {}
    for st in struct_defs or []:
        merged, unresolved, defaults = _merged_field_names(
            st, by_name, memo, set())
        setattr(st, "_merged_field_names", merged)
        setattr(st, "_unresolved_bases", unresolved)
        setattr(st, "_inherited_field_defaults", defaults)


def struct_merged_field_names(struct_def):
    """This struct's field names WITH its bases', or None if never resolved.

    None is "no answer", not "no fields": a struct nothing called
    `attach_inherited_fields` for keeps the pre-merge reading of its own body,
    which is what every caller did before the merge existed and what a module
    parsed outside `parse_module` still gets."""
    return getattr(struct_def, "_merged_field_names", None)


def struct_unresolved_bases(struct_def) -> tuple:
    """The bases this struct names that no declaration in its unit answers.

    A trait, a builtin container, or a class from a module this image cannot
    read — none of which has instance fields to merge, and each of which is a
    fact a refusal about the struct's fields must not hide."""
    return getattr(struct_def, "_unresolved_bases", None) or ()


def struct_declared_bases(struct_defs, struct_def) -> tuple:
    """The bases of `struct_def` that `struct_defs` DECLARES, in order.

    The second half of the inheritance story and the one the layout refusal
    needs: a base's METHODS are compiled against the BASE's layout, so a
    subclass whose own layout is not the base's cannot have them, and that is a
    fact about two declarations rather than about one. A base outside
    `struct_defs` contributes no fields and no methods this image can see, so
    it is not in this list — see `builtin_base_fields` for why that is right."""
    out = []
    for base in (getattr(struct_def, "bases", None) or []):
        for other in struct_defs or []:
            if getattr(other, "name", None) == base:
                out.append(other)
                break
    return tuple(out)


def struct_inherited_layout_conflicts(struct_defs, struct_def) -> list:
    """`[base]` for every base whose METHODS this struct cannot have.

    **The merge makes the layout right and the CALL still wrong, and this is
    the question about that.** `attach_inherited_fields` puts a base's fields
    in a subclass's layout, so `sub.x` reads the right slot. But a method is
    compiled against the layout of the class that DECLARED it — `self` is the
    field for a one-field struct and the address of a frame for a wider one —
    and it is dispatched by NAME, because a call site carries no receiver type
    to check. So `Base.get()` called on a `Sub` whose own fields pushed it over
    the one-word line hands the callee a FRAME ADDRESS where it expects the
    field: the callee reads the address as the value, and the program builds,
    runs, and prints a number nobody wrote. That is the quiet third symptom,
    and it is the one the merge alone would have introduced.

    A conflict is exactly one shape, and it is the shape where the two
    conventions differ. Two framed structs agree — the subclass's slots are the
    base's slots followed by its own, so every index the base's methods compute
    is the same word in both — and two one-word structs agree for the same
    reason. What cannot work is a base of one word receiving a frame address,
    which is `struct_is_framed` disagreeing.

    **A base that declares no METHOD is not a conflict**, and narrowing it that
    way is what keeps this a diagnosis instead of a veto. The hazard is a
    compiled function being handed the wrong representation, so a base with
    nothing compiled from it cannot produce one: `struct Base: var a: Int` +
    `struct Child(Base): var b: Int` measures as one word against a frame and
    answers correctly, because `Child.rank` and `Base.rank` are class constants
    and no method of `Base` is ever called (`test_formal_run.py`'s
    `comptime_attribute_through_the_class_name_is_the_base_value`, which this
    refusal used to take over — and taking over a case that computes the right
    answer is the failure mode the sweep's classification calls `codegen`)."""
    out = []
    for base in struct_declared_bases(struct_defs, struct_def):
        if not struct_methods(base):
            continue
        if struct_is_framed(struct_def) and not struct_is_framed(base):
            out.append(base)
    return out


def inherited_layout_refusal(sub, base) -> str:
    """A subclass whose base's methods are compiled for a different layout."""
    return (
        f"{sub.name} inherits from {base.name}, and the two do not agree on "
        f"what a receiver IS: {base.name} has {struct_field_summary(base)}, so "
        f"its methods read `self` as the receiver's single word, while "
        f"{sub.name} has {struct_field_summary(sub)}, so its receiver is the "
        f"address of a frame. A method is compiled against the layout of the "
        f"class that DECLARES it and a call site carries no receiver type to "
        f"check with, so a {base.name} method called on a {sub.name} is handed "
        f"a frame address where it expects the field: it would read the "
        f"address as the value, and the program would build, run, and print a "
        f"number the source never wrote. Give {sub.name} the same shape as "
        f"{base.name} — a subclass that adds no field of its own inherits the "
        f"layout exactly — or keep {base.name} a plain struct and pass it as a "
        f"field"
    )



def iter_struct_defs(node):
    """Every StructDef under `node`, including nested ones.

    Public because the build pipeline needs the same set the census is taken
    over (`parse_module` attaches the evidence, `_prepare_functions` re-attaches
    it to the structs the file being compiled declares), and a second,
    slightly different notion of "the structs in this statement list" is how one
    of the two ends up measuring a class the other does not."""
    if isinstance(node, list):
        for x in node:
            yield from iter_struct_defs(x)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    if isinstance(node, F.StructDef):
        yield node
    for fname in node.__dataclass_fields__:
        if fname in ("line", "col"):
            continue
        yield from iter_struct_defs(getattr(node, fname, None))


def _split_declaration(struct_def):
    """`(fields, constants)` — the two halves of the class body, or None.

    None means "no evidence", i.e. the caller must fall back to counting every
    declared name as a field; see `struct_field_evidence` for why that is the
    answer rather than "no constants".

    `constants` is `[(name, default_node)]` in declaration order, which is also
    the order a positional constructor fills them in, so it is kept rather than
    reduced to a set."""
    evidence = struct_field_evidence(struct_def)
    if evidence is None:
        return None
    written, dynamic = evidence
    receivers = struct_receivers(struct_def)
    # The two per-method questions, asked ONCE: clause 2 wants every name any
    # method reaches through the receiver (the UNDEMOTED union), and the
    # per-method loop at the bottom of this function wants the same walks
    # DEMOTED. Both are the same `_receiver_names` result, so `reached` is the
    # union of what `struct_method_receiver_reads` just derived rather than a
    # second walk of every method body — which is what it was, and a whole extra
    # pass over the struct on every `_split_declaration` call.
    #
    # The two ask DIFFERENT questions on purpose, which is why both sets come
    # back. Clause 2 is "does a method spell this name as `self.NAME`", asked
    # about a name the CLASS BODY also declared, so what it decides is
    # field-versus-class-constant — and a declared name is storage the language
    # spells out, so a method that reads it is evidence and the answer is a
    # field either way, demoted or not. The per-method loop below is where a
    # name enters the field set with no declaration behind it, and that is the
    # loop that has to ask whether the name is a method instead.
    per_method = struct_method_receiver_reads(struct_def, receivers)
    reached = set()
    for _method, names, _fields in per_method:
        reached |= names
    # BRACKET PARAMETERS are compile-time, not storage: see
    # `struct_bracket_param_names`.  Priming `seen` with them keeps the declared
    # loop and the receiver-touch loop below from turning one into a field, and
    # it is the same set `_pre_rule_field_names` subtracts, so a struct with and
    # without the write census agrees about its width.
    params = struct_bracket_param_names(struct_def)
    fields, constants, seen = [], [], set(params)
    for field in struct_fields(struct_def):
        slots = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        for name in (slots or [struct_field_name(field)]):
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            # clause 1: a `__slots__` name is instance storage by declaration.
            # clause 3/4: written anywhere in the unit, by receiver or by name.
            # clause 5: nothing is demoted while the unit has a write whose
            # name cannot be read, so `dynamic` short-circuits all of it.
            through = reached | _receiver_names(getattr(field, "value", None),
                                                receivers)
            if slots or dynamic or name in written or name in through \
                    or getattr(field, "value", None) is None:
                # clause 6, and the reason a DECLARED field is not a constant:
                # a class-level name with no initializer (`var a: Int`) declares
                # storage, while one WITH a value (`_SIGNED = 1`) defines a
                # value every instance shares. `struct Pair: var a: Int; var b:
                # Int` is a two-field struct even in a program that never
                # touches either field, and refusing it is what
                # test_formal_imports.py's `a struct too wide for one word is
                # refused by name` asserts; demoting it would make the two
                # fields share one word the moment anything read them.
                fields.append(name)
            else:
                constants.append((name, getattr(field, "value", None)))
    # A `comptime NAME = expr` binding, which the parser put in
    # `comptime_aliases` and NOT in `fields` (see the carve-out at the end of the
    # rule above). It is appended AFTER the declared names, so every ordering
    # this file guarantees — declaration order for a positional constructor, and
    # the per-method order of the loop below — is unchanged by its presence; a
    # name that moves position in a diagnostic is a change nobody asked for.
    #
    # It is a class value by construction: evaluated once, at struct-definition
    # time, in the class body's own scope, with no instance in hand. So the only
    # question the rule above has to answer about it is whether this PROGRAM
    # stores into it, and that is clauses 3 and 5 verbatim: a name written
    # through any object in this unit, or any unit with a write whose name cannot
    # be read, keeps the alias as a FIELD, because then the value is
    # per-instance and the slot the write lands in is the only copy of it. The
    # reference engine agrees about which of the two it is: an instance read
    # consults the instance dict BEFORE the alias table (`myinterpreter`'s member
    # read), so `obj.A = 5` really does change what `obj.A` says, and folding
    # the declared 10 into it would be a wrong answer rather than a refusal.
    #
    # **Clauses 3 and 5 decide it and clause 2 does NOT**, and the difference
    # between the two loops is the whole point: `reached` is what this method's
    # body spells as `self.NAME`, and for a `comptime` binding that spelling is a
    # READ of the binding rather than of a field, so consulting it here would put
    # back exactly the refusal this closes. A unit that ASSIGNS the name
    # (`self.rank = …`, `o.rank += 1`, `setattr(o, "rank", v)`,
    # `Point(rank=1)`) still gets a FIELD, and that arrives through `written` —
    # the same clause 3 that carries the rest of the rule, and the direction
    # every doubt here resolves.
    #
    # **NO evidence, no claim**, and that is the rule rather than an omission: a
    # struct this function returns None for — a module parsed without the unit's
    # write census — is not asked the question at all, and
    # `_pre_rule_field_names` below counts every DECLARED name as a field and
    # knows nothing of a `comptime` binding, so a read of one there is a
    # refusal ("Coord has no field 'rank'") rather than a read of a slot whose
    # value nothing wrote. Counting the binding as a field instead would have
    # manufactured the 0 that clause 3's own reasoning above is careful never to
    # substitute, and `attach_field_evidence`'s docstring says why the two must
    # not disagree.
    for name, value in struct_comptime_aliases(struct_def).items():
        if not isinstance(name, str) or name in seen:
            # already a field or a constant: the class body declared the name
            # twice, and the `fields` spelling above won, which is the order
            # this table has always used.
            continue
        seen.add(name)
        if dynamic or name in written:
            fields.append(name)
        else:
            constants.append((name, value))
    # Per method, not globally sorted, so that the field list is byte-for-byte
    # the list `_pre_rule_field_names` produces for a struct with no evidence:
    # a name that moves position in a diagnostic is a change nobody asked for.
    # An alias name is in `seen` by the loop above, so a method that reaches
    # `self.LIMIT` does not put `LIMIT` back into the field list: the read is a
    # read of the class's value, and the substitution materializes it (or
    # refuses by name) rather than leaving it to a slot nothing writes.
    #
    # `struct_method_receiver_reads` and not `_receiver_names`, and the difference
    # is the whole of the method-name defect: a name this struct declares as a
    # METHOD and never stores into is a BOUND METHOD here, not a field, and
    # counting it invented a slot that nothing writes — so every read of it
    # returned zero, which is a number the source never wrote.
    # The reproducer for that zero is `test_formal_bracketed_method_field_set.py`'s
    # `a_value_position_method_reference_is_not_a_field` /
    # `a_method_name_the_struct_stores_into_is_still_a_field` pair: the first
    # says a bare read of a method name is not a field, and the second says a
    # store of the SAME name still is. Neither row means anything without the
    # other — a demotion that ignored the store would delete real storage and
    # build, which is the failure a layout bug is worst at, because nothing
    # refuses it.
    for _method, _reached, touched in per_method:
        for name in sorted(touched):
            if name in seen:
                continue
            seen.add(name)
            fields.append(name)
    return (fields, constants)



# `comptime NAME = expr` in a struct body is a CLASS-SCOPE BINDING, and it is in
# `StructDef.comptime_aliases` rather than in `StructDef.fields` — the parser puts
# it there (`fire_compiler._parse_struct`, a `ComptimeVarStmt` is neither a
# `VarDecl` nor an `AssignStmt`), the interpreter reads it when it builds the
# class (`myinterpreter.execute_StructDef`: `comptime_aliases[name] = eval_expr(...)`
# — once, at struct-definition time, with no instance in hand), and the compiled
# path read it through `gimple_codegen`'s `_struct_comptime_aliases`. NOTHING on
# the formal path read it: `grep -rn comptime_aliases formal/` finds this comment
# and nothing else, so a `comptime` class member was in no table here at all —
# not the field census, not `struct_class_constants`, not the constant-substitution
# rewrite. The consequence was measured and is a silent WRONG ANSWER, not a
# refusal, because the receiver sweep below counts any name a method reaches as a
# field: a one-word struct whose method reads `self.LIMIT` where `comptime LIMIT = 10`
# measures ONE field, reads the slot nothing ever writes, and prints 0 where the
# source says 10 (both architectures). See `struct_class_constants` for where the
# names are classified, and `formal/imports.py`'s `_attach_declared_census` for
# how an IMPORTED module's classes get the census this classification reads.
#
# ONE reader: the dict is wanted by the class-constant split, the substitution's
# site census and a diagnostic, and three `getattr(struct_def, …) or {}` spellings
# of the same default are three places to keep in step.
#
# It was briefly DEFINED TWICE in this tree — this definition and a second one
# carrying only a one-line docstring, added by `work/formal3-2-r2-r2` at the point
# the same merge had to resolve a conflict here. The bodies were identical, so
# Python quietly used the later one and the earlier was unreachable; the pair is
# gone rather than left for the next reader to find.
def struct_bound_names(struct_def) -> frozenset:
    """Every name this class body binds: fields, parameters and constants.

    **The scope `fold_literal_expr`'s `bound` needs**, and the reason it is a
    function here rather than `struct_field_names` at each call site: the two
    tables are not the same set. A class-level `NAME = value` and a
    `comptime NAME = …` are class CONSTANTS (`_split_declaration`), a declared
    or assigned `var` is a FIELD, and a bracket parameter is bound in the
    class scope as well — it is not STORAGE (`struct_bracket_param_names`) but
    it still shadows a builtin for a fold, so it is added here explicitly
    rather than through `struct_field_names`.

    Measured: `struct Box: var len: Int = 2` plus `comptime width =
    len([1, 2, 3])` puts `len` in the CONSTANT table and `width` in neither the
    field table nor the constants it is asking about, so a `bound` built from
    `struct_field_names` alone was empty and the fold fired on a name the class
    had bound. That is the fabricated word this reader exists to refuse.
    """
    names = set(struct_field_names(struct_def) or ())
    names.update(struct_bracket_param_names(struct_def))
    names.update(name for name, _default in struct_class_constants(struct_def))
    return frozenset(names)


def struct_comptime_aliases(struct_def) -> dict:
    """The struct's `comptime NAME = …` bindings: `{name: value node}`.

    One value for every instance, published by the class and stored nowhere —
    which is what makes a `comptime` binding a class-level CONSTANT in the sense
    `struct_class_constants` means, and is why the two tables cannot be derived
    from different places. The parser has said so in the shape of the tree rather
    than in a convention anyone has to remember: `fire_compiler.py`'s
    `_parse_struct` collects every `ComptimeVarStmt` of the class body into
    `StructDef.comptime_aliases` and leaves it out of `StructDef.fields`, and
    `myinterpreter.execute_StructDef` evaluates the dict once at
    class-definition time — so a read is answered from it, through the receiver
    as well as through the class name
    (`myinterpreter._eval_member_of`, after the instance fields and the methods
    and before the `AttributeError`).

    Before this existed the names were in NO table on this path, and each of the
    three that should have had one answered consistently and wrongly:
    `struct_field_names` (they are not in `fields`), `struct_class_constants`
    (which walked `fields`), and the constant-substitution rewrite in
    `formal/build.py` (which reads that table). A read of one therefore arrived
    at the member-access lowering as a name the struct does not have, and was
    refused with a sentence about a run-time `AttributeError` in a program that
    does not raise — `res._InjectedValues` in `std/iter/__init__.mojo`, declared
    fourteen lines above the read. That is
    `formal/hostmods/ast.mojo`-style module docstrings aside, this function is
    the whole of the fix's first half.

    NOT the whole of it: whether a read can be ANSWERED is still
    `class_constant_word`'s question, asked at the read. A binding's value may be
    a computation (`comptime rank = Self.element_types.length`,
    `utils/coord.mojo:214`), and a `comptime` binding whose right-hand side
    mentions a runtime parameter is refused by name rather than inlined — which
    is the same verdict a non-literal class-level constant already gets, and for
    the same reason."""
    return dict(getattr(struct_def, "comptime_aliases", None) or {})


def struct_derived_names(struct_defs, name: str) -> set:
    """Every struct in `struct_defs` whose BASE CLOSURE contains `name`.

    Transitive, because a question about inheritance has to be: `struct
    GrandChild(Child)` where `struct Child(Base)` derives from `Base` through a
    level this function never looks at, and a rule that answered "nothing
    derives from `Base`" about that would be answering a question about a
    different program. The closure is a fixed point rather than one pass for the
    same reason — the fixed point is the set, and one pass over the direct bases
    is a prefix of it.

    Returns struct NAMES, so a caller with a list of StructDefs can index it.

    **The final filter this used to end with is gone because it could not
    remove anything.** It read `{n for n in derived if n in set(names)}`, and
    `set(names)` was rebuilt — a fresh set of every struct's name — once per
    element of `derived`, so the tail cost `#derived × #structs` set insertions
    to return a set that was already exactly `derived`: `derived` only ever
    receives `own = getattr(st, "name", None)` from a struct in `struct_defs`
    that passed `own is None`, and `names` is the same collection's names, so
    every member of `derived` is in `names` by construction. `names` is
    therefore dead too, and with it one list build per call."""
    derived, grew = set(), True
    while grew:
        grew = False
        for st in struct_defs or []:
            own = getattr(st, "name", None)
            if own in derived or own is None:
                continue
            if any(b == name or b in derived
                   for b in (getattr(st, "bases", None) or [])):
                derived.add(own)
                grew = True
    return derived


def struct_is_derived_from(struct_defs, name: str) -> bool:
    """True when some struct in `struct_defs` names `name` in its `bases`.

    The one question a `comptime` binding's VALUE cannot be asked without, and
    the reason the substitution in `formal/build.py` stops at the base class.

    `struct Child(Base)` overrides `Base`'s `comptime rank` for every instance
    of `Child` — `myinterpreter.execute_StructDef` merges the bases' aliases in
    first and the child's own second, so the child's value is the one a read of
    `self.rank` inside a method `Base` declares resolves to when the receiver is
    a `Child`. Substituting `Base`'s literal at that read would print the parent's
    value for a child, which is a wrong answer and not a refusal.

    It cannot be checked the other way round either, because the interpreter also
    copies the base's METHODS onto the child: a method `Base` declares is called
    with a `Child` receiver (`_method_owners` dispatches by name and no struct in
    this unit inherits the method into its own `methods` list), so "the method is
    declared on `Base`" says nothing about which alias table the receiver's class
    has.

    Which is why the disqualification is per NAME and not per struct:
    `formal/build.py` withholds exactly the bindings a subclass REDECLARES, so a
    `Child(Base)` that overrides `rank` makes `self.rank` unanswerable inside a
    method `Base` declares while leaving every other name of `Base` answerable.
    A subclass that inherits the name cannot change it — the interpreter merges
    the bases' aliases into the child and the child adds its own, so an inherited
    binding reads exactly as the base declared it.

    Use `struct_derived_names` for the transitive closure; this is the direct
    question and it is what the docstring above is about.

    A limitation worth stating rather than hiding: `struct Child(Base)` is the
    only inheritance this parser records, and the base may arrive from an IMPORTED
    module, where `struct_defs` holds the imported declarations too — so a
    derivation from a module this unit never parsed is not visible here. That is
    not a hole in the rule but a fact about where the tables come from, and it is
    the direction the answer already takes: a struct whose bases this function
    cannot read is not disqualified by anything it cannot read."""
    return any(name in (getattr(st, "bases", None) or [])
               for st in struct_defs or [])


def _receiver_names(node, receivers) -> set:
    """The names `node` reaches through one of `receivers`."""
    out = set()
    _self_field_names(node, out, receivers)
    return out


def class_constant_candidates(struct_def) -> set:
    """Every name `struct_class_constants` could possibly return for this struct.

    A NECESSARY condition, and cheap where the real question is not: the rule
    `_split_declaration` applies is that a class constant is a name the CLASS
    BODY declared — a `StructDef.fields` entry, or a `comptime` binding, which
    the parser keeps in `StructDef.comptime_aliases` and never puts in `fields` —
    that is not written, not reached and not dynamically written. Every other
    clause of that rule is about the unit's write census, which is what makes
    the answer expensive: deciding it walks every method body of the struct (see
    `struct_method_receiver_reads`). The set of NAMES cannot contain anything the
    class body did not declare, so for a struct that declares nothing this
    answers the question without the walk — and a struct that declares nothing
    is the common case in a compiler's own sources, where `formal/arm64_codegen.py`'s
    `ARM64Codegen` is 177 methods and zero class-level values.

    It is a filter, not an answer: `set() ⊆ struct_class_constants(st)` always,
    and a non-empty set here says nothing about whether any of those names is a
    constant. A caller that needs the answer asks the real question."""
    out = set()
    for field in struct_fields(struct_def):
        name = struct_field_name(field)
        if isinstance(name, str):
            out.add(name)
    for name in struct_comptime_aliases(struct_def):
        if isinstance(name, str):
            out.add(name)
    return out


def struct_class_constants(struct_def) -> list:
    """`(name, default_node)` per class-level constant, in declaration order.

    The complement of `struct_field_names`, and empty for every struct with no
    evidence attached — where nothing can be told apart, so everything stays a
    field and there is no constant to speak of.

    Two things count as a class-level constant and only one of them is spelled
    `NAME = value` in `StructDef.fields`: a `comptime NAME = …` binding, which the
    parser keeps in `comptime_aliases` and never puts in `fields` at all, is
    stored nowhere per instance and so is exactly as much a constant as the other
    kind. `struct_comptime_aliases` is the accessor and the note above
    `_split_declaration` is the rule; the two are kept apart because "is a
    constant" (this function) and "can this read be answered"
    (`class_constant_word`, asked at the read) are different questions, and only
    the first is answered here."""
    split = _split_declaration(struct_def)
    return list(split[1]) if split is not None else []


def comptime_binding_reads_a_field(struct_def, value) -> list:
    """The field names a class-level initializer reads, in source order.

    A struct PARAMETER is a field here, and that is the whole reason this
    function exists: `_parse_struct_params_as_fields` puts `keys: List[T]` in
    `StructDef.fields`, so `struct Box[T, keys: List[T]]` has a field named
    `keys` and a class body may read `keys` or `Self.keys` for it. What the
    parameter IS — a value supplied per instantiation — is not in the tree
    anywhere, which is the fact `struct_parameter_not_bound_refusal` exists to
    say.

    Both spellings, because the class body uses both and the difference is
    which node carries the name: a bare read is an `IdentExpr`, and `Self.keys`
    is a `MemberExpr` whose `member` is a STRING and whose `obj` is the
    receiver spelling. `iter_nodes` has no parent, so the walk asks each node
    what it can answer about itself and nothing needs one.

    Only `Self` / `self` / `cls` / `this` bases count, so `other.FIELD` — a
    read of some OTHER class — is not reported as this struct's parameter."""
    if value is None or struct_def is None:
        return []
    # The BRACKET PARAMETERS are not storage (`struct_bracket_param_names`), and
    # they are exactly what this reader is for, so they are added back to the
    # body's field names rather than being read out of `struct_field_names`
    # (which stopped counting them when the temple's width had to match its
    # instantiation's).  A parameter read and a field read are reported the same
    # way here, as they were before the two sets were distinguished.
    fields = set(struct_field_names(struct_def) or ())
    fields.update(struct_bracket_param_names(struct_def))
    if not fields:
        return []
    bases = set(struct_receivers(struct_def) or ()) | {"Self", "cls", "this"}
    out = []
    for node in iter_nodes(value):
        name = None
        if isinstance(node, F.IdentExpr):
            name = node.name
        elif isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr) \
                and node.obj.name in bases:
            name = node.member
        if name in fields and name not in out:
            out.append(name)
    return out


def struct_parameter_not_bound_refusal(struct_name: str, spelling: str,
                                       value, fields) -> str:
    """The diagnostic for a class-level binding whose value reads a struct
    PARAMETER.

    A different refusal from the one about a non-literal `comptime` value, and
    the difference is the whole of it: that one is about the VALUE ("a `comptime`
    binding's value is … a CALL or a COMPUTATION rather than a literal, and this
    path has no comptime evaluator to run one"), and its repair — "write the
    value at the use site (a literal, or an assignment the compiler can see)" —
    is IMPOSSIBLE for this shape, because there is no value in the class body to
    write anywhere else. Measured on both architectures:

        struct Box[T: AnyType, keys: List[T]]:
            comptime length = len(keys)      # refused as "no comptime evaluator"

    The use site is `Box[Int, [1,2,3]]`, so the values ARE at the use site and
    are not literals there either — they are arguments to an instantiation this
    path does not perform. So the sentence a reader is given ("make it a
    literal") describes an edit that cannot be made, which is a refusal sending
    them to a line that does not exist.

    What is actually missing is narrower and nameable: a struct parameter's
    value is a property of the INSTANTIATION, and this path compiles a generic
    struct as one image for every instantiation (`doc/ABI.md` §Generics: a
    generic is not one boundary symbol; each instantiation is, and there is no
    monomorphizer here). So at the class body there is no instantiation, and
    `Self.<param>` names a slot nothing has filled — in the class body there is
    not even a receiver.

    `fields` is what the initializer actually reads, so the reader is sent to
    the parameter rather than to the binding."""
    shown = ", ".join(repr(f) for f in (fields or ())[:4])
    spelled = expr_spelling(value) if value is not None else "nothing at all"
    return (f"{spelling} reads a `comptime` class attribute of {struct_name}, "
            f"whose value is `{spelled}` — and what it reads is {shown}, a "
            f"PARAMETER of {struct_name}. A parameter's value belongs to an "
            f"INSTANTIATION: the use site supplies it as an argument "
            f"(`{struct_name}[…, <value>, …]`), and that argument is a value, "
            f"not a literal written in this class body, so there is nothing here "
            f"to write somewhere else. This path compiles one image for every "
            f"instantiation — `doc/ABI.md` §Generics makes each instantiation a "
            f"separate boundary symbol and there is no monomorphizer here — so "
            f"at the class body there is no instantiation, and `Self.{fields[0]}` "
            f"names a parameter nothing has supplied. That is a different fact "
            f"from a value this path cannot compute, and the two have different "
            f"next steps: this one is closed by binding the parameter values at "
            f"the instantiation site, not by editing the expression")


#: The expression nodes that BUILD a frame container. A comprehension ELEMENT
#: that is a container literal can be materialised per-iteration only when
#: nothing inside it builds ANOTHER container: the per-iteration storage is a
#: byte copy of the element's own blob, so a nested container's ADDRESS would be
#: copied rather than the container and every iteration would share it. A CALL
#: is in the set because a constructor such as `List()` allocates too, and a
#: SLICE because it builds a new blob from an old one.
_CONTAINER_BUILDING_NODES = (
    F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr, F.Comprehension,
    F.SliceExpr, F.CallExpr,
)


def template_attribute_read_ambiguous(template: str, attr: str,
                                      instantiations) -> str:
    """The diagnostic for `{template}.{attr}` where the consumer applies that
    template at MORE THAN ONE instantiation.

    A class-level value belongs to an INSTANTIATION and not to the template —
    `comptime length = len(Self.values)` is `4` in the instantiation of
    `[1, 2, 3, 4]` and `1` in the instantiation of `[9]`, and the two are two
    separate declarations under two mangled names
    (`formal/monomorph.py::instantiate_all`). So a read spelled through the
    template's own name names a value only when the program says which
    instantiation it means, and `formal/monomorph.py::rewrite_instantiation_uses`
    answers it exactly when this unit applies the template once. At two or more
    there is nothing to answer with, and the two ways of proceeding are both
    wrong: the template's own unsubstituted alias is a number no instantiation
    stands behind, and the first instantiation built is an order the source does
    not state.

    Named, not counted, because the repair is a spelling rather than a number:
    the value is reachable through an INSTANCE (`d.{attr}`) or through the
    mangled name of the instantiation meant, and the reader can see which
    instantiations this file has. the general shape (recorded in `bugs/plan/step-15a-monomorph-baseline.md`)
    a type argument in a NON-CALL position is not a
    demand — and this is the one spelling of it where the consumer supplies the
    argument somewhere else in the file and here supplies none."""
    shown = ", ".join(instantiations[:3])
    more = "" if len(instantiations) <= 3 else ", …"
    return (f"{template}.{attr} reads a `comptime` class attribute of "
            f"{template}, and a class attribute belongs to an INSTANTIATION, "
            f"not to the generic template — this file "
            f"applies {template} at {len(instantiations)} of them ({shown}"
            f"{more}), each with its own value for `{attr}`, so the read names "
            f"none of them in particular. Reading it through an instance "
            f"(`d.{attr}`) names one; reading it through one instantiation's own "
            f"name does too. Guessing the first one built would answer with a "
            f"number the source never wrote")


def _expr_builds_a_container(e) -> bool:
    """True when `e` is, or contains, an expression that builds a container."""
    if e is None or isinstance(e, str):
        return False
    if isinstance(e, _CONTAINER_BUILDING_NODES):
        return True
    if isinstance(e, F.UnaryOp):
        return _expr_builds_a_container(e.operand)
    if isinstance(e, F.BinaryOp):
        return (_expr_builds_a_container(e.left)
                or _expr_builds_a_container(e.right))
    if isinstance(e, F.TernaryExpr):
        return (_expr_builds_a_container(e.condition)
                or _expr_builds_a_container(e.then_val)
                or _expr_builds_a_container(e.else_val))
    if isinstance(e, F.CompareChain):
        return any(_expr_builds_a_container(o) for o in e.operands)
    if isinstance(e, F.MemberExpr):
        return _expr_builds_a_container(e.obj)
    if isinstance(e, F.SubscriptExpr):
        return (_expr_builds_a_container(e.obj)
                or _expr_builds_a_container(e.index))
    if isinstance(e, F.WalrusExpr):
        return _expr_builds_a_container(e.value)
    return False


def _comprehension_result_is_flat(comp) -> bool:
    """True when a comprehension's own RESULT blob holds no nested container.

    A comprehension's result is a `[count][element…]` blob (a list of pairs for
    a dict), so a byte copy of it duplicates every produced value. That copy is
    sound exactly when no produced value is itself a container built by this
    site: a container would be carried as its ADDRESS, so every copy would point
    at one shared scratch blob — the same aliasing defect
    `comprehension_element_is_flat_container` exists to prevent, one level up.
    The produced value is the comprehension's `element` (and its `value` for a
    dict), so this asks each of those whether it builds a container.
    """
    if not isinstance(comp, F.Comprehension):
        return False
    parts = ([comp.element, comp.value] if comp.kind == "dict"
             else [comp.element])
    return not any(_expr_builds_a_container(p) for p in parts)


def _container_ctor_base_name(call) -> str:
    """The base name of a call's callee, or "" — `List[Int]()` → `List`.

    The same two spellings `subscript_callee_names` recognises, reduced to the
    base STRING because `blob_constructor_lowering` is keyed on the name: a bare
    ident (`bytearray()`) and a subscript whose base is an ident (`List[Int]()`).
    A member callee (`m.List[Int]()`) is not a container constructor this path
    lowers, so it is left out rather than guessed at.
    """
    func = getattr(call, "func", None)
    if isinstance(func, F.IdentExpr):
        return func.name
    if isinstance(func, F.SubscriptExpr) and isinstance(func.obj, F.IdentExpr):
        return func.obj.name
    return ""


def comprehension_element_is_flat_container(element) -> bool:
    """True when a comprehension element is a container a byte copy can make
    per-iteration.

    THE predicate both emitters ask before materialising an element per
    iteration, and it is here rather than in either backend so the two
    architectures cannot disagree about which elements are representable — a
    comprehension that built on one machine and was refused on the other is the
    divergence this whole path is built to prevent.

    The element's container is stored per-iteration by copying its own blob into
    a slot of a `cap`-sized array (see the emitters' `_materialize_compr_element`),
    and a SHALLOW copy is sound only when nothing inside the element built a
    second container: the copy would carry the nested container's ADDRESS, so
    every iteration's outer container would still point at one inner object.
    That is the same aliasing defect one level down, and it is why the predicate
    recurses rather than looking at the element's node type alone.

    A NAME is deliberately NOT a container here, and that is correctness rather
    than a narrowing: `[a, b]` where `a` and `b` are outer lists copies the outer
    list per iteration and shares `a`/`b`, which is exactly what CPython does —
    distinct outer lists over the same elements. Only a container the element
    position itself BUILDS is the defect.

    A nested COMPREHENSION whose produced values are words is accepted, and the
    reason is the same recursion: `[[x + y for x in [1, 2]] for y in …]`'s inner
    result is a `[count][int…]` blob, so copying it per outer iteration gives
    each outer element its own list. What is still refused is an inner result
    that itself holds containers (`[[[z] for z in …] for y in …]`), where the
    copied words would be addresses of one shared scratch. The copy lands the
    inner result, already built, into the outer element array; it does NOT have
    to relocate the inner comprehension's own base, which is why the nested case
    does not need the runtime blob base the flat case does not need either.

    A SLICE is accepted exactly when its BASE's produced values carry no address
    of a blob this site built, which is the same question the literal arms ask
    of their children one level down. A slice copies element words out of its
    base into a new blob of its own, so a base that persists (`a[0:2]` under a
    NAME, a member read, a subscript) contributes only values or addresses of
    persistent objects \u2014 what CPython's own slice shares \u2014 and a base that is a
    display of scalars (`[1, 2, 3][0:2]`) contributes only words. A base built
    here that itself holds containers (`[[1, 2]][0:1]`) carries the ADDRESS of
    one scratch blob into every iteration's copy, so it stays refused, as does
    the slice of any base a byte copy cannot make flat. The slice of a SLICE is
    the recursion applied twice and is accepted on the same terms.

    A CALL is accepted for the same reason, and EVERY call rather than only
    the empty/sized container construction: the callee is elsewhere, so whether
    the result is a blob this site builds is a fact about the call SITE, and
    the emitter's own `_emit_type_constructor` and the static initializer
    already give each iteration its own storage.
    `a_comprehension_whose_element_is_a_call_returning_a_container_gives_each_
    one` is the row that decides it; a narrower arm that reads
    `blob_constructor_lowering` refuses that row and is asked to refuse nothing.

    The shapes that return False keep `comprehension_element_blob_refusal`:
    a comprehension whose produced values are containers, a list of lists, a
    The shapes that return False keep `comprehension_element_blob_refusal`:
    a comprehension whose produced values are containers, a list of lists, a
    slice whose base carries a scratch address, a constructor call, and every
    non-container expression. Those are the cases whose per-iteration
    materialisation needs the runtime blob base the refusal's own document
    describes.

    **Three arms were added (the concat and the call on 2026-10-16, the slice on
    2026-10-13), and all three are shapes whose blob this path already knows the
    SIZE of — which is the whole of what a copy needs.**

    * **A SLICE, when its BASE carries no scratch address.** A slice copies
      element words out of its base blob into a NEW blob of its own, so the
      per-iteration copy is sound exactly when the base's produced values are not
      ADDRESSES of a blob this site built. A base that persists (a name, a member,
      a subscript) contributes only values or addresses of persistent objects,
      which is what CPython's own slice shares; a base built here contributes the
      same words a flat container literal would (`[1, 2, 3][0:2]` is a display of
      scalars) and is asked the same question as one. A base built here that
      itself holds containers (`[[1, 2]][0:1]`) carries one scratch ADDRESS into
      every iteration's copy — the aliasing the literal arms refuse — so it
      recurses into `element.obj` and keeps the refusal above.
    * **A `+` on two containers whose operands are both flat.** A concat's result
      blob holds its operands' WORDS in one block, so the shallow-copy argument
      above is satisfied by the operands rather than by the node: `[0] + [y]`
      produces `[count][0][y…]`, every word of which is a scalar. What is NOT
      true of a concat is that the ledger delta is the result's size — the two
      operands reserve first and the result last — so each emitter reads the
      result's own size off `_emit_list_concat`, which is the one place that
      reserved it, rather than off the span.
    * **A CALL.** A callee that hands a container back has its block COPIED into
      the caller's own scratch at the call's own site
      (`container_returned_blob_sites`), so the caller's element site rewrites
      one block per iteration exactly as a display does — and that block is
      `[count][word…]` by the callee's own construction, or it is not copied at
      all (`returned_container_blob_bytes`). The block is parked ABOVE the blob
      region, which is why it does not move the ledger either, and the size comes
      from that same table. A call that returns no container has no block and no
      span, and falls out of the copy before this predicate is asked.

    All three were REFUSED before, and each refusal was a coverage hole rather
    than a soundness answer: `a_comprehension_whose_element_is_a_call_returning_
    a_container_gives_each_one` and `a_comprehension_whose_element_is_a_concat_
    of_displays_gives_each_one` in `test_formal_value_model.py` are CPython-
    oracle rows, and each aliases every iteration onto one object — `[mk(y) for
    y in ys]` answered `90` where CPython answers `60`.
    """
    if isinstance(element, F.Comprehension):
        return _comprehension_result_is_flat(element)
    if isinstance(element, F.SliceExpr):
        # A slice copies element words out of its base blob into a NEW blob of
        # its own, so the per-iteration copy is sound exactly when the base's
        # produced values are not ADDRESSES of a blob this site built. A base
        # that persists (a name, a member, a subscript) contributes only values
        # or addresses of persistent objects, which is what CPython's own slice
        # shares; a base built here contributes the same words a flat container
        # literal would (`[1, 2, 3][0:2]` is a display of scalars) and is asked
        # the same question as one \u2014 which is why this RECURSES rather than
        # refusing every base the element site builds. A base built here that
        # itself holds containers (`[[1, 2]][0:1]`) carries one scratch ADDRESS
        # into every iteration's copy \u2014 the aliasing the literal arms refuse.
        if _expr_builds_a_container(element.obj):
            return comprehension_element_is_flat_container(element.obj)
        return True
    if isinstance(element, F.BinaryOp) and element.op == "+":
        return (_expr_is_flat_container_operand(element.left)
                and _expr_is_flat_container_operand(element.right))
    # A CALL, and every call.  The reason is the one this predicate cannot see
    # from the call's own AST: the callee is elsewhere, so whether the result
    # is a blob this site builds or a reference to one it does not is a fact
    # about the CALL SITE \u2014 and `test_formal_run.py`'s
    # `a_comprehension_whose_element_is_a_call_returning_a_container_gives_
    # each_one` is the row that says the copy is per-iteration anyway for a
    # call that returns a container.  A narrower arm \u2014 accepting only the
    # empty/sized construction `blob_constructor_lowering` shapes \u2014 reads
    # better against the docstring and is WRONG: it refuses that row, and no
    # row asks it to refuse anything, because the emitter's
    # `_emit_type_constructor` and the static initializer give a call's result
    # its own storage per iteration on their own.
    if isinstance(element, F.CallExpr):
        return True
    if not isinstance(element, (F.ListExpr, F.TupleExpr, F.SetExpr,
                                F.DictExpr)):
        return False
    if isinstance(element, F.DictExpr):
        children = [x for pair in element.pairs for x in pair]
    else:
        children = list(element.elements)
    return not any(_expr_builds_a_container(c) for c in children)


def _expr_is_flat_container_operand(node) -> bool:
    """One operand of a CONCAT element: a container whose words the result carries.

    The same question `comprehension_element_is_flat_container` asks of an
    element, asked of a node the concat is holding up rather than of the concat
    itself — and it must be that same question, or `[0] + [[y]]` would be
    accepted because its LEFT operand is a flat display while its result carries
    the address of a container the element position also built.
    """
    if isinstance(node, F.CallExpr):
        return False
    return comprehension_element_is_flat_container(node)


def comprehension_result_is_flat(expr) -> bool:
    """True when a comprehension's own RESULT is a container a byte copy can
    make per-iteration.

    THE predicate for the shape `comprehension_element_is_flat_container` does
    not cover: an element that is ITSELF a comprehension. The element site
    cannot byte-copy the nested comprehension's scratch, because that scratch
    holds the nested result and the nested RESULT is exactly what has to be
    kept — so the emitters copy the nested comprehension's finished result blob
    (`[count][element…]`) into a slot of a `cap`-sized array instead, indexed by
    the outer result count. That copy is sound under the SAME condition the
    literal predicate states, one level in: a shallow copy carries the nested
    result's WORDS, so every word must be a scalar or a deliberately shared
    reference, never the address of a container the element position BUILT.
    That is why this recurses through a nested comprehension and rejects a
    container-building element, and it is here rather than in either backend so
    the two architectures cannot disagree about which nested comprehensions are
    representable.

    A dict comprehension carries two words per element (KEY and VALUE), so BOTH
    must be flat.

    The shapes that return False — a nested comprehension over a container-
    building element, a nested comprehension whose value opens a container —
    keep `comprehension_element_blob_refusal`.
    """
    if not isinstance(expr, F.Comprehension):
        return False
    el = expr.element
    if isinstance(el, F.Comprehension):
        if not comprehension_result_is_flat(el):
            return False
    elif _expr_builds_a_container(el):
        return False
    if getattr(expr, "kind", "list") == "dict":
        v = getattr(expr, "value", None)
        if isinstance(v, F.Comprehension):
            if not comprehension_result_is_flat(v):
                return False
        elif _expr_builds_a_container(v):
            return False
    return True


def _descendant_builds_a_non_literal_container(e) -> bool:
    """True when the subtree under `e` builds a container the element's own
    emission does not reserve at a LITERAL site.

    The question `comprehension_element_is_relocatable` asks of a container
    literal's children, and it is `_expr_builds_a_container` narrowed to the
    answer the relocation needs: a container literal is not the answer, it is
    a branch into its children (the relocation gives each such literal its own
    per-iteration slot), while a comprehension, a slice, a call and a star
    splat each build their blob where its own emission does not move it per
    iteration — a comprehension reserves its result in `_emit_comprehension`
    before its walk and reuses it, a slice reserves its result in its own
    emission, a call's returned block is parked above the blob region by
    `container_returned_blob_sites`, and a star literal appends into its blob
    at its own site — so any such blob's address in the element's words would
    point at one frame location every iteration shares, the aliasing the flat
    copy is refused for. A star is the same answer for its own reason: its
    literal lowers by APPENDING (`_emit_list_star`), which cannot target a
    slot the append does not read its count from.
    """
    if e is None or isinstance(e, str):
        return False
    if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr)):
        if isinstance(e, F.DictExpr):
            pairs = e.pairs or []
            if any(isinstance(k, F.UnaryOp) and k.op in ("**", "*")
                   for k, _v in pairs):
                return True
            children = [x for pair in pairs for x in pair]
        else:
            if any(isinstance(el, F.UnaryOp) and el.op == "*"
                   for el in e.elements or []):
                return True
            children = list(e.elements or [])
        return any(_descendant_builds_a_non_literal_container(c)
                   for c in children)
    return _expr_builds_a_container(e)


def comprehension_element_is_relocatable(element) -> bool:
    """True when a comprehension ELEMENT's containers are given a per-iteration
    BASE rather than a per-iteration COPY.

    THE predicate for the element a byte copy cannot make per-iteration and a
    base can: the element's region carries the ADDRESS of a container the same
    emission built, so a copy would share it, and the sound materialisation is
    to build each such container in the slot ITS iteration owns — a slot of a
    `cap`-sized array indexed by the result count, recomputed at run time —
    which the emitters' `_emit_list`/`_emit_dict` do when the element is this
    shape. It is here rather than in either backend so the two architectures
    cannot relocate — or refuse — the same element differently.

    The shape is a container LITERAL whose container-building descendants are
    all container literals — a list of lists, a tuple holding a list, a dict
    pair holding one — because those are the blobs the element's own emission
    reserves at the element site and the relocation can move. What is not this
    shape keeps `comprehension_element_blob_refusal`: a nested comprehension
    (its result is reserved in `_emit_comprehension` and reused), a slice (its
    result is a separate blob of its own), a call (its returned block is
    parked elsewhere), and a star splat (its literal appends at its own site).
    """
    if not isinstance(element, (F.ListExpr, F.TupleExpr, F.SetExpr,
                                F.DictExpr)):
        return False
    return not _descendant_builds_a_non_literal_container(element)


def comprehension_element_blob_refusal(spelling: str, element, cap: int,
                                       bytes_: int) -> str:
    """The diagnostic for a comprehension ELEMENT that opens a container and
    whose result a byte copy cannot materialize per iteration.

    **This is now the FALLBACK, not the whole answer.** A FLAT element — a
    display of scalars, or a dict display of scalars; one whose result blob
    holds no pointer to a blob built in the same emission — is given its own
    arena slot per iteration by both backends' `_materialize_compr_element`,
    because a byte copy of its result is sound. What reaches this refusal is
    the element that a byte copy of would STILL alias or that this path cannot
    size, the same shapes the predicate's docstring names: a nested
    comprehension, a slice whose base carries a scratch
    address, a constructor call, and every non-literal expression — a call, a
    subscript or a member read whose result this path cannot type among them.
    A container literal that holds containers of its own (a list of lists
    among them) is the OTHER materialisation, the one
    `comprehension_element_is_relocatable` answers with a per-iteration base
    rather than a per-iteration copy, so it does not reach this refusal.
    `comprehension_element_is_flat_container` is the shared predicate and
    `test_formal_run.py`'s `COMPREHENSION_ELEMENT_CASES` is the row set that
    pins both sides.

    **Where it does fire it is still a silent wrong answer if emitted, and that
    is why it is a refusal rather than a guess.** A container on this path is a
    blob in the frame, and the frame is ONE sequential ledger: `_reserve_blob`
    steps `_list_cursor` along `_blob_cap`, so a site's reservation happens
    ONCE at compile time. A comprehension's element is one site that runs `cap`
    times, so the blob is one allocation shared by every iteration and each
    iteration overwrites the last one's contents. Measured on both
    architectures, CPython 3.14 against the same source:

        [[y, y + 1] for y in [10, 20, 30]]     CPython: 11 21 31
                                              this path: 31 31 31
        [[x + y for x in [1, 2]] for y in [10, 20, 30]] and then v[0] summed
                                              CPython: 63   this path: 93

    **Both of those are now materialised per iteration** by
    `comprehension_element_is_flat_container`, so this message fires only on
    the shapes whose per-iteration copy is unsound and whose containers the
    relocation does not build at the element site: a nested comprehension
    whose produced values are containers, a slice whose base carries a scratch
    address and a constructor call. A container literal that holds containers
    of its own (a list of lists among them) is materialised per iteration by
    the relocation, and its rows answer rather than refuse. The paragraph above is the
    measurement that made the refusal the right answer for THEM; the two
    reproducers are kept because they are what a copy must answer, and are the
    rows `test_formal_run.py`'s `COMPREHENSION_ELEMENT_CASES` now assert.

    **A slice was in that list and is not any more** — the same re-reading that
    closed the nested row applies to it: a slice copies element words out of its
    base, so the copy is sound whenever the base's produced values are not
    addresses of a blob built at this site. Only the base that itself holds a
    container stays here (`[[1, 2]][0:1]`); `a[0:2]` and `[1, 2, 3][0:2]` are
    materialised and answer CPython.

    For the nested case the second row is the one that says a refusal was
    necessary rather than tidy: it exits 1 as well as answering wrongly, because
    the count the third iteration wrote landed one word past a blob sized for one
    element. And the first is silent in the way this repository's rules call out
    — a caller that appends to element 0 gets element 1's list too, which no
    assertion in the program can notice.

    **`bytes_` is the ELEMENT's own footprint, measured by the ledger.** The
    emitters ask for the delta across the element's own emission and refuse when
    it is not zero, so the set of constructs that allocate is whatever the
    emitters allocate rather than a list kept in step with them by hand — a list
    here would be a second copy of `_reserve_blob`'s callers, and the defect it
    is here to prevent (a construct nobody remembered) is exactly the defect a
    hand-kept list grows.

    The remedy is stated in the source's own terms because there are two, and
    only one of them is a workaround: build the containers in an explicit loop
    over a list the program owns (`out = []` … `out.append(...)`), which is the
    same program with a per-iteration allocation this path HAS — `append`
    grows one blob and there is one append site per iteration of an ordinary
    loop. The other, a comprehension whose element is a single word, has no
    container in it and is not affected.

    **`cap > 1` is the callers' condition to ask this at all**, and it is
    soundness rather than politeness in the other direction: `_compr_cap` is an
    UPPER BOUND on the iteration count, so `cap == 1` means the body runs at
    most once and one shared blob is then not shared by anything — `[[y] for y
    in [10]]` answers CPython today and must keep answering it.
    """
    spelled = expr_spelling(element) if element is not None else "nothing"
    return (f"{spelling}: the element `{spelled}` opens a container, and this "
            f"path has one frame blob for it — {bytes_} bytes reserved once, at "
            f"the element's own site — while the comprehension body runs up to "
            f"{cap} times. Every iteration would therefore append the SAME "
            f"object and the last one's contents would be in all of them, and "
            f"on a nested comprehension the count word runs past the blob and "
            f"the append guard exits 1. Refused rather than emitted, because a "
            f"list whose elements are all one object is a wrong answer in a "
            f"shape nothing in the program can observe. Build the containers in "
            f"an explicit loop over a list the program owns (`out = []`, then "
            f"`out.append(…)` inside a `for`), which allocates per iteration "
            f"because each iteration runs its own append")


def struct_field_names(struct_def) -> list:
    """Every INSTANCE field name this struct has, in a stable order.

    THE field set, and therefore the whole of the representability decision
    (`struct_fits_one_word` reads its length). It is derived from every place a
    field can be introduced rather than from the class body alone, because the
    class body alone is not where most of this repo's own classes put their
    fields:

      * a class-level `VarDecl` / assignment — the annotated or defaulted
        spelling (`x: int`, `x: int = 0`, `x = 0`) — MINUS the names that are
        class-level CONSTANTS rather than storage, which is what
        `struct_class_constants` decides and the note above that function is
        the rule;
      * a class-level `__slots__ = (...)` — the one class-level assignment
        that names fields instead of storing one, contributing the names it
        lists rather than the name `__slots__`. Names it lists are never
        demoted: that is a declaration of instance storage in the language;
      * any `<receiver>.<name>` a method of this struct touches — the
        Python-style spelling, in which the fields are whatever `__init__`
        assigns.

    Reading only the class body measured `imports.Resolver` — which assigns
    `path`, `gcc`, `flags` and `_modules` in `__init__` and declares nothing —
    as a struct of NO fields, i.e. as one word. The consequence was not a
    refusal but a wrong answer: each field became a separate function-local
    slot spelled `self.<field>`, the receiver word was never written by
    anything, and every accessor returned an uninitialised register. A formal
    backend that mismeasures a struct and then computes on the wrong storage is
    worse than one that refuses, so the set is derived.

    A name that appears in two of those places is ONE field, not two: a class
    that declares `x: int` and also assigns `self.x = 0` has one field.

    What it still cannot do: with no evidence attached it counts a class-level
    constant as a field, because it cannot see the unit that would settle it.
    That remains the conservative direction — see the note above
    `struct_class_constants` — and it is why a reported width is an UPPER
    BOUND whenever the evidence is missing, which is why every refusal that
    quotes one also quotes the names it counted.

    **THE BASE'S FIELDS ARE IN THIS LIST, base-first** (`attach_inherited_fields`
    is where they are resolved and `CPYTHON_EXCEPTION_BASES` is why a base this
    image does not declare can still contribute a field). This function used to
    answer for the class body alone, and every reader below it — the width, the
    arity, the slot index, the frame defaults — inherited that answer, so the
    whole representability decision was made about a subclass's own fields
    while the program had a base's. The derivation of the OWN half is
    `_own_field_names`, unchanged; the merge is one pass over the two lists."""
    merged = struct_merged_field_names(struct_def)
    if merged is not None:
        return list(merged)
    return _own_field_names(struct_def)


def _own_field_names(struct_def) -> list:
    """The field names the class BODY declares, with no base merged in.

    What `struct_field_names` returns for a struct nothing resolved the
    inheritance of, and the second half of what it returns for one that did.
    Split out so the merge has a name for the thing it merges onto rather than
    reaching into the middle of the derivation above."""
    split = _split_declaration(struct_def)
    if split is None:
        return _pre_rule_field_names(struct_def)
    return list(split[0])


def _pre_rule_field_names(struct_def) -> list:
    """The field set as it was before constants were separated out: all of them.

    What `struct_field_names` returns for a struct with no evidence attached,
    and what it returned for every struct before this rule existed. Kept as its
own function rather than inlined so the two derivations cannot drift apart
    in their handling of `__slots__` and of `self.<name>` — the parts that
    are not about constants at all.

    It knows NOTHING of a `comptime` binding, deliberately. With no evidence
    there is no clause 3 to ask, and the two answers available are a field —
    whose slot nothing writes, so a read of it fabricates a 0 — and a constant,
    which cannot be substituted without the write census that is exactly what is
    missing. The refusal is the honest answer, so a binding stays invisible here
    and a struct nobody attached evidence to reports the read as a name it does
    not have."""
    names, seen = [], set()

    def add(name):
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            names.append(name)

    params = struct_bracket_param_names(struct_def)
    for field in struct_fields(struct_def):
        declared = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        if declared:
            for name in declared:
                add(name)
        else:
            add(struct_field_name(field))
    # A BRACKET PARAMETER is not storage (see `struct_bracket_param_names`),
    # so it must not enter the set even when a method spells it through the
    # receiver — which is what the next loop would otherwise do.  `seen` is
    # primed with them rather than filtering afterwards, so the method walk
    # cannot re-add one under a different field node.
    for _param in params:
        seen.add(_param)
    receivers = struct_receivers(struct_def)
    # `struct_method_receiver_reads` and not the bare walker, for the same reason
    # `_split_declaration`'s per-method loop uses it: a name this struct declares
    # as a METHOD and never stores into is a bound method, and counting it as a
    # field put a slot in the frame that nothing writes.
    # The DECLARED names above are untouched — a class-level `var x: Int` is
    # storage the language spells out, whatever else the struct calls `x`.
    for _method, _reached, touched in struct_method_receiver_reads(
            struct_def, receivers):
        for name in sorted(touched):
            add(name)
    return names


def struct_field_count(struct_def) -> int:
    """How many fields the struct has — the derived count, never the raw one.

    `len(struct_fields(st))` answers a different and much weaker question (how
    many the class body declares) and is what this used to return; see
    `struct_field_names` for what went wrong when that was the answer."""
    return len(struct_field_names(struct_def))


def struct_sole_field_name(struct_def):
    """The name of the struct's one field, or None if it does not have exactly one.

    Read out of the DERIVED field set rather than out of `StructDef.fields[0]`,
    because a one-field struct need not have declared its field: a class whose
    `__init__` assigns `self.n` has one field and no field node at all, so
    indexing the declared list for it either found a different struct's idea of
    the fields or found nothing."""
    names = struct_field_names(struct_def)
    return names[0] if len(names) == 1 else None


# How many field names a width diagnostic will spell out before it says "and
# more" instead. A refusal that lists 263 names has replaced a usable message
# with a wall of text, and the names are there to let the reader CHECK the
# count, which a prefix does just as well as the whole census.
MAX_LISTED_FIELDS = 6


def struct_field_summary(struct_def) -> str:
    """`N fields: a, b, c` — the width, and the names behind it.

    Every refusal that quotes a width quotes the names too, because the derived
    count is an UPPER BOUND — a class-level name the unit's evidence could not
    clear is still counted, and one with no evidence attached counts every
    declared name — and a bare number would be asking the reader to trust a
    census they cannot check. The list is bounded by `MAX_LISTED_FIELDS`:
    past that the count itself is the news and the first few names are enough
    to confirm the tool looked at the class you think it did.
    """
    names = struct_field_names(struct_def)
    if not names:
        return "no fields at all"
    if len(names) <= MAX_LISTED_FIELDS:
        return f"{len(names)} field(s): {', '.join(names)}"
    return (f"{len(names)} fields (too many to list; the first "
            f"{MAX_LISTED_FIELDS} are {', '.join(names[:MAX_LISTED_FIELDS])})")


def struct_width_cost(struct_def) -> str:
    """What closing this particular gap would take, in one clause.

    With the by-reference receiver on (the default; see
    `wide_receiver_by_reference`) a width above one is no longer a wall at all
    and the text says so, because a diagnostic that describes a problem the
    tool has already solved sends the reader looking for a bug that is not
    there. What is still not closed is named instead: the *proof* side of a
    wide receiver is reached only for the cases
    `FORMAL_wide_receiver_by_reference.md` (deleted; fixed) records."""
    n = struct_field_count(struct_def)
    if wide_receiver_by_reference():
        return (f"{n} fields is a frame of {n} 8-byte slots with a pointer "
                f"receiver, which is the same code as any other width; what is "
                f"still per-width is the proof (a method's callee contract is "
                f"stated modulo its receiver frame — Refine.FrameOk_except)")
    if n == 2:
        return ("two fields is a one-word model plus a second word: an ABI "
                "change, and the cheapest of the widths to close")
    if n <= MAX_LISTED_FIELDS:
        return (f"{n} fields is that same ABI change with a layout to invent: "
                f"a frame slot per field, and a receiver that is a pointer to "
                f"it rather than the value")
    return (f"{n} fields is not an ABI special case at all: it needs a calling "
            f"convention that passes aggregates, a register allocator that can "
            f"spill one, and a proof model whose values are no longer one word")
