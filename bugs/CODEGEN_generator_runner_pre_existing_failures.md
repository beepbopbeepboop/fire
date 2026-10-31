# CODEGEN_generator_runner_pre_existing_failures

`python3 test_gimple_generator_runner.py` at HEAD (1292104b7) reports
`297 passed, 8 failed`. The same 8 fail with and without the
cross-module generator-global change (`CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure`,
2026-10-30c), so they are not caused by it.

## Status (2026-10-30)

The 8 failing cases (exact names from the runner):

- `generator_explicit_call_arguments_still_resolve` — gcc -fgimple error
- `generator_keyword_only_parameter_is_not_a_hole_from_a_positional_spread` — gcc -fgimple error
- `param_generator_unannotated_string_via_cross_call` — gcc -fgimple error
- `generator_yields_string_param_identifier` — gcc -fgimple error
  (`prog.c:2:29: passing argument 2 of '__mojo_coro_yield_p' makes pointer from integer without a cast`)
- `generator_callsite_string_through_caller_param` — gcc -fgimple error
- `gen_tuple_slot_list_valued` — the runner's own decode of program stdout: `'utf-8' codec can't decode byte 0x90`
- `genexp_over_annotated_param_with_capture` — "generator expression could not be compiled ... neither the stack-switch nor the C++20 coroutine path supports this shape"
- `genexp_over_annotated_param_with_condition` — same refusal (see `CODEGEN_genexp_over_annotated_param_refused.md`)

**Next step:** re-run the file, read each case's full gcc output in the
runner log (`grep -A20 '^FAIL  <name>'`), and group by the first error. The
`__mojo_coro_yield_p` int->pointer cast is the most common root (the
string-yielding generator passes an int64_t boxed word to a `void *` parameter).
The `utf-8` decode case is probably the runner reading a binary-ish stdout; check
that before treating it as a codegen bug.
