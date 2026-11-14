# GPU offload validation modular - part 3: device-passable closure argument validation

Parent: `bugs/hard/GPU_offload_validation_modular.md` (SPLIT). The part-1
triage matrix is the `## Triage (part 1)` section of the parent doc.

## Scope

Cover enqueue-time/device-passable closure argument validation cases:

- `enqueue_function_device_passable_closure_arg_error.mojo`
- `enqueue_function_device_passable_closure_arg_layout_error.mojo`

Source intent read from Modular:
- `.../compile_offload/max_license/enqueue_function_device_passable_closure_arg_error.mojo`
- `.../compile_offload/max_license/enqueue_function_device_passable_closure_arg_layout_error.mojo`

## Contract

Both cases use `max.gpu.host.DeviceContext`: `ctx.compile_function[kernel]()` returns a compiled kernel object whose declared argument signature is fixed by the kernel instantiation, and `ctx.enqueue_function(compiled_kernel, closure_arg, grid_dim=..., block_dim=...)` enqueues with runtime argument validation (Modular: `not %mojo-build --target-accelerator="nvidia:sm_90a"` + FileCheck for a comptime `constraint failed` diagnostic).

1. **Type/passability mismatch** (`enqueue_function_device_passable_closure_arg_error.mojo`): kernel is instantiated as `apply_closure[type_of(expected_capture)]` where `expected_capture` captures `Int32(42)`. Enqueue passes `incompatible_capture` whose capture has a different device-encodable closure type (`SIMD[.int32, 4]`). Required diagnostic: argument `#0` of the passed closure type is not encodable as the declared function argument closure type, naming both closure types (Modular check: `constraint failed: argument #0 of type '{{.*}}incompatible_capture{{.*}}' is not encodable as the declared function argument type '{{.*}}expected_capture{{.*}}'`).
2. **Device layout/size mismatch** (`enqueue_function_device_passable_closure_arg_layout_error.mojo`): kernel reads a closure argument in its host layout, but enqueue writes the closure's `device_type` encoding. When a capture's device layout is smaller than its host layout (custom `DevicePassable` where `HostString.device_type == SIMD[.int32, 4]` but host layout includes `host_padding`, so encoded size 16 bytes vs declared argument 32 bytes), launch validation must reject to prevent the kernel reading past encoded bytes. Required diagnostic: argument `#0` encodes to 16 bytes but declared function argument type is 32 bytes, with hint `If the argument's host bytes are already valid on the device, pass it via \`host_args=\` to skip encoding`.

Determinism/user-facing requirement: rejection must be a clear diagnostic/constraint failure for the invalid input shape (no internal crash/traceback).

## Hook points

Where validation would have to live in this compiler (current state):

- **Host API / compiled-kernel handle (missing parity):** Modular-style flow is `compile_function[...]() -> compiled kernel` carrying declared parameter/device-passable metadata, then `enqueue_function(compiled_kernel, *runtime_args, ...)`. In this tree, the interpreter GPU stub is `_MojoDeviceContext` in `myinterpreter.py` (exposed as `DeviceContext`) with `enqueue_function` implemented as a subscript accessor `_MojoEnqueueFunctionAccessor` → `_MojoEnqueueFunctionCall` that takes `[kernel]` and runs the kernel serially on CPU; there is no `compile_function` method and no compiled-kernel object/signature carrier. `fire_compiler.py` defines a stub `class DeviceContext` with `compile_function`/`enqueue_function` as TODO placeholders only.
- **Device-passable/encoding model (missing):** `DevicePassable`, `device_type`, `DeviceTypeEncoder`, and `_to_device_type` are not implemented in this tree's compiler/runtime stubs (searched: no `DevicePassable` definitions outside docs/bug logs; `device_type` references are unrelated GPU-def metadata in `fe_reader.py`/test results). Without this, "encodable as declared arg type" and "encoded byte size vs declared layout size" cannot be computed.
- **Kernel enqueue validation hook (needed):** would belong at the host enqueue boundary before dispatch: in interpreter, on the path that accepts a compiled-kernel handle + runtime args (or an equivalent API form) to compare each runtime closure arg's device-passable type/encoded layout against the compiled kernel's declared argument type/layout and raise a deterministic, user-facing diagnostic. In compiled/device-offload codegen, `enqueue_function`/`compile_function` are treated as kernel registrars in `mojo/backend_gimple/device_select.py` for region selection; argument-level device-passable validation is not present there and would require host-side runtime/ABI metadata not currently modeled.
- **Closure capture typing (needed):** closures/captures as device-passable arguments with comparable type identity and layout (`type_of(expected_capture)` vs `incompatible_capture`, custom struct `DevicePassable`) require closure value/type representation that preserves capture layout and device encoding; this is beyond current simulated CPU kernel launch.

## Blocker

**BLOCKED on missing GPU host runtime / device-passable infrastructure (not representable in this compiler today without a full runtime/API model).** Concrete prerequisites:

- MAX-style host API parity for this flow: `max.gpu.host.DeviceContext` with `compile_function` producing a compiled-kernel handle that retains declared argument type/layout/encoding metadata, and `enqueue_function` accepting `(compiled_kernel, *args, grid_dim=..., block_dim=...)`.
- `DevicePassable` trait semantics, `device_type`, `DeviceTypeEncoder`, and per-type/device-target encoding/layout computation (including custom `_to_device_type`) so "encodable as" and encoded byte size can be validated.
- Closure-as-argument type identity and capture/device layout representation sufficient to compare passed closure args against the kernel's declared closure parameter type at enqueue time.
- A deterministic diagnostic surface for comptime/launch-constraint failures in the offload build/enqueue path used by these Modular tests.

Part 1 triage observation (this worktree): running the external Modular sources with `python3 tools/memslot.py --gb 8 --label t4/t5 -- python3 fire.py <case>` fails at import with `ModuleNotFoundError: No module named 'max'` (peaks 0.0–0.1 GB), so the exact Modular tests cannot be reproduced here without the `max` package/runtime.

**Disposition:** both cases are **BLOCKED** (require GPU backend/runtime + MAX host API + device-passable encoding). No compiler/runtime validation was implementable without those hooks; this change isolates and documents the runtime-dependent portion and the exact insertion points.

## Narrow verification

- `python3 tools/memslot.py --gb 8 --label p3test -- python3 -m unittest test_gpu_offload_validation_part3.py -v` — focused regression asserting this doc records contract, hook points, blocker, and disposition for both cases (passes after this change).
- (pre-fix baseline for that test: `AssertionError: '## Contract' not found ...` — the doc lacked the required analysis/disposition sections.)

## Done when

`python3 tools/memslot.py --gb 8 --label p3test -- python3 -m unittest test_gpu_offload_validation_part3.py -v` passes and this doc disposition remains accurate for both cases.

## Status

Blocked (2026-11-13): contract and required hook points identified for both cases; implementation of the enqueue-time device-passable closure argument type/layout validation is runtime-dependent on MAX `DeviceContext`/`compile_function`+compiled-kernel metadata and `DevicePassable` device encoding/layout support not present in this tree. No compiler/runtime behavior changed.
