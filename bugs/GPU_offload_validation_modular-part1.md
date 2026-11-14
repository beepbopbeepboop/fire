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

## Source lookup (this worktree)

None of the 10 `.mojo` files are present under `/Users/mrs/net/chatgpt/claude/work-7026` (searched with `find . -name "<case>"` and `rg` for the case names; no local copies found).

Canonical Modular test sources were read for intent/commands from:
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/compile_offload_unbound_param_error.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/compile_offload_missing_symbol_error.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/max_license/compile_offload_bundle_order.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/max_license/enqueue_function_device_passable_closure_arg_error.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/max_license/enqueue_function_device_passable_closure_arg_layout_error.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/max_license/op_with_unsupported_type_error.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/name-mangling/max_license/end_to_end_thunk_with_direct_compile.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/sanitize_address.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/sanitize_address_inlined.mojo`
- `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/simd_bad_size_lowering.mojo`

Concrete observations below were taken in this worktree by running those external files through `python3 tools/memslot.py --gb 8 --label <id> -- python3 fire.py <external-path>` (wrapped with `timeout 30` where noted to bound hangs).

## Triage matrix

| Case | What it tests | Current compiler behavior (this tree) | Classification | Dependency/owner area + smallest next step | Follow-up |
|---|---|---|---|---|---|
| `compile_offload_unbound_param_error.mojo` | Compile-time diagnostic for `std.compile.compile_info` when an instantiated function is missing a parameter and inference should report "failed to infer parameter 'y'..." (Modular: `not %mojo %s` + FileCheck). | `timeout 30 python3 tools/memslot.py --gb 8 --label t1 -- python3 fire.py /Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/compile_offload/compile_offload_unbound_param_error.mojo` → `memcap: t1 -- ceiling 8.0 GB ...` then interrupted by timeout/signal 15 with no diagnostic emitted within 30s ("nothing below this wrapper is left running..."). | `feasible-without-gpu-backend` (diagnostic/semantic validation of parameter binding for `compile_info`/elaboration, independent of device execution). | Owner: parser/diagnostics + elaboration/compile-time reflection (`compile_info`) pipeline. Next step: trace where `compile_info[param_fn[2]]` elaboration hangs or defers, and add deterministic unbound-parameter validation that emits the expected user diagnostic instead of stalling. | `part2` |
| `compile_offload_missing_symbol_error.mojo` | Compile-time diagnostic when slicing/offloading a kernel instantiated with a runtime function pointer (`get_fn[False]()`), which the elaborator cannot refer to as an exported symbol ("cannot slice out exported symbol scale...n=3"). | `timeout 30 ... --label t2 -- python3 fire.py .../compile_offload_missing_symbol_error.mojo` → `memcap: t2 -- ceiling 8.0 GB ...` then interrupted by timeout/signal 15 with no diagnostic emitted within 30s. | `feasible-without-gpu-backend` (symbol/export/slicing validation in elaboration). | Owner: elaboration/offload compilation pipeline + diagnostics. Next step: identify offload-slice/`compile_info` path handling of non-symbol callee values and emit the "cannot slice out exported symbol" diagnostic without asserting/hanging. | `part2` |
| `compile_offload_bundle_order.mojo` | Compile-time/device-offload compilation ordering: bundling must sort offload ops by auto-mangled kernel symbol name (deterministic diagnostics for NVIDIA-target constraints), exercising `compile_info[..., target=A100.target]` and `@export` entrypoints; source checks emitted `constraint failed: *_kern/bb/yy is not supported on NVIDIA GPU` in mangled-name order. | `python3 tools/memslot.py --gb 8 --label t3 -- python3 fire.py .../compile_offload/max_license/compile_offload_bundle_order.mojo` (tail): compiled fallback to interpreter with `driver error ... error: unable to locate module 'max'` / `ModuleNotFoundError: No module named 'max'` from `from max.gpu.host.info import A100` (and related MAX imports); `memcap: done, peak 0.4 GB ... child exit 1`. | `modular-target-specific` (NVIDIA `sm_90a`/A100 target metadata + MAX GPU host/info APIs and offload bundle semantics tied to Modular's GPU toolchain). | Owner: GPU backend/offload bundler + target model. Next step (if ever supported): provide/bridge `max.gpu.host.info` target descriptors and implement deterministic offload-op bundling keyed by mangled kernel symbol in the device compilation pipeline. | out-of-scope as `modular-target-specific` (NVIDIA/Modular MAX target & bundling) |
| `enqueue_function_device_passable_closure_arg_error.mojo` | Enqueue-time validation that a closure argument's device-passable/encoded type matches the compiled kernel's declared argument type; expects a clear `constraint failed` naming incompatible vs expected closure types (Modular: `not %mojo-build --target-accelerator="nvidia:sm_90a"`). | `timeout 30 ... --label t4 -- python3 fire.py .../enqueue_function_device_passable_closure_arg_error.mojo` (tail): `driver error, interpreting instead ... unable to locate module 'max'` / `ModuleNotFoundError: No module named 'max'` from `from max.gpu.host import DeviceContext`; `memcap: done, peak 0.1 GB ... child exit 1`. | `requires-gpu-backend` (kernel compilation/enqueue against `DeviceContext` and device-passable argument encoding; depends on GPU host runtime). | Owner: GPU runtime/host API integration + kernel argument validation. Next step: model `DeviceContext.compile_function/enqueue_function` and device-passable closure typing/encoding checks so mismatched closure argument types are rejected with a deterministic diagnostic. | `part3` |
| `enqueue_function_device_passable_closure_arg_layout_error.mojo` | Enqueue-time validation that encoded device layout/size matches kernel's expected argument layout (host vs device bytes differ for a custom `DevicePassable`), with `constraint failed ... encodes to 16 bytes but ... is 32 bytes` and hint about `host_args=`. | `timeout 30 ... --label t5 -- python3 fire.py .../enqueue_function_device_passable_closure_arg_layout_error.mojo` (tail): `driver error, interpreting instead ... unable to locate module 'max'` / `ModuleNotFoundError: No module named 'max'`; `memcap: done, peak 0.0 GB ... child exit 1`. | `requires-gpu-backend` (device-type encoding/layout at enqueue boundary, GPU host runtime). | Owner: GPU runtime/host API + device-passable layout validation. Next step: implement/represent `DevicePassable` device encoding size and compare encoded size to kernel parameter layout during enqueue validation. | `part3` |
| `sanitize_address.mojo` | Runtime behavior under AddressSanitizer: heap buffer overflow detected with ASAN report pointing at OOB write (`alloc` + `unsafe_offset=1`), built with `--sanitize address` and run expecting ASAN diagnostics. | `timeout 30 ... --label t8 -- python3 fire.py .../sanitize_address.mojo` (tail): `export table: 2049 of 2054 runtime entry points advertised (0 misresolved, 5 undefined)` ... `memcap: done, peak 0.1 GB ... child exit 245` (no ASAN report produced). | `modular-target-specific` (ASAN-enabled build/runtime/toolchain integration and stack-trace formatting expectations tied to Modular's `%mojo-build`/sanitizer pipeline). | Owner: runtime/toolchain integration (sanitizers) + codegen flags. Next step: plumb `--sanitize address` through build/link/runtime in this toolchain and validate ASAN runtime reporting; treat as target/toolchain-specific support work. | `part4` (GPU/target-runtime-adjacent bucket per split; tracked as toolchain-specific sanitizer support) |
| `sanitize_address_inlined.mojo` | Runtime ASAN behavior with inlining: stack trace must include inlined `step_b` source location (DWARF/atos `-i` behavior), built at O3 with `--sanitize address` (macOS-specific). | `timeout 30 ... --label t9 -- python3 fire.py .../sanitize_address_inlined.mojo` (tail): `export table ...` `argv: unavailable in compiled mode` `memcap: done, peak 0.1 GB ... child exit 245` (no ASAN report/inlined frame). | `modular-target-specific` (ASAN + debug info/inlining/atos symbolization specifics on macOS; depends on Modular's sanitizer toolchain). | Owner: runtime/toolchain integration, debug info/codegen. Next step: ensure sanitizer-instrumented optimized builds preserve/report inlined frames with the platform symbolizer; depends on sanitizer support from `sanitize_address`. | `part4` (toolchain-specific sanitizer support) |
| `op_with_unsupported_type_error.mojo` | Compile-time/lowering diagnostic that operations/casts on unsupported types (e.g. `float8_e3m4` cast/add) are rejected (Modular: `not kgen -emit=llvm ...` with "conversion..." / "operation..." errors, including NVPTX target). | `timeout 30 ... --label t6b -- python3 fire.py .../op_with_unsupported_type_error.mojo` (tail): `export table: 2049 of 2054 runtime entry points advertised (0 misresolved, 5 undefined)` ... `memcap: done, peak 0.1 GB ... child exit 0` (no unsupported-type diagnostic; completed successfully). | `feasible-without-gpu-backend` for the semantic/lowering guard itself (type/op legality can be validated in frontend/codegen); NVPTX-targeted variant in source is `modular-target-specific` for target emission parity. | Owner: codegen/type lowering + diagnostics. Next step: add legality checks for unsupported scalar/FP8-like dtype operations/casts in the relevant lowering path and emit deterministic user-facing diagnostics (start with host/LLVM-like path; gate NVPTX parity separately). | `part4` (compiler-side validation/lowering guard item) |
| `end_to_end_thunk_with_direct_compile.mojo` | End-to-end GPU offload/thunk correctness on NVPTX: same kernel offloaded directly and via enqueue thunk must compile once, avoid duplicate `kgen.offload.kernelid`, and emit a single PTX entry with stable linkage-name prefix (cross-compiled to `--target-accelerator nvidia:sm_90a`). | `timeout 30 ... --label t7 -- python3 fire.py .../end_to_end_thunk_with_direct_compile.mojo` (tail): `driver error, interpreting instead ... unable to locate module 'max'` / `ModuleNotFoundError: No module named 'max'` from `from max.gpu import global_idx` / `from max.gpu.host import DeviceContext`; `memcap: done, peak 0.0 GB ... child exit 1`. | `modular-target-specific` (NVIDIA/PTX target, MAX GPU host/runtime APIs, and offload thunk/kernel-id machinery). | Owner: GPU backend/codegen (offload metadata + thunking) + MAX GPU runtime integration. Next step: implement offload kernel-id dedup/routing for thunk-wrapped vs direct offloads and NVPTX emission path; requires GPU target/runtime infrastructure first. | `part4` (blocked on named GPU backend/runtime capabilities) |
| `simd_bad_size_lowering.mojo` | Compile-time/lowering validation that SIMD vector lengths must be a power of two in range (reject 0, -1, 3) with diagnostics naming the invalid `!kgen.simd<...>` type; backstop for cases where builtin assertions are dropped during folding. | `timeout 30 ... --label t10 -- python3 fire.py .../simd_bad_size_lowering.mojo` (tail): `export table ...` then printed `0.0` / `0.0` / `0.0`; `memcap: done, peak 0.1 GB ... child exit 0` (no rejection/diagnostic; invalid SIMD sizes accepted and ran). | `feasible-without-gpu-backend` (frontend/type construction or lowering validation of SIMD shape constraints). | Owner: parser/semantics or type/lowering validation for `SIMD[...]`. Next step: enforce SIMD length legality (power-of-two, valid range) at construction/elaboration or lowering and emit a deterministic diagnostic instead of accepting/lowering invalid sizes. | `part4` (compiler-side validation/lowering guard item) |

## Assignment summary

- `part2`: `compile_offload_unbound_param_error.mojo`, `compile_offload_missing_symbol_error.mojo`
- `part3`: `enqueue_function_device_passable_closure_arg_error.mojo`, `enqueue_function_device_passable_closure_arg_layout_error.mojo`
- `part4`: `sanitize_address.mojo`, `sanitize_address_inlined.mojo`, `op_with_unsupported_type_error.mojo`, `end_to_end_thunk_with_direct_compile.mojo`, `simd_bad_size_lowering.mojo`
- out-of-scope as `modular-target-specific` (with justification above): `compile_offload_bundle_order.mojo` (NVIDIA A100 target + Modular MAX offload bundling semantics)

## Status

Triage complete (2026-11-13): all 10 cases documented with intent, concrete `fire.py` observations/commands (or source-only lookup notes), classification, owner/next-step, and a single follow-up disposition each. No compiler/runtime behavior changes made.
