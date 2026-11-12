# GPU offload validation modular - part 3: device-passable closure argument validation

Parent: `bugs/hard/GPU_offload_validation_modular.md` (SPLIT). Depends on triage in `bugs/mid/GPU_offload_validation_modular-part1.md`.

## Scope

Cover enqueue-time/device-passable closure argument validation cases:

- `enqueue_function_device_passable_closure_arg_error.mojo`
- `enqueue_function_device_passable_closure_arg_layout_error.mojo`

## Work

1. Determine the intended validation contract for device-passable closure arguments (type/passability and layout) from part 1 findings/Modular semantics.
2. Identify where closure capture/argument lowering and kernel enqueue validation would occur in this compiler (or where a diagnostic hook must be added).
3. Implement validation that rejects invalid device-passable closure arguments with clear diagnostics when representable without a full GPU runtime, or isolate and document the GPU-runtime-dependent portion.
4. Add focused tests for the achievable validation behavior.

## Acceptance check

- Each of the 2 cases has a focused test showing correct rejection/diagnostic for the invalid condition, or a precise blocker documented with the required runtime/backend hook.
- Any implemented check reports a deterministic, user-facing diagnostic (no internal crash/traceback) for the invalid input shape.
- Narrow verification command(s) for the added/updated tests are recorded.

## Status

Open.
