# CODEGEN: `type_param_defaults` splits a bracket default at an `=` inside its brackets

Part 1 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Independent of the other parts.

## Goal

`elaborate.type_param_defaults` (`elaborate.py:415`) splits a bracket parameter's default at the first `=`
it finds, even when that `=` is inside the brackets of the parameter's own annotation. In the stdlib's
`std/collections/span.mojo`, `struct Span[mut: Bool, //, T: AnyType, origin: Origin[mut=mut], ...]` gives
`origin` the default text `mut]` instead of "no default", and `_default_type_arg('mut]')` then rejects it.
Split only at a top-level `=` (depth 0 with respect to `[]`, `()`, `{}`), so the annotation stays whole
and the default is only the text after a top-level `=`.

## Acceptance

- For `struct Span[mut: Bool, //, T: AnyType, origin: Origin[mut=mut], *, address_space: AddressSpace = .GENERIC]`,
  `type_param_defaults` returns `{'address_space': '.GENERIC'}` and does NOT return a default for `origin`
  (`origin` has no default; its `=` belongs to the annotation).
- A default that is itself bracketed (`x: Int = f[a=1]()`) keeps its whole text.
- No other caller's behaviour changes: `test_gimple.py` still passes in full.

## Done when

Add `test_type_param_defaults_splits_only_at_a_top_level_equals` to `test_gimple.py` (module level, next to
the other `test_span_*` tests), asserting the two cases above, then run:

    python3 -m pytest test_gimple.py -k type_param_defaults_splits_only_at_a_top_level_equals -q

It must fail before the change and pass after.
