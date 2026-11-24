# CODEGEN: `_check_no_value_shadow` reads a keyword label inside brackets as an assignment binding

Part 4 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Independent of the other parts.

## Goal

`monomorphize._check_no_value_shadow` (`monomorphize.py:219`) refuses a template when a type parameter is
also used as a binding name. Its "is this an assignment?" check excuses `identifier = ...` lines only inside
`{}` depth, so a keyword label inside a `[...]` or `(...)` is read as a binding. The measured case is
`address_space=Self.address_space` (`std/collections/span.mojo:859`) inside a `Pointer[...]` bracket: the
label `address_space` is not a binding, but the check raises. Excuse labels inside any open bracket or
paren, not only braces, while still raising for a real statement-level `T = ...` binding of a type parameter.

## Acceptance

- A template whose only `address_space=` occurrence is a keyword label inside `Pointer[...]` passes the check.
- A template with a real statement-level binding (`    T = 3` where `T` is a type parameter) still raises.
- A binding written inside a `{...}` literal that the check already excuses stays excused.

## Done when

Add `test_keyword_label_in_brackets_is_not_a_value_shadow` to `test_gimple.py` with the first two Acceptance
cases, then run:

    python3 -m pytest test_gimple.py -k test_keyword_label_in_brackets_is_not_a_value_shadow -q

It must fail before the change and pass after.
