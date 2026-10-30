# CODEGEN: four gimple runner cases are red on HEAD (not caused by the nested-list fix)

## Status 2026-10-29 — three of four fixed; one remains

Fixed: `list(<a mixed list>)` was a typed walk. The walk read every slot with
the promoted element type (`double` for `[1, 2.5]`), so the int slot came out
as the double's bit pattern, and the copy inherited that type as its element
repr. `_lower_ctor_from_iterable` (`mojo/backend_gimple/emit_calls.py`) now
copies a source that records its own per-slot kinds with `mojo_list_copy`,
which copies the raw words and the kinds row. Cases that now pass:

- `gimple_heterogeneous_list_literal_keeps_each_slot` (`[1, 2.5]`, `list(f)`)
- `gimple_struct_mixed_reads_survive_a_derivation` (`list(t)`, `list(c)`)
- `gimple_struct_mixed_reads_survive_a_function_boundary` (`list(u)`)

Pinned in `test_gimple_runner.py` by `gimple_list_copy_of_mixed_list_reads_each_slot`
(index, iterate and copy-again of a copy).

Still red: `gimple_ctor_param_polymorphic_slot_reads_receiver`. It is a method
call on a polymorphic slot with no static type, a different defect. The plan is
in `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`.

Found 2026-10-29 while verifying `CODEGEN_nested_list_param_two_kinds_segfaults`
(fixed; its doc deleted). A full `python3 test_gimple_runner.py` on a pristine
`git archive HEAD` copy fails these four cases with the same output as on the
fixed tree, so they predate that change.

## What I ran

`python3 test_gimple_runner.py` (whole file) in a `git archive HEAD` copy:
`470 passed, 5 failed` (the fifth is the nested-list case the fix addresses).

## What I saw (expected vs got)

- `gimple_struct_mixed_reads_survive_a_derivation`: `[1, 1.0]` expected,
  got `[1, 4607182418800017408]` (the float's raw IEEE-754 bits).
- `gimple_struct_mixed_reads_survive_a_function_boundary`: `[7, 0.5]` expected,
  got `[7, 4602678819172646912]`.
- `gimple_heterogeneous_list_literal_keeps_each_slot`: `[1, 2.5]` expected
  (the line after `1\n2.5\n`), got `[5e-324, 2.5]` (the double's bits).
- `gimple_ctor_param_polymorphic_slot_reads_receiver`: `2` expected, got
  `4348269312` (a pointer decimal).

## Why this is a doc, not a fix

Each is a float or pointer read through the int accessor on a struct field or a
mixed-kind list slot: the same family as the boxed-read route. The nested-list
fix does not touch these paths (it only changes list-of-lists parameter kinds
and inner string-list kinds). Not investigated further this round.

## Next step

Start from `gimple_heterogeneous_list_literal_keeps_each_slot`: it is the
smallest (a single heterogeneous literal, no call boundary). Check whether its
`[1, 2.5]` slot is read via `mojo_list_get_int` instead of `mojo_list_get_boxed`,
using `gimple_codegen`'s `_maybe_kinds_vals` gate in `_lower_list_literal`. Then
the struct-field cases, which go through `_field_nested_elem_types` /
`_actual_types`.
