SPLIT: bugs/GPU_offload_validation_modular-part2, bugs/GPU_offload_validation_modular-part3 (part1 triage landed and its doc deleted 2026-11-13: the per-case matrix is below; part4 dispositioned 2026-11-13: `test_regress_gpu_offload_validation_modular_part4.py`)
# GPU: offload validation for modular test cases (category C)

## Symptom

Modular test files exercise GPU offload features (kernel launch, device passable
closures, sanitize address, SIMD lowering). Our compiler does not implement
these, so they fail or produce wrong code.

## Affected files
- compile_offload_unbound_param_error.mojo
- compile_offload_missing_symbol_error.mojo
- compile_offload_bundle_order.mojo
- enqueue_function_device_passable_closure_arg_error.mojo
- enqueue_function_device_passable_closure_arg_layout_error.mojo
- sanitize_address.mojo
- sanitize_address_inlined.mojo
- op_with_unsupported_type_error.mojo
- end_to_end_thunk_with_direct_compile.mojo
- simd_bad_size_lowering.mojo

## Notes
- We DO target GPU offloading and GPU computations, so these are relevant.
- There is no real device backend, but the interpreter is not empty: it
  auto-stubs unshimmed `std.*` modules through `_AutoStubNamespace`
  (`myinterpreter.py:4373`, used at `:4815`), so `std.compile.compile_info`
  binds the integer `0`; and it has a CPU-simulated
  `std.gpu.host.DeviceContext` (`_MojoDeviceContext`, `myinterpreter.py:3224`)
  with `enqueue_function`, `DeviceBuffer` and `GPUInfo.from_name`. What is
  missing is (a) the `max.gpu.*` spellings the Modular tests import (they fail
  with `unable to locate module 'max'`; only `std.*` is stubbed), (b) an
  elaboration/offload model that turns `compile_function`/`enqueue_function`
  into compile-time checks, and (c) the device compilation/emission path.
- The compiled path is a separate world from the interpreter: a guard added to
  `myinterpreter.py` does not validate a `fire.py <file>` build. Measure both.

## Triage (part 1, measured 2026-11-13 in this worktree)

Every observation below was taken from this worktree. `fire run FILE` is the
interpreter path (`python3 fire.py run FILE`); `fire FILE` is compile-then-run
with interpreter fallback. Each was wrapped:
`python3 tools/memslot.py --gb 8 --label <id> -- <command>`.

