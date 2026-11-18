"""The builtin scalar types, and the traits the compiler synthesizes for them.

ONE language fact, in one place, because two independent consumers need it and
they must not drift apart:

  * `ownership_check._type_ann_is_trivial` — the lifetime-tracking gate. Real
    Mojo records liveness only for values that are NOT trivially
    register-passable, so a binding declared as one of these types is never
    tracked and a use after `x^` is legal.
  * `mojo/middle/comptime.conforms_to` — the compile-time conformance
    predicate. `conforms_to(T, TrivialRegisterPassable)` has no source-level
    struct declaration to read for a builtin scalar, so without this table the
    question stayed undecidable and a `comptime if` over an alias such as
    `std.traits.IsTriviallyDeinitable[T]` could not fold at `T = Int`, leaving
    a runtime branch on an undeclared name's zero word.

The rule and its source are in `ownership_check`'s module docstring: real
Mojo's `Mojo/lib/LowerLIT/CheckLifetimes.cpp` (`isRegisterPassableTrivial`)
says "other values of raw MLIR type are always trivial", and
`std/builtin/value.mojo` declares

    trait TrivialRegisterPassable(
        std.traits.Deinitable,
        std.traits.ImplicitlyCopyable,
        std.traits.Movable,
        RegisterPassable,
    ):

so the conformance is transitive through that declared base list (and through
`ImplicitlyCopyable -> Copyable -> Movable`).
"""

# Builtin scalars that are raw register values in real Mojo. `UInt` is here
# alongside the fixed-width spellings for the same reason they are: it is a
# builtin scalar this compiler lowers to `uint64_t` (`_TYPE_MAP`), not a
# source-level struct that could carry an explicit conformance.
TRIVIAL_REGISTER_PASSABLE_TYPES = frozenset((
    'Int', 'Int8', 'Int16', 'Int32', 'Int64', 'Int128',
    'UInt', 'UInt8', 'UInt16', 'UInt32', 'UInt64', 'UInt128',
    'Float', 'Float16', 'Float32', 'Float64', 'Float128',
    'Bool', 'Byte', 'Char', 'Address',
))

# `TrivialRegisterPassable`'s transitive base list, as declared in
# `std/builtin/value.mojo` and `std/traits/copyable.mojo`: a type that conforms
# to it also conforms to every trait here.
TRIVIAL_REGISTER_PASSABLE_TRAITS = frozenset((
    'TrivialRegisterPassable',
    'Deinitable',
    'ImplicitlyCopyable',
    'Copyable',
    'Movable',
    'RegisterPassable',
))
