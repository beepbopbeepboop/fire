# CODEGEN: a scalar list BUILT at runtime (comprehension / `list(range)`) and nested in a container the runtime walks generically still reprs a `0` as `None`

**State: OPEN, measured 2026-10-07, exit 0 (or a crash for a float), repr-only.**

## What this is

The sibling of the now-fixed "a `0` in a scalar list literal nested in a dict
display prints as `None`" bug: a SCALAR list literal nested in a dict display
used to print its `0` as `None`, because `_mojo_repr_dict` hands the value to
`_mojo_generic_elem_repr` -> `_mojo_repr_list`, whose generic walker answers
`None` for a zero word. That is fixed at the LITERAL:
`_lower_list_literal` / `_lower_tuple_literal` now record per-slot kinds
(`mojo_list_set_kinds`) for a homogeneous scalar literal, so the runtime walker
describes each slot by its real kind.

A list the LITERAL lowering never saw — one BUILT at runtime by a
comprehension or `list(range(n))` — still records no kinds on the value, so the
same generic walker mis-renders it. Measured on this tree:

    print({'k': [i for i in range(2)]})      compiled {'k': [None, 1]}  CPython {'k': [0, 1]}
    print({'k': [i * 0.5 for i in range(2)]})compiled (nothing)         CPython {'k': [0.0, 0.5]}
    print({'k': list(range(2))})             compiled {'k': [None, 1]}  CPython {'k': [0, 1]}
    def f(): return [i for i in range(2)]
    print({'k': f()})                        compiled {'k': [None, 1]}  CPython {'k': [0, 1]}
    print([{'j': [i for i in range(2)]}])    compiled [{'j': [None, 1]}]CPython [{'j': [0, 1]}]

The float case is worse than a wrong digit: `_mojo_generic_elem_repr` reads the
IEEE-754 bits as a value and `mojo_read_type_tag_safe` dereferences a
bit pattern that looks like an address, so the program dies with no output.

A list DERIVED from a literal is already fine, because the derivation carries
the source's kinds (`mojo_list_inherit_kinds`): `sorted([1, 0])` and
`a[:]` both print CPython's text. `list(range(2))` is the producer that has no
literal to inherit from.

## Why it is not fixed with the literal change

The literal can name its slot kinds statically, one byte per slot, because its
slot count is a compile-time fact. A comprehension's length is a RUNTIME fact,
so `mojo_list_set_kinds`'s one-byte-per-slot string cannot describe it. The
element TYPE is known at compile time (`gen._elem_types[res]` is `int64_t` /
`double` / `_Bool`, and `_list_repr_fn` already picks the right typed walker for
a top-level `print`), so the information exists; what is missing is a channel
that tells the RUNTIME walker the whole list is homogeneous of one kind.

## Exact next step

One of these, both in `mojo/backend_gimple/`:

1. A per-list `elem_kind` byte (a second, homogeneous-only channel beside the
   per-slot kinds row) set by the comprehension / `_lower_ctor_from_iterable`
   result lowering from `gen._elem_types[res]`, consulted by
   `_mojo_repr_list`'s generic walker before it falls to
   `_mojo_generic_elem_repr`. One byte per list rather than per slot, so it
   costs nothing on a long list and needs no runtime length.
2. Record a per-list ELEMENT REPR function for a homogeneous scalar list
   (`mojo_list_set_elem_repr` already exists and `_mojo_repr_list` asks
   `mojo_list_repr_elem` per slot), using the runtime's own
   `mojo_repr_int` / a double/bool thunk. This is the mechanism the struct shim
   already uses and needs no new runtime state, only a codegen shim/registration
   for the scalar functions.

Either way the acceptance is the five rows above, CPython as the oracle, run
through `test_gimple_runner.py`'s `compile_mojo_to_gimple_exe`, plus the
existing float row (which currently crashes).

## Regression

The literal half is pinned by
`test_gimple_runner.py::gimple_nested_scalar_container_repr_uses_recorded_kinds`.
This residual needs its own case beside it once a channel exists.

## Related

- `bugs/CODEGEN_materialized_container_has_no_element_type.md` — the same
  "an element type only knowable at runtime" shape one level down.
