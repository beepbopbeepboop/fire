SPLIT: CODEGEN_stdlib_dylib_lazy_undefined_refs-part4, CODEGEN_stdlib_dylib_lazy_undefined_refs-part5, CODEGEN_stdlib_dylib_lazy_undefined_refs-part6, CODEGEN_stdlib_dylib_lazy_undefined_refs-part7, CODEGEN_stdlib_dylib_lazy_undefined_refs-part8, CODEGEN_stdlib_dylib_lazy_undefined_refs-part9

# CODEGEN: the stdlib dylib references 50 `_std_` symbols it never defines

**Job:** none. This is the latent half of `stdlib-dylib`, which now passes because the JOB's contract is
that the dylib LOADS (a data/class-table reference to an undefined symbol is fatal there; see
`tools/stdlib_dylib_ratchet.py`). These 50 are lazy CALL references: they do not stop the load, but a
client that reaches one through the dylib aborts at that call unless another image happens to define it.

## Replan (2026-11-15): the live parts are 4-9

Parts 1-3 landed and their docs were deleted when they landed:

- part 1: a re-exported free function's reference carries the DEFINING module's
  qualifier (`_reexported_defining_qualifier`).
- part 2: an imported free function's overload suffix is the DEFINING unit's
  (the text-scan `Span`/`StringSlice` -> `char *` mapping).
- part 3: a same-arity struct dunder names one concrete overload (subscript
  dispatch and the comparison lowering); the suffix-less forward declaration
  for an overloaded dunder is gone. The total was 50 -> 43 -> 32 by
  2026-11-14, with 0 modules falling back to source.

The title's "50" is the 2026-11-12 measurement and is stale; the live
residual is the table below. Measured 2026-11-15 in this worktree by compiling
each caller and definer module with `compile_module_to_c` and comparing the
undefined `_std_` names against the definers' exported names (no whole-stdlib
build, no link), then confirming the end-to-end shape with two-module
`build_stdlib_dylib.build` dylibs. The probes are
`test_stdlib_dylib_lazy_undefined_refs_probes.py`.

| part | doc | class | example symbols |
|---|---|---|---|
| 4 | `bugs/CODEGEN_stdlib_dylib_lazy_undefined_refs-part4.md` | a `comptime if` chain emits the other TARGET's bodies; only the host's `_linux`/`_macos` variant is built | 4 x `std_os__linux_{aarch64,x86}__{lstat,stat}` from `std/os/path/path.mojo` |
| 5 | `...-part5.md` | a body the backend cannot lower vanishes, so the caller's qualified name has no definition (its own calls get a BARE weak stub) | `std_sys_info_is_{apple,nvidia,amd}_gpu`, `std_python__cpython_CPython_as_imm` |
| 6 | `...-part6.md` | a BRACKETED `Span`/`StringSlice` param is `char *` in the text scan and `Span *` in the defining unit | 4 x `std_collections_string__unicode_*`, `_count_utf8_continuation_bytes`, `std_sys__amdgpu_printf_append_string_n` |
| 7 | `...-part7.md` | a struct type private to the defining module becomes `int64_t` on the caller side | `std_benchmark_benchmark__run_impl` |
| 8 | `...-part8.md` | two same-name free functions in one module are neither defined nor callable; the call becomes a bare `(void)` stub | `std_bit_mask_splat`, `std_memory_memory__free`, `..._unsafe_memset_zero`, `..._to_integer` |
| 9 | `...-part9.md` | a generic free function instantiated only by another module is never emitted | `..._forget_deinit`, `..._unsafe_destroy_n`, `..._dealloc`, `std_time_time_time_function` |

Not a part:

