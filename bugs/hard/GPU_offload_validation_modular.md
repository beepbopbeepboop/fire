SPLIT: bugs/mid/GPU_offload_validation_modular-part1, bugs/mid/GPU_offload_validation_modular-part2, bugs/mid/GPU_offload_validation_modular-part3, bugs/mid/GPU_offload_validation_modular-part4
# GPU: offload validation for modular test cases (category C)

## Symptom
Modular test files exercise GPU offload features (kernel launch, device passable closures, sanitize address, SIMD lowering). Our compiler does not implement these, so they fail or produce wrong code.

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
- Need to investigate each: some may be implementable, others may be modular-specific (NVIDIA/AMDGPU/Metal targets).
- Our compiler currently has no GPU backend; this is a large feature gap.
EOF