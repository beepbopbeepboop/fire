# CODEGEN: `_default_type_arg` rejects an enum-value default such as `.GENERIC`

Part 2 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Independent of the other parts.

## Goal

`elaborate.py::_default_type_arg` (`elaborate.py:510`) accepts a literal or a TYPE-named expression, and
returns None for anything else. The stdlib's `Span` declares `address_space: AddressSpace = .GENERIC`
(a leading-dot enum value), which matches neither shape, so `bind_type_args` cannot fill `address_space`
and the whole generic struct stays unelaborated. Teach `_default_type_arg` the leading-dot enum-value shape:
`.GENERIC` renders as the enum member `GENERIC` (the same spelling `AddressSpace.GENERIC` the stdlib uses
when it names the value), and a non-member leading-dot default still returns None.

## Acceptance

- `_default_type_arg('.GENERIC')` returns a concrete, non-None argument that the generic-struct instance
  can use as its `address_space` value.
- `_default_type_arg('.')`, `_default_type_arg('.lower')` (not an enum member spelling the elaborator can
  prove) and `_default_type_arg('mut]')` still return None.
- Literal and type-named defaults keep their current results.

## Done when

Add `test_default_type_arg_renders_a_leading_dot_enum_value` to `test_gimple.py` asserting the cases above,
then run:

    python3 -m pytest test_gimple.py -k test_default_type_arg_renders_a_leading_dot_enum_value -q

It must fail before the change and pass after.
