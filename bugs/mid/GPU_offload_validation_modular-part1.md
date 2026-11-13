# GPU offload validation modular - part 1: triage and classification

Parent: `bugs/hard/GPU_offload_validation_modular.md` (SPLIT).

## Scope

Triage every affected Modular test case listed in the parent doc and classify it so follow-up work can be scheduled without re-discovering constraints:

- `compile_offload_unbound_param_error.mojo`
- `compile_offload_missing_symbol_error.mojo`
- `compile_offload_bundle_order.mojo`
- `enqueue_function_device_passable_closure_arg_error.mojo`
- `enqueue_function_device_passable_closure_arg_layout_error.mojo`
- `sanitize_address.mojo`
- `sanitize_address_inlined.mojo`
- `op_with_unsupported_type_error.mojo`
- `end_to_end_thunk_with_direct_compile.mojo`
- `simd_bad_size_lowering.mojo`

## Work

For each file, determine and record:
1. **What it tests** (compile-time diagnostic, runtime behavior, lowering/codegen constraint, or end-to-end GPU execution).
2. **Current compiler behavior** in this tree (parse/typecheck/compile/run outcome or refusal), with the exact command used.
3. **Classification**: `feasible-without-gpu-backend`, `requires-gpu-backend`, or `modular-target-specific` (NVIDIA/AMDGPU/Metal-specific), with rationale.
4. **Dependency/owner area** (parser/diagnostics, codegen, runtime, GPU backend) and smallest next implementation step.

Capture findings in this doc (or a linked note committed alongside it) as a per-case matrix/table.

## Acceptance check

- The doc contains an entry for all 10 listed files with the four fields above filled in.
- Each entry includes at least one concrete command/output observation from this worktree (or an explicit note if the test source is not present locally, stating where it was looked for).
- Every case is assigned to exactly one of the follow-up parts (part2-part4) or explicitly marked out-of-scope as `modular-target-specific` with justification.
- No compiler/runtime behavior changes are made as part of this triage; this part is analysis/documentation only.

## Status

Open.
