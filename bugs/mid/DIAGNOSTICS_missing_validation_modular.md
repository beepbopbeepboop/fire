# DIAGNOSTICS: missing validation/error reporting for modular test cases

## Symptom
Modular test files expect compile-time errors/diagnostics that our compiler does not produce (it compiles them successfully). These are cases where modular's compiler rejects invalid code but ours accepts it.

## Categories

### A. Missing validation (real bugs — should catch these) ~25 files
- Comptime asserts: comptime_assert.mojo, comptime_assert_tstring.mojo
- Type/conformance: invalid_downcast_error.mojo, struct_conditional_trait_conformance_errors.mojo, defaulted_trait_method_bad_conformance.mojo, never_conforming_no_synthesis.mojo, not_conformance.mojo
- Constraints: autoparam_dependency_errors.mojo, failed_binding_deferrals.mojo, tuple_contains_type_mismatch_error.mojo, tuple_first_of_error.mojo, where_message.mojo, moco_4400_no_crash_on_bind_parameter.mojo
- Imports: import_error_location.mojo, import_fn_scope_ambiguous.mojo, import_qualified_member_no_leak.mojo, import_mojoc_conformance_error.mojo, import_mojoc_implicit_default_param.mojo, import_dual_mount_mojoc.mojo, mojo_import_case_sensitive_error.mojo, docstring_self_import.mojo
- Error tolerance/recovery: error_tolerance.mojo, elaboration_error_recursion1.mojo, error_handling.mojo, enum_exhaustive_errors.mojo
- Other: align_decorator_parametric_error.mojo, assert_failure_message.mojo, identifier_source_range.mojo, variadic_kwargs.mojo, mojo_package_moco_773.mojo

### B. Diagnostic formatting (compare our output to theirs) ~10 files
- diagnostics_in_missing_locs.mojo, diagnostics_in_missing_locs_imports.mojo, diagnostic_format.mojo, kgen_lsp_check_parse_error.mojo, invalid_downcast_error.mojo (diagnostic part)
- See bugs/mid/DIAGNOSTICS_formatting_modular.md

### C. GPU/offload (we target GPU — see bugs/hard/GPU_offload_validation_modular.md)
- compile_offload_*, enqueue_function_device_passable_closure_arg_*, sanitize_address*.mojo, op_with_unsupported_type_error.mojo, end_to_end_thunk_with_direct_compile.mojo, simd_bad_size_lowering.mojo

### D. Modular-specific/CLI (not our bugs)
- mojo_doc_*, mojo_build_*, mojo_run_*, mojo_package_*, missing_option_value.mojo, mojo_lldb_version.mojo, literals.mojo, explicit_destroy.mojo, indirect_call.mojo, raise_and_try.mojo, layout_copy_error.mojo, inline_mlir_op_fstring_elaborate_errors.mojo, inline_decorator_errors.mojo, debuginfo_raise_hook.mojo

## Full list
See build/checkfail_candidates.json (61 error-like cases).

## Notes
- Our compiler currently produces no errors for these; it compiles them successfully.
- Need to add validation for category A (real bugs).
- Category B: compare our diagnostic output to modular's; file individual bugs if ours is worse.
- Category C: we target GPU offloading, so these validations are relevant (see GPU bug report).
- Category D: modular-specific features/CLI, likely out of scope.
