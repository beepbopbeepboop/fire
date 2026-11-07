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
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-6289`):** root-cause fix in
  `mojo/middle/comptime.py` to fold DType values (`DType.int32`) and DType
  predicate methods (`is_integral`, `is_floating_point`, `is_signed`,
  `is_unsigned`, `is_numeric`, `is_bool`, `is_index`, `is_float8`,
  `is_half_float`) during compile-time constant evaluation. Provably-false
  `comptime assert` / `constrained` conditions that use DType predicates now
  produce compile-time diagnostics (direct cases). Unknown/unresolvable DType
  Regression: `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-7836`):** root-cause fix in
  `mojo/backend_gimple/emit_resolve.py`: compile-time diagnostics
  (`constraint failed` / `comptime assertion failed` RuntimeErrors) raised
  while compiling an elaborated generic struct instantiation were being
  swallowed by `_ensure_generic_struct` and the inferred struct elaboration
  path (they fell back as if elaboration "couldn't handle" the shape), so
  provably-false `constrained`/`comptime assert` conditions inside
  instantiated generic struct bodies (e.g. methods) were silently accepted.
  These diagnostics are now re-raised so the invalid instantiation fails
  compilation. For the `.o`/monomorphize elaboration route, type-param
  substitution already makes DType predicates like `dtype.is_integral()`
  evaluable in the instantiated body. Regression:
  `test_comptime_dtype_diagnostic.py`
  (`test_generic_struct_constrained_dtype_param_false`,
  `test_generic_struct_comptime_assert_dtype_param_false`,
  `test_generic_struct_constrained_dtype_param_true`).
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-794`):** root-cause fix in
  `fire_compiler.py` tokenizer: a line ending with a string literal set
  `prev_ended_string` (for implicit multi-line string concatenation) but never
  cleared it across a blank/comment-only line and did not verify that the next
  significant line actually begins a string continuation. When a `comptime
  assert`/`assert` (or any statement) ended with a string message as the
  last/only statement in an indented block and was followed by a blank line
  and a dedented definition, the required DEDENT tokens were suppressed and the
  parser swallowed the following top-level code (e.g. `fn main`). This
  prevented elaboration-time diagnostics from firing for instantiated generic
  structs in that shape (e.g. a sole `comptime assert dtype.is_floating_point(),
  "..."` in a method of a locally-instantiated generic struct compiled with
  `do_imports=True`). Regression:
  `test_comptime_dtype_diagnostic.py`
  (`test_generic_struct_comptime_assert_dtype_param_only_stmt`).
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-3407`):** comptime evaluation
  of interpolated string literals (`t"..."` / `f"..."`) in compile-time
  diagnostic messages (`mojo/middle/comptime.py`). `eval_const` now formats
  interpolations by parsing f/t-string parts and folding each `{expr}` with the
  comptime bindings, so provably-false `comptime assert` / `constrained`
  diagnostics report evaluated messages (e.g.
  `t"expected positive number, got {x}"` with `x = -3` ->
  `expected positive number, got -3`), including instantiated generic params.
  Verified against the modular integration shape
  `comptime_assert_tstring.mojo` (`use_positive_int_tstring[-3]()`). Reflection-
  driven messages (`StaticString(_get_kgen_string[...])`) remain open.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-4840`):** root-cause fix in
  `mojo/middle/comptime.py` for short-circuit boolean folding in compile-time
  constant evaluation. `and`/`or` in `eval_const`, `eval_const_int`,
  `eval_const_bool_state`/`_const_foldable` now apply short-circuit semantics,
  so a provably-false left operand of `and` (e.g. `False and <unknown>`) is
  diagnosed as provably false even when the right operand cannot be folded
  (generic/comptime-param dependent). This fixes missed `comptime assert` /
  `constrained` compile-time diagnostics for that shape. Regressions:
  `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, this worker, branch
  `work/bug-mid-diagnostics-missing-validation-m-6439`):** root-cause fix in
  `mojo/backend_gimple/emit_funcs.py` comptime-for unrolling: induction/target
  variables for unrolled `comptime for` over `range(...)` and
  `product(range(...), ...)` are now bound in `gen._comptime_vals` (saved/
  restored per iteration) while emitting the body. This makes the iteration
  values visible to compile-time constant evaluation, so provably-false
  `comptime assert` / `constrained` conditions that depend on the loop variable
  are diagnosed instead of being treated as non-foldable and silently accepted.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Still open (large):** the rest of this umbrella — comptime-assert/
  `constrained` cases where condition evaluation is incomplete (e.g.
  DType predicates on comptime params in generic struct instantiations that
  genuinely bypass elaboration and are compiled with unbound params through the
  template fallback, so param-dependent conditions degrade to unknown/non-fatal;
  reflection-driven messages such as `StaticString(_get_kgen_string[...])`),
  `constrained` cases whose conditions/messages cannot yet be folded (generics,
  trait reflection, `StaticString(_get_kgen_string[...])`), `comptime assert`/
  `constrained` in non-gimple/formal backends or in comptime-for shapes beyond
  the gimple unroller's bound forms, type/trait conformance diagnostics, import
  errors, and the other categories listed above.
  `build/checkfail_candidates.json` is not present in this worktree; re-run
  `tools/collect_checkfail.py` against the modular suite to refresh the
  candidate list and prioritize.
