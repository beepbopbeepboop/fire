# Imported generic overloads: only one overload gets an extern (hip_hostcall warnings)

`python3 build_stdlib_dylib.py` still prints three
`-Wint-to-pointer-cast` warnings in `std/_plugin/hip/hip_hostcall.mojo`
(lines 64, 583, 883): `readfirstlane(...)` is called with a scalar.

`hip_intrinsics.mojo` has two generic overloads:

    def readfirstlane[T: AnyType, //](value: Pointer[T, ...]) -> type_of(value)
    def readfirstlane[dtype: DType](value: Scalar[dtype]) -> Scalar[dtype]

Only the pointer one is registered as an extern
(`std__plugin_hip_hip_intrinsics_readfirstlane_55072c (int64_t *)`), so every
call, scalar or not, binds to it and the scalar argument is cast to a pointer.
The code is AMD-GPU-only (`comptime assert is_amd_gpu()`), so nothing runs on
the host, but the call is mis-resolved.

## Status
- 2026-11-05: `x.cast[DType.int32]()` / `x.cast[.int32]()` on a scalar was an
  identity echo (the cast was dropped, so the argument kept its source width).
  Fixed in `emit_calls.py` (`_dtype_cast_ctype`). This was not enough: the
  overload choice still lands on the pointer overload.
- Not done: resolving between generic overloads by argument type in link mode
  (`_effective_param_types` -> `func_param_types['readfirstlane']` holds one
  entry). Next step: register one extern per overload (suffix hashed from each
  overload's own parameter ctypes) and pick by the call's argument ctypes.
- Quick test: `python3 build_stdlib_dylib.py -o /tmp/x.dylib <path>/hip_hostcall.mojo`
  prints no warnings.
