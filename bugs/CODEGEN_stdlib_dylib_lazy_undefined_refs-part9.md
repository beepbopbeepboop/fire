# CODEGEN: a generic free function instantiated only by another module is never emitted

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 9.

## Goal

A caller that instantiates a generic free function with concrete types must
find a definition of that instance in the dylib. Measured cases:

| defining module | generic | caller | reference |
|---|---|---|---|
| `std/memory/memory.mojo` | `forget_deinit[T]` | `std/collections/array.mojo` | `_std_memory_memory_forget_deinit_9f63a2` |
| `std/memory/memory.mojo` | `unsafe_destroy_n[T]` | `std/collections/array.mojo` | `_std_memory_memory_unsafe_destroy_n_2dbb98` |
| `std/memory/alloc.mojo` | `dealloc[T]` | `std/collections/list.mojo` | `_std_memory_alloc_dealloc_9f63a2` |
| `std/time/time.mojo` | `time_function[FuncType]` | `std/benchmark/benchmark.mojo` | `_std_time_time_time_function` |

## Evidence (measured 2026-11-15, this tree)

A two-module dylib built with `build_stdlib_dylib.build([definer, caller])`
leaves all four names in `nm -u` and defines none of them. The defining
module's own C contains no instance (`grep` for the name finds nothing),
because a module is compiled ALONE: nothing in `memory.mojo` asks for
`forget_deinit[Int]`, so the generic has no concrete signature to emit.

The caller DOES know the concrete types for the first three (its reference
carries the concrete suffix `_9f63a2` / `_2dbb98`), which is why the gap was
invisible to the caller-side signature scan. `time_function`'s caller falls
back to the bare name because its type parameter is a function type.

`build_stdlib_dylib.build` already runs a cross-module pre-pass
(`known_structs`, computed before any job is dispatched) for exactly this
reason on the struct side, and `monomorphize.mangle` / `mangle_signature`
already name a concrete instance of a generic.

## Work

1. Extend the builder's pre-pass from structs to free functions: collect, for
   every module being linked, the `(name, concrete type args)` instances its
   imports/calls ask for (the text-scan signatures already carry them for
   `forget_deinit`/`unsafe_destroy_n`/`dealloc`), and pass the defining
   module's list to that module's compile.
2. The defining module emits each requested instance with the SAME qualifier
   and suffix the caller uses — one naming function (`_func_csym` /
   `monomorphize.mangle`), not a second spelling.
3. If a requested instance cannot be lowered, fail that module's build (a
   visible `skip <module>:` line) rather than emitting a wrong-erased template.
   The dylib's "skip and fall back to source" contract is the honest answer.
4. Alternative shape, if the pre-pass is too invasive: have the CALLER emit the
   instance in its own TU under the defining module's qualifier, the way
   `_localize_symbols` already handles colliding struct instances. Prefer the
   defining unit: the template source is its own file.

`benchmark.compiler.keep[T, origin]` is the same class; no current module in
the dylib references it, so it is not in the table. Fix the mechanism, not
this list.

## Acceptance

- The three two-module dylibs above leave none of the four names undefined.
- A module that only DECLARES a generic (no importer asks for an instance)
  still emits nothing for it, and the dylib still links (the existing
  `stdlib-dylib` contract is unchanged).
- The `skip <module>:` count does not increase: run
  `python3 tools/stdlib_dylib_ratchet.py` if the change touches `build()`'s
  per-module error path (it is the job that reads that count).

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p9_generic` exits 0.
It builds the three two-module dylibs (`build_stdlib_dylib.build`, ~7 s each)
and asserts none of the four names is in `unresolved_stdlib_refs`.
