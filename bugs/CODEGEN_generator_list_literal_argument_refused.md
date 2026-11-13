# CODEGEN: a generator call with a non-scalar list-literal argument is refused, but the test expects it compiled

Observed 2026-11-12 on `work/bug-codegen-nested-generator-method-incl` at HEAD 5950448db
(`python3 test_gimple_generator_runner.py`, 478 passed / 4 failed). Two of the four are this defect:

- `generator_heterogeneous_stack_param_rebound_from_pop`
- `generator_escaping_closure_drives_capturing_sibling_virtual_self`

Both fall back to interpreting the module from source with:

    Unsupported shape(s): g: a non-scalar element in a list-literal argument of a compiled-generator call is not supported in a coroutine body.

The refusal comes from `mojo/backend_gimple/cpp_core.py` (around line 2158), in the
list-literal lowering for a compiled-generator call: it admits only `StringLiteral`,
`IntLiteral` and `FloatLiteral` elements, and raises for any other element.

The runner tests are `test_generator_stdout` (`generator_heterogeneous_stack_param_rebound_from_pop`,
expects stdout) and `test_generator_matches_cpython` (`generator_escaping_closure_drives_capturing_sibling_virtual_self`,
expects CPython-equal output). Both expect the module to compile, so the refusal is a
failure of the test's expectation, not an accepted gap. The fix must either admit the
element shape or the test must be proven to need the refusal; that decision is for the owner.

## Exact next step

1. Print the list-literal elements in the two sources (`test_gimple_generator_runner.py`
   near lines 10685 and 11158) to see which element kind is non-scalar (a tuple or a
   class instance, not a literal).
2. Decide, with the owner, whether the non-scalar element should be lowered (the
   boxed-list path `_cpp_boxed_list_literal_expr` already handles
   `_cpp_is_struct_pointer_elem`; check if that covers these elements) or whether the
   test should assert the refusal.
3. Implement the chosen side, verify both tests singly, and delete this doc in that commit
   with `python3 tools/dangling_doc_refs.py --ratchet`.
