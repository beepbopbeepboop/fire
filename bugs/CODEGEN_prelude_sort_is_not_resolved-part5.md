# CODEGEN: a `Span[X, o]` PARAMETER annotation is never materialized as a generic struct

Part 5 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Depends on parts 1-4: until the
`Span` binder is correct, materializing it cannot succeed.

## Goal

`emit_resolve._materialize_generic_struct_mentions` (`emit_resolve.py:4392`) is called for FIELD and RETURN
annotations only (around `emit_resolve.py` 4211 and 4227). A `Span[X, o]` parameter annotation of a helper
instance therefore keeps the builtin `Span` stub, and its method calls (`as_ref`, `unsafe_get`,
`unsafe_swap_elements`, `unsafe_ptr`) become weak no-op stubs. Call the same materialization for parameter
annotations of an instance being emitted, through the same helper, so a `Span[X, o]` parameter gets
`_ensure_generic_struct('Span', [X, o])` exactly as a field would.

## Acceptance

- Compiling a generic function whose parameter is `Span[T, origin]`, instantiated with a proven `Span[Int64, MutOrigin]`,
  emits the materialized `Span` struct's methods (no `Span_as_ref` / `Span_unsafe_get` weak stub in that
  instance's C for a method the stdlib `Span` defines).
- A parameter whose annotation is not a generic-struct mention is unchanged.

## Done when

Add `test_span_parameter_annotation_is_materialized` to `test_gimple.py`: compile a small generic function
with a `Span[T, origin]` parameter instantiated as above, and assert the generated C contains no weak
`Span_as_ref` stub. Then run:

    python3 -m pytest test_gimple.py -k test_span_parameter_annotation_is_materialized -q

It must fail before the change and pass after. (Parts 1-4 must be landed first, or this test fails for their
reason, not this one.)
