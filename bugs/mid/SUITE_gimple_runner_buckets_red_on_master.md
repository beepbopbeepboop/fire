# SUITE: gimple-generators/gimple buckets red on master (pre-existing, not a merge regression)

## What I ran (2026-11-04, in work-4816, branch work/fix-merge-fix-merge-bug-plan-summarize-stats-step2)

While verifying the merge of master@d8d31af66 into the summarize-stats step2
fix-merge branch, I ran the narrow suites covering the changed codegen files,
each wrapped in `python3 tools/memslot.py --gb 8 --label <x> --`:

    python3 test_gimple_generator_runner.py        # 413 passed, 37 failed
    python3 test_gimple.py                          # 418 passed, 12 failed

## What I saw

To prove the failures are NOT caused by the merge, I extracted a pristine
`git archive d8d31af66` (master at merge time) to a scratch dir, swapped in
ONLY the repaired `test_gimple_generator_runner.py` (see below), and reran
both suites against the pure-master sources. The failure sets are
**byte-identical** (compared sorted test-name lists):

`test_gimple_generator_runner.py` — 37 failures, clusters:
- `gcc -fgimple compile of .c failed ... In function '_mojo_register_classes'`
  (generator_send_forwarded_to_stackswitch_sub_from_cpp_outer,
  flag_instance_iter_via_iter_member_alias, yield_from_cls_generator_method_delegation,
  classmethod_generator_yield_from_staticmethod_generator, cls_class_attr_dict_get_yield,
  cls_classmethod_call_in_generator, inherited_classmethod_generator_dispatches_per_class,
  generator_method_of_function_nested_class_yields_str_none_tuples,
  generator_classmethod_reads_class_attributes_incl_posthoc,
  generator_classmethod_reads_runtime_class_attributes,
  generator_yield_from_sorted_generator_call_with_attr_key, generator_calls_property_getter_result)
- `g++ compile of .cpp failed` (cpp_coroutine_starargs_lambda_value,
  cpp_coroutine_kwargs_lambda_value, cpp_coroutine_starargs_kwargs_lambda_value,
  cpp_coroutine_starargs_lambda_bool_arg, cpp_coroutine_starargs_lambda_via_map,
  cpp_coroutine_starargs_lambda_via_filter, cpp_coroutine_starargs_lambda_rebound_across_branches,
  cpp_coroutine_unpack_own_starargs_param, generator_os_fwalk_fd_relative_walk)
- `expected a refusal, but it compiled` (cpp_coroutine_starargs_lambda_str_arg_refused,
  cpp_coroutine_starargs_lambda_double_arg_refused, cpp_coroutine_kwargs_lambda_str_value_refused,
  cpp_coroutine_kwargs_only_local_positional_call_refused,
  cpp_coroutine_starargs_only_local_kwarg_call_refused, cpp_coroutine_unpack_boxed_source_refused)
- empty compiled output (star_args_coroutine_await_packs, star_args_async_method_aexit_shape,
  star_args_async_generator_for_packs, async_for_over_nonparking_await)
- `'utf-8' codec can't decode byte 0xbb ...` exception-message output corruption
  (generator_next_method_exception_after_yield, generator_next_method_exception_before_yield,
  generator_raise_propagates_to_caller, generator_yield_from_delegate_raises_propagates,
  generator_reraise_propagates_to_caller)
- wrong values (received_or_str_operand_cpp: `\x01z` vs `z`;
  generator_closing_a_tagged_dir_iterator_then_list: pointer words printed instead of names)

`test_gimple.py` — 12 failures: a_character_is_an_immortal_table_entry_not_a_slice,
bytes_subclass_method_override_wins, bytes_subclass_payload_and_inherited_ops,
comprehension_target_shadowing_a_struct_local_gets_its_own,
every_ast_mutation_site_invalidates_the_walk_memo, for_over_str,
func_state_snapshot_covers_reset_func,
generator_global_container_tuple_target_compiles_via_cpp_path,
generator_method_self_field_compiles_via_cpp_path,
generator_method_try_except_compiles_via_cpp_path,
no_compiler_module_defines_a_function_twice,
two_modules_one_same_named_function_keep_their_own_return_types

## What I expected

Both buckets green on master (they are registered gate jobs: `gimplegenerators`
and `gimple`, both `cache=True`).

## Why I believe this is pre-existing and not from the summarize-stats merge

1. Identical failure sets on pure master@d8d31af66 sources.
2. The failures cluster in areas the summarize-stats step2 branch never
   touches (starargs/variadic lambdas, classmethod/class-attr registration,
   bytes subclasses, dir-iterator tagging).

Related pre-existing defect repaired in the merge commit 9d224b256: master's
`test_gimple_generator_runner.py` did not PARSE (unterminated string literal
at line 2112). A foreign-callable-table merge had left a duplicated dead
module-level source fragment (lines 1173-1224 of the then-master file, no
test calls in it) whose stray `"""` quotes shifted the token stream and
swallowed ~190 lines of real code; deleting the fragment restored parsing.
The intact rewritten `_regression_read_table_callable_reader` test
(`test_generator_matches_cpython` — the flipped, current intent) is untouched.

## Exact next step

On a current-master checkout, rerun:

    python3 test_gimple_generator_runner.py   # expect 0 failures
    python3 test_gimple.py                    # expect 0 failures

Bisect per cluster: the `gcc -fgimple ... _mojo_register_classes` cluster
smells like the recent enum-runtime-class integrations (class registration
emission); the starargs-lambda `g++ compile failed` cluster like the
variadic-lambda work; the `expected a refusal, but it compiled` cluster is
a gate that silently opened.

## Status (2026-11-05, hard worker)

Moved to bugs/hard: the orchestrator made 34 no-progress attempts on this doc
because a pending reclass was starved by continuations (fixed in 061dc9410,
`tools/swarm.py` + `test_swarm_feed.py`).

Measured on master 6d11db6af, `test_gimple_runner.py`: 21 failures. The
self-host work (89df5bea3..c1d8466fc) fixed `multi_item_with_unwinds_in_reverse`
and introduced none. Failures present on master 821c12dfd before that work and
still open:
- `boxed_mut_local_escapes_is_kept` / `_is_flat` / `held_by_a_returned_inner`:
  "unresolved callee 'make_counter(...)'" (a function returning a nested def
  that mutates a `nonlocal`; the interpreter runs it fine).
- `bytes_subclass_shape` / `_method_override` / `_join`: gcc error, `Extra___init__`.
- `none_store_does_not_mark_str_local_as_int`: `callee in known` prints False
  (a str joined with None at an if/else is treated as a word).
- plus the 15 older ones (list_slice_mixed, for_over_a_call_through_a_function_value,
  check_all_idiom, match_or_pattern, str_encode_errors..., char_scan..., generator
  context managers x2, char_concat..., runtime_string_tuple_key..., str_window...,
  struct_mixed_int_float_formats, struct_class_attribute_handle_format_known,
  nested_class_var_attr_from_str_param).
Next step: take the three families above, each reproducible with a one-file
program through `T.compile_mojo_to_gimple_exe`.

Co-owned by: no one (claim released).
