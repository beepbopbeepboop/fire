# DIAGNOSTICS: missing validation/error reporting for modular test cases

## Symptom
63 modular test files expect compile-time errors/diagnostics that our compiler does not produce (it compiles them successfully). These are cases where modular's compiler rejects invalid code but ours accepts it.

## Affected files
(See build/checkfail_candidates.json for full list; error-like cases.)

Key categories:
- Comptime asserts: comptime_assert.mojo, comptime_assert_tstring.mojo
- Type checking: invalid_downcast_error.mojo, struct_conditional_trait_conformance_errors.mojo, defaulted_trait_method_bad_conformance.mojo, never_conforming_no_synthesis.mojo, not_conformance.mojo
- Constraint checking: autoparam_dependency_errors.mojo, failed_binding_deferrals.mojo, tuple_contains_type_mismatch_error.mojo, tuple_first_of_error.mojo
- Import errors: import_error_location.mojo, import_fn_scope_ambiguous.mojo, import_qualified_member_no_leak.mojo, import_mojoc_conformance_error.mojo, import_mojoc_implicit_default_param.mojo, import_dual_mount_mojoc.mojo, mojo_import_case_sensitive_error.mojo, docstring_self_import.mojo
- Diagnostics: diagnostics_in_missing_locs.mojo, diagnostics_in_missing_locs_imports.mojo, identifier_source_range.mojo, error_tolerance.mojo, where_message.mojo
- Offload: compile_offload_*, enqueue_function_device_passable_closure_arg_*
- kgen/MLIR: indirect_call.mojo, literals.mojo, explicit_destroy.mojo, raise_and_try.mojo
- Other: align_decorator_parametric_error.mojo, assert_failure_message.mojo, comptime_assert, enum_exhaustive_errors.mojo, error_handling.mojo, elaboration_error_recursion1.mojo, kgen_lsp_check_parse_error.mojo, layout_copy_error.mojo, op_with_unsupported_type_error.mojo, simd_bad_size_lowering.mojo, end_to_end_thunk_with_direct_compile.mojo, sanitize_address*.mojo, variadic_kwargs.mojo, moco_4400_no_crash_on_bind_parameter.mojo, mojo_package_moco_773.mojo, exec_import_dir_staged_precompiled.mojo, indirect_call.mojo

## Notes
- These are all cases where modular rejects invalid code. Our compiler lacks the corresponding validation.
- Full list with expected error messages in build/checkfail_candidates.json.
- This is a large body of work; prioritize based on user needs.

## Status (2026-11-06, branch work/bug-mid-diagnostics-missing-validation-m)
- **Landed (partial):** `comptime assert` statements with provably-false
  conditions now fail compilation with a diagnostic
  (`comptime assertion failed: ...`) in the gimple backend, instead of being
  silently accepted/emitted as a runtime trap. `eval_const_bool`/`_state`
  determines provable falsehood; when a `comptime if` degrades to runtime
  (conditions unknown) the assert is treated as non-fatal to avoid false
  positives in generic fallback branches (e.g. DType-category `else` guards
  whose conditions our comptime evaluator cannot yet resolve).
  Regression: `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up, earlier worker):** comptime diagnostic messages are now
  evaluated, not lowered to compiler temp names. `mojo/middle/comptime.py`
  folds `String(int/bool)` and string `+` concatenation at compile time, so
  messages like `"got " + String(x)` with bound param values (e.g. `x = -2`
  in a monomorphized instantiation) produce the human-readable message.
  Verified against modular `mojo-integration/comptime_assert.mojo`:
  `use_positive_int[-2]()` is rejected with
  `comptime assertion failed: expected positive number, got -2` (contains the
  `# CHECK` text). Also fixed `test_implicit_string_concat.py` to run in the
  current worktree (it hardcoded another worktree's cwd). Regression added to
  `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-4715`):** compile-time
  diagnostics for the `constrained[...]()` builtin form (and paren form) in
  the gimple backend (`mojo/backend_gimple/emit_calls.py`). A provably-false
  condition now fails compilation with `constraint failed: <message>`,
  mirroring the comptime-assert diagnostic path and using the same comptime
  evaluator/message folding. Unknown conditions are treated conservatively
  (no false diagnostic). This addresses a root cause for many modular
  validation cases that use `constrained` rather than `comptime assert`.
  Also fixed a duplicate runtime-assert lowering in
  `mojo/backend_gimple/emit_stmts.py` (regular `assert` emitted twice).
  Regression: `test_constrained_diagnostic.py`.
- **Still open (large):** the rest of this umbrella — comptime-assert cases
  where condition evaluation is incomplete (e.g. `DType.*.is_integral()` in
  instantiated params, `t"..."`/reflection-driven messages), `constrained`
  cases whose conditions/messages cannot yet be folded (generics, trait
  reflection, `StaticString(_get_kgen_string[...])`), type/trait
  conformance diagnostics, import errors, and the other categories listed
  above. `build/checkfail_candidates.json` is not present in this worktree;
  re-run `tools/collect_checkfail.py` against the modular suite to refresh
  the candidate list and prioritize.
