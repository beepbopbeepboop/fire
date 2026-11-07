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
EOF