- The five `_std_ffi___init___OwnedDLHandle_*` references from
  `std/python/_cpython.mojo` are not a name mismatch. Their defining module,
  `std/ffi/__init__.mojo`, does not compile in this tree at all:
  `std/ffi/__init__.mojo:360:0: error: invalid bindings in signature: lacking
  evidence` (the same error `std/simd.mojo` gives at 2247). A module that
  falls back to source is the dylib's documented, accepted state; making ffi
  compile is a diagnostics/elaboration bug (see the `lacking evidence` note in
  `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and
  `test_binding_deferral_diagnostic.py`), not this doc's name-resolution work.
- The Array/Deque/List `__getitem__` entries in the old bare-dunder list are
  gone after part 3; the in-flight
  `CODEGEN_simd_and_array_values_erase_to_int64` lane is not touched by these
  parts.
- The `unresolved_stdlib_refs` count is not made a gate condition here: the
  ratchet's contract is still "the dylib LOADS", and the parts shrink the lazy
  gap one class at a time.

**Working the parts:** each part's `## Done when` names one probe in
`test_stdlib_dylib_lazy_undefined_refs_probes.py`; run it red first, fix, run
it green. The probe file is deliberately not a registered gate job.


**This section is the 2026-11-12 snapshot**, kept for the measurements'
provenance. Several of its group diagnoses are superseded by the
`## Replan (2026-11-15)` table above (notably: `mask_splat` is
`std/bit/mask.mojo`'s `splat`, an overloaded free function, and
`_run_impl` is a suffix mismatch, not a missing function).

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
  `_effective_param_types` is not the defining unit's signature. **The suffix half is fixed**
  (`module_loader`'s text-scan maps `Span`/`StringSlice` parameters to `char *`, the defining unit's
  lowering) — re-measure the remaining names.
- **Qualifier is the re-exporting package, not the defining module**: callers emit
  `_std_memory___init___unsafe_memset_zero`, `..._unsafe_destroy_n_2dbb98`, `..._forget_deinit_9f63a2`,
  `..._alloc_dealloc_9f63a2`, `_std_time___init___sleep`, `_std_os___init___listdir_9f63a2`,
  `_std_pwd___init___getpwnam_d719e0`/`getpwuid_9f63a2`, `_std_random___init___seed`; the definitions
  live in `std/memory/memory.mojo`, `std/time/time.mojo`, `std/os/os.mojo`, `std/pwd/_macos.mojo`, …, so
  their symbols are `std_<module>_...`. **The qualifier half is fixed** (`_reexported_defining_qualifier`):
  references now spell `std_time_time_sleep`, `std_pwd_pwd_getpwnam_d719e0`, etc. This does NOT define a
  symbol that has no emitted definition: `unsafe_memset_zero` is generic/uninstantiated in
  `std/memory/memory.mojo`'s standalone compile, so its reference now names
  `std_memory_memory_unsafe_memset_zero` and stays undefined — that is this doc's
  "Function not emitted at all" class, not the qualifier group.
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

**Exact next step:** work parts 4-9, in the order of the table above. Each
part's `## Done when` names the probe that is red today and green when the
part lands. The old advice to take "the arity-only overload choice" is part 3,
which landed; the remaining classes are the replan table's, not this
section's.

## Re-measured 2026-11-15: the JOB is green; 32 references remain

The job this doc was filed against now PASSES:

    python3 tools/stdlib_dylib_ratchet.py
    -> stdlib-dylib: 0 module(s) fell back to source (0 expected)
    -> exit 0

and `tools/control.py gate list` no longer turns `stdlib-dylib` off. The count
is **32**, down from the 50 the Symptom above records (43 after part 1, 32
after part 3). Of the 32, **12 carry no overload suffix** — `_std_sys_info_
is_apple_gpu`, `_std_sys_info_is_nvidia_gpu`, `_std_random_random_seed`,
`_std_time_time_sleep`, `_std_memory_memory__free`, `_std_bit_mask_splat`,
`_std_collections_string_string__calc_initial_buffer_size`,
`_std_python__cpython_CPython_as_imm`, `_std_sys_info_is_amd_gpu`,
`_std_sys_info_has_nvidia_gpu_accelerator`, `_std_time_time_time_function`,
`_std_memory_memory_unsafe_memset_zero` — and the other 20 carry a suffix that
is not the defining unit's.

All 12 unsuffixed ones were calls to an OVERLOADED free function from a module
that did not define it (`std/sys/info.mojo`'s `is_apple_gpu()` has both a
`()` and a `[subarch: StaticString]()` overload). **Fixed 2026-11-15
(`ddc086d41`)**: a MIXED overload set (one plain head + one bracketed head) was
caught by the generic-import registration and returned early, so it never
reached the overload registration, and the opener set `'('` could not even see
a bracketed head; `_elaborate_overload_call` also mangled from the BARE name,
dropping the defining module's qualifier. The references are now correct --
`_std_sys_info_is_apple_gpu__void`, `_std_pwd__macos__getpw_macos__1_0_6_
String` / `__1_0_6_UInt32`.

**The count went 32 -> 38, and that is an honest regression in the metric,
not a fix.** The names are right now, and being right exposes references the
dylib never defined: both `getpw_macos` overloads are referenced where before
only the one the ABI scan happened to pick was, and two `_gpu_intrinsics_`
entries appeared. The job still PASSES (0 modules fall back to source, ratchet
exit 0) because these are lazy call references a client falls back from, but
the definers are still absent from the dylib -- that, not the naming, is now
the visible remaining work.
