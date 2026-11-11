# GPU offload validation modular - part 4: sanitize/lowering/end-to-end GPU cases

Parent: `bugs/hard/GPU_offload_validation_modular.md` (SPLIT). Depends on triage in `bugs/mid/GPU_offload_validation_modular-part1.md`.

## Scope

Cover the remaining cases that are likely to require GPU-capable lowering/runtime or target-specific support:

- `sanitize_address.mojo`
- `sanitize_address_inlined.mojo`
- `op_with_unsupported_type_error.mojo`
- `end_to_end_thunk_with_direct_compile.mojo`
- `simd_bad_size_lowering.mojo`

## Work

1. Use part 1 classification to separate cases needing only compiler-side validation/lowering guards (e.g. unsupported type or bad SIMD size diagnostics/lowering rules) from cases needing GPU backend/runtime/thunk execution.
2. For compiler-side-feasible items, implement the smallest correct validation or lowering behavior and add focused tests.
3. For GPU-backend-dependent items, define the required backend/runtime capabilities, target constraints (NVIDIA/AMDGPU/Metal as applicable), and a concrete incremental implementation plan; do not claim support without executable validation.
4. Keep Modular-target-specific requirements clearly labeled so they are not conflated with generic compiler bugs.

## Acceptance check

- All 5 cases are explicitly dispositioned: implemented with a focused passing test, or documented as blocked on named GPU backend/runtime capabilities with an actionable next step.
- Any implemented diagnostic/lowering behavior for `op_with_unsupported_type_error` or `simd_bad_size_lowering` is covered by a narrow test demonstrating the expected failure/success condition.
- GPU-execution-dependent cases (`sanitize_address*`, thunk/end-to-end paths as applicable) include a clear prerequisite checklist (target, runtime, codegen path) required before implementation can proceed.

## Status

Open.
