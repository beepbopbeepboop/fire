# CODEGEN: a private struct parameter/return is `int64_t` on the caller side and a pointer on the defining side

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 7.

## Goal

`std/benchmark/bencher.mojo` must reference the symbol
`std/benchmark/benchmark.mojo` emits for `_run_impl`. Today the caller's
text-scan signature cannot resolve `_RunOptions` (private to
`benchmark.mojo`), falls back to `int64_t` for the parameter AND the return
type, and derives a different suffix:

    caller:  extern int64_t std_benchmark_benchmark__run_impl_9f63a2 (int64_t opts);
    definer: Report * std_benchmark_benchmark__run_impl_0c2adc (_RunOptions * opts)

## Evidence (measured 2026-11-15, this tree)

`std/benchmark/bencher.mojo`'s object `nm -u` lists
`_std_benchmark_benchmark__run_impl_9f63a2`;
`std/benchmark/benchmark.mojo`'s C defines only
`std_benchmark_benchmark__run_impl_0c2adc`. The defining source is
`def _run_impl(opts: _RunOptions) raises -> Report:` (`benchmark.mojo:529`).

Both `_RunOptions` and `Report` are structs declared in `benchmark.mojo`
itself, so the importer has no `Span`-style externally-known typedef for them.
The text-scan signature (`module_loader._imported_sigs` /
`_imported_type_ctype`) therefore boxes both to `int64_t`, which changes the
overload suffix and the whole declaration.

The same-neutral case `_run_impl_fixed(int64_t, int64_t) -> Report` is NOT
affected symmetrically: its parameters are primitives, and its return type is
`Report`, so it currently names `..._run_impl_fixed_2dbb98` — which happens to
match the definition only because the return type is not part of the suffix.
Do not rely on that; a return type change must not move a suffix.

## Work

1. Resolve an imported function's parameter/return annotation through the
   DEFINING module's own declarations: `module_loader` already has the
   defining source and `GimpleGen` already builds its struct table
   (`_find_struct_template_source` is the existing cross-module struct lookup).
   Map `_RunOptions` to `_RunOptions *` and `Report` to `Report *` instead of
   the `int64_t` catch-all.
2. Keep the catch-all for genuinely unknown types (that fallback is what makes
   forward references parse today).
3. The suffix must then be computed from the same type list the definition
   used; if the two are still computed separately, that is the duplicate this
   part exists to remove.

## Acceptance

- `bencher.mojo`'s `_run_impl` reference is a symbol `benchmark.mojo` defines
  (`..._run_impl_0c2adc`).
- `bencher.mojo`'s `_run_impl_fixed` reference still resolves.
- A function whose struct parameter is genuinely unavailable keeps today's
  `int64_t` fallback rather than failing the build.

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p7_struct` exits 0.
It compiles `std/benchmark/benchmark.mojo` and `std/benchmark/bencher.mojo`
through `compile_module_to_c` (no gcc, no link, ~5 s) and compares the
`_run_impl` symbol on both sides.
