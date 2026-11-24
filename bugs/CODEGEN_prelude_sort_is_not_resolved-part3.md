# CODEGEN: `bind_type_args` reads a `Span`-shaped bracket positionally, not by its deduced prefix

Part 3 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Depends on parts 1 and 2 for the
`Span` binder to produce a complete answer; its own test does not need them.

## Goal

The stdlib declares `struct Span[mut: Bool, //, T: AnyType, origin: Origin[mut=mut], *, address_space: AddressSpace = .GENERIC]`.
The `//` makes `mut` a DEDUCED leading parameter, but the stdlib spells the type `Span[T, origin]`
(two arguments). `elaborate.bind_type_args` (`elaborate.py:683`) reads the arguments positionally, so `T`
lands on `mut`. Make `bind_type_args` treat the deduced prefix as deduced: for a bracket shorter than the
full parameter list, `mut` must be deduced from the `origin` argument (a `MutOrigin` argument gives
`mut = True`, an `ImmutOrigin` gives `False`), and `address_space` must take its default, the way
`complete_explicit_type_args` already does for function calls. Reuse `_deduce_prefix_from_rest`; do not
add a second deduction.

## Acceptance

- `bind_type_args` on `Span` with `['Int64', 'MutOrigin']` returns
  `{'mut': 'True', 'T': 'Int64', 'origin': 'MutOrigin', 'address_space': 'GENERIC'}` (the value text may
  match the existing spelling; the binding of `T` must be `Int64`, not `True`).
- A full-length list (`['True', 'Int64', 'MutOrigin', 'GENERIC']`) is still taken as written.
- The existing fallback documented on `bind_type_args` (a list that carries the prefix but omits a
  trailing default) keeps its behaviour.

## Done when

Add `test_bind_type_args_deduces_span_prefix_from_its_origin` to `test_gimple.py`, asserting the first two
Acceptance cases, then run:

    python3 -m pytest test_gimple.py -k test_bind_type_args_deduces_span_prefix_from_its_origin -q

It must fail before the change and pass after.
