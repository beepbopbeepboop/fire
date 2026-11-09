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
- See bugs/hard/DIAGNOSTICS_formatting_modular.md

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

## Status (merged from work/bug-mid-diagnostics-missing-validation-m branches)
- **Landed (partial):** `comptime assert` statements with provably-false
  conditions now fail compilation with a diagnostic
  (`comptime assertion failed: ...`) in the gimple backend, instead of being
  silently accepted/emitted as a runtime trap. `eval_const_bool`/`_state`
  determines provable falsehood; when a `comptime if` degrades to runtime
  (conditions unknown) the assert is treated as non-fatal to avoid false
  positives in generic fallback branches (e.g. DType-category `else` guards
  whose conditions our comptime evaluator cannot yet resolve).
  Regression: `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up):** comptime diagnostic messages are now evaluated, not
  lowered to compiler temp names. `mojo/middle/comptime.py` folds
  `String(int/bool)` and string `+` concatenation at compile time, so messages
  like `"got " + String(x)` with bound param values produce the human-readable
  message. Regression added to `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up, branch 4715):** compile-time diagnostics for the
  `constrained[...]()` builtin form (and paren form) in the gimple backend
  (`mojo/backend_gimple/emit_calls.py`). A provably-false condition fails with
  `constraint failed: <message>`. Unknown conditions treated conservatively.
  Also fixed a duplicate runtime-assert lowering in
  `mojo/backend_gimple/emit_stmts.py`. Regression:
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6289):** `mojo/middle/comptime.py` folds DType
  values (`DType.int32`) and DType predicate methods (`is_integral`,
  `is_floating_point`, `is_signed`, `is_unsigned`, `is_numeric`, `is_bool`,
  `is_index`, `is_float8`, `is_half_float`) during compile-time constant
  evaluation. Regression: `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 7836):** `mojo/backend_gimple/emit_resolve.py`
  re-raises compile-time diagnostics (`constraint failed` / `comptime assertion
  failed` RuntimeErrors) raised while compiling an elaborated generic struct
  instantiation (previously swallowed). Regression:
  `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 794):** `fire_compiler.py` tokenizer fix: a line
  ending with a string literal no longer suppresses DEDENTs across blank lines
  when the next significant line is not a string continuation. Regression:
  `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 3407):** comptime evaluation of interpolated
  string literals (`t"..."` / `f"..."`) in diagnostic messages
  (`mojo/middle/comptime.py`). Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 4840):** short-circuit boolean folding for
  `and`/`or` in compile-time constant evaluation (`mojo/middle/comptime.py`).
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6439):** comptime-for unrolling binds
  `range(...)`/`product(range(...))` induction targets in `gen._comptime_vals`
  (`mojo/backend_gimple/emit_funcs.py`). Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 8406):** comptime-for unrolling over constant
  `ListExpr`/`TupleExpr` iterables binds loop variables in `gen._comptime_vals`.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 223):** comptime-for unrolling over constant
  list/tuple iterables with tuple-unpacking targets. Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 1584):** comptime-for unrolling over non-literal
  iterables that resolve via `gen._eval_const` to a constant list/tuple.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 3096):** `eval_const_int` resolves `IdentExpr`
  comptime bindings, enabling `range(...)` bounds that are comptime variables.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 4910):** comptime folding of `len()` for
  comptime-known `list`/`tuple`/`str` in `eval_const`, `_const_foldable`,
  `eval_const_int`. Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6270):** comptime folding of
  `SubscriptExpr`/`SliceExpr` over comptime-known `list`/`tuple`/`str`;
  comptime-for unroller treats comptime-known `str` iterables as unrollable.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 7781):** comptime folding of `DictExpr` literals
  and `len()`/subscript on comptime-known `dict` values. Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Still open (large):** remainder of the umbrella — comptime-assert/
  `constrained` cases with incomplete condition evaluation (DType predicates on
  comptime params in generic instantiations bypassing elaboration; reflection-
  driven messages like `StaticString(_get_kgen_string[...])`), generic/trait-
  reflection conditions, non-gimple/formal backends, comptime-for shapes beyond
  the gimple unroller (DType/variadic iterables, computed/non-foldable
  iterables, comptime-known `dict` iteration, local `alias` bindings not always
  visible), type/trait conformance diagnostics, import errors, and other
  categories above. `build/checkfail_candidates.json` not present in this
  worktree; re-run `tools/collect_checkfail.py` against the modular suite to
  refresh/prioritize.