| Case | What it tests | Current behavior (this tree) | Classification | Owner + smallest next step | Follow-up |
|---|---|---|---|---|---|
| `compile_offload_unbound_param_error.mojo` | `not %mojo`: instantiating `param_fn[x, y]` as `param_fn[2]` must diagnose "failed to infer parameter 'y' …" (FileCheck). | `fire run` and `fire` both print `0` and exit 0 — no diagnostic. `compile_info` is an auto-stub `0`, so `compile_info[...]()` is a no-op. A probe without `compile_info` shows `param_fn[2]` binds `y=None`; calling it dies with `TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'` (`myinterpreter.py:7928`) — an internal traceback, not a user diagnostic. | `feasible-without-gpu-backend` (parameter-arity validation is elaboration-side; no device involved). | Elaboration/comptime + diagnostics. Validate parameter arity at bracket application (2 declared, 1 given) and emit the MissingParameter diagnostic; `std.compile.compile_info` has to exist for the case to reach a FileCheck-able message. | `part2` |
| `compile_offload_missing_symbol_error.mojo` | `not %mojo`: slicing a kernel instantiated with a runtime function pointer (`get_fn[False]()`) must report "cannot slice out exported symbol … scale…n=3", not assert. | `fire run` and `fire` both print `0`, exit 0; no diagnostic and no assertion (`compile_info` auto-stub as above). Source imports only `std.compile`, which resolves. | `feasible-without-gpu-backend` (export/symbol validation is front-end elaboration). | Elaboration/offload diagnostics. Implement `compile_info` and the exported-symbol check for a non-symbol callee value; the source's own `CHECK-NOT: Assertion` is already satisfied, the CHECK line is not. | `part2` |
| `compile_offload_bundle_order.mojo` | `not %mojo`: `compile_info[kern, emission_kind="llvm", target=A100.target]` must compile each kernel for NVIDIA, so the `comptime assert not is_nvidia_gpu()` inside each kernel fails and `constraint failed: <kern> is not supported on NVIDIA GPU` appears in mangled-name order (`alpha_kern, bb, middle_kern, yy, zebra_kern`). | `fire` fails in the compile phase: `driver error, interpreting instead: …: error: unable to locate module 'max'`, then `ModuleNotFoundError: No module named 'max'`, exit 1; `fire run` the same. `std.sys.info.is_nvidia_gpu()` is a shim returning False, so the comptime asserts pass whenever they are reached. | `modular-target-specific` (A100 target metadata + device compilation/bundling). | GPU backend + target model. Provide the A100 target descriptor (`max.gpu.host.info.A100.target`), make `is_nvidia_gpu()`/`CompilationTarget` reflect the requested device target, and bundle offload ops sorted by mangled kernel symbol. | out-of-scope as `modular-target-specific` |
| `enqueue_function_device_passable_closure_arg_error.mojo` | At build time (`%mojo-build --target-accelerator=nvidia:sm_90a`) enqueueing a closure whose capture has an incompatible device type must report `constraint failed: argument #0 … is not encodable as the declared function argument type …`. | Only `from max.gpu.host import DeviceContext` fails (`unable to locate module 'max'`, `ModuleNotFoundError`, exit 1). `std.builtin.device_passable` is also unshimmed (auto-stub). No closure-argument validation is ever reached. | `feasible-without-gpu-backend` for the validation itself: it is a host/elaboration argument-encoding check, and the interpreter already simulates `DeviceContext`/`enqueue_function` on the CPU. It needs the `max.gpu.*` name alias and a compile-time model of `compile_function`/`enqueue_function`, not a device. | GPU runtime shims + kernel argument validation. Alias `max.gpu.host` to the existing `std.gpu.host` shims, model `compile_function[kernel]` kernel signatures, and compare the closure capture's `device_type` encoding with the declared argument type. | `part3` |
| `enqueue_function_device_passable_closure_arg_layout_error.mojo` | Build-time enqueue check for a `DevicePassable` whose device encoding is smaller than its host layout: `constraint failed: … encodes to 16 bytes but … is 32 bytes`, plus the `host_args=` hint. | Only the `max` import failure (exit 1). No `DevicePassable`/`DeviceTypeEncoder` support and no layout check. | `feasible-without-gpu-backend` for the check (same reasoning as the case above; the encoding-size comparison is elaboration-side). | GPU runtime shims + layout validation. Model `DevicePassable` device-encoding size and compare it with the declared parameter layout during the enqueue check; emit the `host_args=` hint. | `part3` |
| `sanitize_address.mojo` | `%mojo-build -O0 --sanitize address`, then the binary must be stopped by ASAN with a heap-buffer-overflow report (`WRITE of size 8`, frame at `sanitize_address.mojo`). | `fire`: exit 245 with no output and no ASAN report. `fire run`: `NameError: … name 'alloc' is not defined` (`sanitize_address.mojo:27:13`), exit 1. The Modular source itself is marked `UNSUPPORTED: asan`. | `modular-target-specific` (sanitizer toolchain integration; Modular's own suite skips it unless ASAN is enabled). | Runtime/toolchain. Plumb `--sanitize address` through build/link/runtime, provide `alloc`, and produce/format the ASAN report — or record it as unsupported exactly as Modular does. | `part4` |
| `sanitize_address_inlined.mojo` | Same ASAN case at O3, requiring the inlined `step_b` frame in the report (`atos -i`). | `fire`: exit 245, prints `argv: unavailable in compiled mode`, no ASAN report. `fire run`: `AttributeError: 'str' object has no attribute 'byte_length'` at `sanitize_address_inlined.mojo:45:21`, exit 1. Modular marks it `UNSUPPORTED: asan, system-linux`. | `modular-target-specific` (ASAN + debug-info/inlining/symbolizer specifics). | Runtime/toolchain + debug info. Depends on `sanitize_address`; then preserve and symbolize inlined frames. | `part4` |
| `op_with_unsupported_type_error.mojo` | `kgen -emit=llvm` (host and `nvptx64 … sm_89`) must reject `float8_e3m4` conversions/ops: "conversion from 'f8e3m4' to 'f32' is not implemented" / "operation with a type 'f8e3m4' is not implemented". | `fire`: exit 0, no output, no diagnostic. `fire run`: exit 0, no output. The exported functions are accepted silently. | `feasible-without-gpu-backend` for the semantic/legality guard; the NVPTX-target emission parity in the source's second RUN line is `modular-target-specific`. | Codegen/type lowering + diagnostics. Add legality checks for unsupported scalar/FP8 dtype conversions and binary ops in the lowering path and emit the two Modular messages; verify host path first, gate NVPTX parity separately. | `part4` |
| `end_to_end_thunk_with_direct_compile.mojo` | Cross-compile to NVPTX (`--emit asm --target-accelerator nvidia:sm_90a`): a kernel offloaded directly and through an `enqueue_function` thunk must not duplicate `kgen.offload.kernelid`, and must surface once in PTX with its mangled linkage name. | Only the `max` import failure (`from max.gpu import global_idx`, `from max.gpu.host import DeviceContext`; exit 1). No PTX/offload metadata path exists. | `modular-target-specific` (NVPTX emission + MAX GPU APIs + offload thunk/metadata machinery). | GPU backend/codegen. Implement the NVPTX emission path and kernel-id dedup/routing for thunked vs direct offloads. | `part4` (blocked) |
| `simd_bad_size_lowering.mojo` | `not %mojo`: reject `SIMD[.float32, N]` for N = 0, -1, 3 with `error: SIMD vector length must be a power of two between 1 and 2^15, found '!kgen.simd<N, f32>'`. | Compiled path: guarded where the `SIMD[dtype, width]` type is built from a concrete integer width — `mojo.middle.types._mojo_type` (annotations) and `emit_calls._lower_call` (constructors) — through the shared rule in `mojo/middle/simd_width.py`. `fire` on `SIMD[.float32, 3](1.0)` now prints `error: SIMD vector length must be a power of two between 1 and 2^15, found '!kgen.simd<3, f32>'` and exits non-zero; it previously printed `1.0`, exit 0. Interpreter path: `fire run` rejects 0/-1/3 via `_mojo_simd_width_is_valid` (`myinterpreter.py`), which now delegates to the same shared rule. The canonical source's dot-relative `.float32` still stops the interpreter at `eval_DottedLiteral` (a separate inference gap), but the compiled path emits the width diagnostic before that fallback. Both modes are pinned by `test_regress_gpu_offload_validation_modular_part4.py`. | `feasible-without-gpu-backend`; width guards landed on both paths. | Codegen/type lowering. Landed: reject an illegal concrete width before lowering and word the diagnostic with the lowered `!kgen.simd<N, dtype>` type the canonical test checks. | `part4` |

### Done when (part 1)

`python3 test_regress_gpu_offload_validation_modular_part1.py` exits 0. It
checks that this section still carries one row per affected case with a
follow-up, that the `max.gpu` block is still real (a program importing
`max.gpu.host` still fails with `No module named 'max'`), and that part 4's
interpreter SIMD guard is intact.
