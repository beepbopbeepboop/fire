# CODEGEN: the stdlib dylib references 50 `_std_` symbols it never defines

**Job:** none. This is the latent half of `stdlib-dylib`, which now passes because the JOB's contract is
that the dylib LOADS (a data/class-table reference to an undefined symbol is fatal there; see
`tools/stdlib_dylib_ratchet.py`). These 50 are lazy CALL references: they do not stop the load, but a
client that reaches one through the dylib aborts at that call unless another image happens to define it.

**Measured on master `793118227`, 2026-11-12**, with the ratchet's own build and the `nm` pair the bug
doc for the matcher used:

    python3 tools/stdlib_dylib_ratchet.py        # builds build/libmojostdlib.<arch>.dylib
    nm -u  build/libmojostdlib.arm64.dylib       # 50 _std_ names below
    nm -gU build/libmojostdlib.arm64.dylib       # none of them is defined
    dyld_info -fixups build/libmojostdlib.arm64.dylib   # all 50 are lazy-bind __la_symbol_ptr

The names, grouped by what the DEFINITION is actually called (the group is the cause):

- **Overload suffix disagrees with the definition's** (same symbol, different hash):
  `_std_collections_string__parsing_numbers_parsing_floats__atof_55072c` vs defined
  `..._atof_d719e0`; `_std_collections_string__unicode_is_lowercase_55072c` vs `..._fa3cf4` (same for
  `is_uppercase`, `to_lowercase`, `to_uppercase`,
  `_std_collections_string__utf8__count_utf8_continuation_bytes_55072c`). The call site's
  `_effective_param_types` is not the defining unit's signature.
- **Qualifier is the re-exporting package, not the defining module**: callers emit
  `_std_memory___init___unsafe_memset_zero`, `..._unsafe_destroy_n_2dbb98`, `..._forget_deinit_9f63a2`,
  `..._alloc_dealloc_9f63a2`, `_std_time___init___sleep`, `_std_os___init___listdir_9f63a2`,
  `_std_pwd___init___getpwnam_d719e0`/`getpwuid_9f63a2`, `_std_random___init___seed`; the definitions
  live in `std/memory/memory.mojo`, `std/time/time.mojo`, `std/os/os.mojo`, `std/pwd/_macos.mojo`, …, so
  their symbols are `std_<module>_...`.
- **Bare dunder where the definition is overloaded**: `_std_collections_array_Array___getitem__`,
  `_std_collections_deque_Deque___getitem__`, `_std_collections_list_List___getitem__`,
  `_std_collections_string_string_span_StringSpan___{eq,gt,le,lt}__`,
  `_std_ffi_cstring_CStringSpan___eq__`, `_std_memory_pointer_Pointer___{eq,getitem}__`,
  `_std_python__cpython_CPython_as_imm`. `_lower_struct_subscript_dunder` picks an overload only when
  the arity match is UNIQUE; two same-arity overloads leave `overload_id == ''`.
- **Function not emitted at all**: `_std_memory_memory__free` (and `std/collections/string_string.mojo's
  `_calc_initial_buffer_size` reference to `..._int32_9f63a2`/`..._int64_88e58d`), `_std_bit_mask_splat`
  (no source defines `mask_splat`), `_std_benchmark_benchmark__run_impl_9f63a2`,
  `..._compiler_keep_9f63a2`, `_std_bit___init___log2_ceil_9f63a2`, and the `std_sys_info_is_*_gpu`
  family.
- **Target-mismatched**: `_std_os__linux_aarch64__{lstat,stat}_d719e0`,
  `_std_os__linux_x86__{lstat,stat}_d719e0`, `_std_sys__amdgpu_printf_append_string_n_f5e74a` — a macOS
  build's `std/os/path/path.mojo` still references the other targets' bodies.

**Callers per symbol** (module object that carries the undefined reference) were measured the same way:
`std_memory_pointer` → `..._free`; `std_python_python` → `CPython_as_imm`;
`std_collections_string_string_span.local.o` → the `StringSpan` comparisons and the unicode helpers;
`std_benchmark_bencher` → `benchmark__run_impl_9f63a2`; `std_testing_assert_aborts` →
`time___init___sleep`/`perf_counter`; `std_os_path_path` → the linux `lstat`/`stat` and pwd symbols.

**What to expect:** each reference should name the symbol its defining unit really emits (qualifier,
overload suffix, or a body that exists). The gate for this class is a check that says so, not the load
test: run `nm -u` against `nm -gU` and require the `_std_` difference to *shrink*. Do not make
`stdlib-dylib` fail on it until the count is zero: all 50 exist before the fix and the job's documented
contract is that the dylib need not be complete.

**Exact next step:** start with the qualifier group, because it is one registry bug (the home module of a
re-exported free function is recorded as the re-exporting `__init__`), then the suffix group
(`_effective_param_types` for imported names), then `_lower_struct_subscript_dunder`'s arity-only
overload choice. The Array/Deque/List `__getitem__` entries overlap the in-flight
`CODEGEN_simd_and_array_values_erase_to_int64` lane — re-measure after that lands before touching them.
