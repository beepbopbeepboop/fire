# CODEGEN: a bracketed generic call inside a generic instantiation compiles to a silent 0

**Status (2026-11-17): partially fixed — the integer-valued repro below is fixed and landed;
the DType/string-literal half (step 3) is still open.**

Landed (integer-valued bracket arguments, the repro below):

- Root cause: a generic instantiation is compiled by `monomorphize.instantiate` in a fresh
  `GimpleGen` that sees only its own concrete source. `ident` (the callee) was not visible there,
  so `_elaborate_generic_call` declined and `emit_calls._lower_call` stubbed the call to `0`. The
  callee's object would also have been dropped at the `instantiate` boundary even if it had been
  elaborated.
- Fix: `monomorphize.instantiate(generic_paths=, links_out=)` passes the caller's generic templates
  down (`gen._sibling_generic_paths`, resolved only for explicitly bracketed calls, since a bare
  `log(x)` inside math's `log[...]` names a non-generic overload). A template that makes such a call
  folds each callee's source digest into its key (`_sibling_fingerprints`), and its nested objects
  are recorded in a `.links` CAS sidecar and attached at the call by
  `emit_resolve._emit_generic_instantiation`. Forwarding is `emit_resolve._generic_paths_for`, so
  two levels of nesting resolve too.
- Measured: the repro below prints `13` (was `1`).
- Tests: `test_elaboration_recursion_diagnostic.py::test_nested_bracketed_call_in_instantiation_is_materialized`
  (13) and `::test_nested_bracketed_calls_two_levels_and_shared_callee` (37) pass. The file's other
  seven cases pass too, including `::test_intrinsic_name_bracket_arg_builds`, which had been failing before
  elaboration on an unrelated pre-existing unknown-declaration false positive: the compiler-provided
  `type_of` builtin was not in the name check's known set. Fixed 2026-11-17 (all nine cases pass).
  Not run here: `stdlib-dylib` / `stdlib-syntax` skip and FAILED counts (integrator gate).

Still open (the doc stays until these pass):

- DType and string-literal bracket arguments still stub. Measured 2026-11-13: with
  `tag[s: StaticString](x) = x + 100` called as `tag["abc"](x)` and `ident[dt: DType](x) = x + 10`
  called as `ident[.uint32](x)`, `wrap[1](5)` prints `1` (expected `121`). Cause:
  `_type_expr_to_ann` renders `StringLiteral` and `DottedLiteral` as `''`, so
  `_elaborate_generic_call` refuses them. This is step 3 below.
- The stdlib call sites this affects (`_format_float._truncate[.uint32]`, `llvm_intrinsic["llvm.*"]`)
  still compile to 0 in the dylib.

## Repro

Built with `python3 fire.py build <file> -o <bin>`:

    def ident[n: Int](x: Int) -> Int:
        return x + n

    def wrap[i: Int](x: Int) -> Int:
        return ident[7](x) + i

    def main():
        print(wrap[1](5))

- **Expected:** `13` (`ident[7](5) = 12`, plus `i = 1`).
- **Observed (before the fix):** `1` — `ident[7](5)` was emitted as the stub `(int64_t)0`
  (`gimple_codegen`'s "indirect call stubbed" path in `mojo/backend_gimple/emit_calls.py`,
  `_lower_call`), so the nested call contributes 0 and nothing is reported.

The same shape with a `DType` or string-literal bracket argument (`ident[.uint32](x)`,
`tag["abc"](x)`) also stubs to 0. At top level (`main` calling `ident[.uint32](5)` directly) the
call IS elaborated and correct (prints `5`), so the defect is specific to a call whose
enclosing function is itself a concrete elaborated instantiation.

## Why it matters

The stubbed value is silently wrong. Two stdlib modules hit exactly this shape and so compile to
0 for these calls in the dylib: `std/builtin/_format_float.mojo` (`_truncate[.uint32](...)`) and
`std/math/math.mojo` / `std/collections/string/string.mojo` (`llvm_intrinsic["llvm.*", ...]`).
Whether any caller reaches those values at run time was not measured.

## Why the stub is reachable at all

`b3e501b60` ("Refuse mutually recursive and unbounded generic instantiation") added a refusal for
non-concrete bracket arguments inside an elaborated instantiation. It was meant to refuse only an
argument that can recurse without bound (`i + 1`) or names an unbound type parameter. It refused
every argument the renderer leaves blank (`_type_expr_to_ann` returns `''` for `StringLiteral` and
`DottedLiteral`), which made 6 stdlib modules skip. That refusal is narrowed in the same commit
that adds this doc, so those calls are back on the pre-existing stub path, which is this bug.

## What was tried and why it was not kept

Rendering `StringLiteral` (as `repr`) and `DottedLiteral` (as `.<path>`) in
`mojo/middle/resolve_shared.py::_type_expr_to_ann` makes those args concrete, so the elaborator
accepts them. That turned the 6 skips into 5 different skips in `benchmark`, `_rng`
(`gcc -c` failure on `max_finite_5_dtype_13__x002Efloat64`), `simd` (`comptime assertion failed:
Int and UInt do not conform to DevicePassable` for `SIMD[.bfloat16, ...]`) and `_amdgpu`. So
concrete args do reach the elaborator once rendered, but the callees they then reach have their
own gaps. Reverted; the rendering is the right direction but needs those gaps closed first.

## Exact next step

1. DONE (2026-11-13): the nested call is registered and materialized; the `13` probe passes.
2. DONE (2026-11-13): tests above; the repro is `13`.
3. Retry the `_type_expr_to_ann` rendering of `StringLiteral`/`DottedLiteral` in
   `mojo/middle/resolve_shared.py` (render `repr` / `.<path>`), now that nested calls reach the
   elaborator. Earlier attempts exposed gaps in the callees (`benchmark`, `_rng`, `simd`,
   `_amdgpu`); close them one at a time. Measure after each with the DType/string probe above.
4. Tighten `test_concrete_unrenderable_type_arg_is_not_refused` to assert `121` once step 3 lands,
   then delete this doc in the same commit (and run `tools/dangling_doc_refs.py --ratchet`).

## Status (2026-11-19) — step 3 measured again; the rendering is correct, three callee gaps block it

Rendering `StringLiteral` (`repr(value)`, non-bytes) and `DottedLiteral` (`'.' + path`) in
`resolve_shared._type_expr_to_ann` makes the probe (`ident[.uint32]` + `tag["abc"]` inside
`wrap[1]`, expected `15 + 105 + 1 = 121`) print `121` (was `1`). Not landed: with it,
`compile_stdlib.py` goes from 0 to **2 unexpected** failures (608 passed), and one more shape runs away:

1. `test/builtin/test_sort_issue_1018.mojo`: `_sort_test[.int8, "int8"]` is now elaborated and its
   body calls `sort(p)` with **no import** (it is a prelude name, `std/prelude/__init__.mojo:127`).
   The call lowers to a bare `_sort`: undefined at link time, and `gcc -c failed` under
   `compile_stdlib`. A plain `main` calling `sort(p)` with no import fails the same way, so this is
   an existing prelude gap that the stub used to hide. `from std.builtin.sort import sort` builds but
   prints `sort: unavailable in compiled mode`, so the real `sort` is uncompilable too. Registering
   `'sort': 'std.builtin.sort'` in `GimpleGen._PRELUDE_GENERICS` (the `alloc` mechanism) was tried and
   reverted: it elaborates the real `sort`, which fails with `invalid conversion in gimple call` at
   `std/collections/counter.mojo:948` and `invalid use of void expression` at the call.
2. `std/simd.mojo`: codegen fails at
   `SIMD_5_dtype_14__x002Ebfloat16_6_length_1_2.mojo:423` (the `SIMD[.bfloat16, 1]` instantiation).
   The doc's earlier note ("Int and UInt do not conform to DevicePassable") is the same family.
3. **Runaway import-closure compile (bisected 2026-11-19, under `tools/memcap.py`).** Not an
   elaboration cycle. With the rendering applied, a plain `fire.py build` of
   `from std.random import rand` + a generic `_t[dtype: DType, name: StaticString]` whose body does
   `rand(p)`, called as `_t[.int8, "int8"](300, 3_000)`, never finishes (15 min timeout, then killed;
   an earlier unwrapped run reached 7 GB). Controls, same imports, each under 8 GB: direct `rand(p)`
   in `main` builds in 71 s (0.1 GB); the generic defined but never called builds in 69 s; the
   generic with `sort` only fails fast at link (item 1); the generic with neither builds. A stack
   sample at 150 s is in `_gmp_compile_imports` -> `_compile_imported_module` -> `gen_module`
   recursion, ~60 levels deep (`std.random` -> `.philox` -> `std._gpu.intrinsics` -> `std._gpu`
   -> `.host.info` -> `std.sys` -> ... -> `std.python._cpython` -> `std.os.path` -> `std.memory.Pointer`),
   i.e. the `do_imports=True` inline closure `fire.py build` always uses
   (`build_executable` -> `compile_to_gimple_cached(do_imports=True)`), emitting `# ERROR: compiling
   imported module ...: cannot compile in-process: a bracketed call X[...]() needs the generic
   instantiated, which the single-unit path does not do; link mode (fire build) does`. So the
   instantiated generic's `rand` reference makes the main build pull in the whole `philox`/`_gpu`
   closure inline, where it is not cached. `std/_gpu/intrinsics.mojo`, `std/random/philox.mojo`
   and `std/random/_rng.mojo` are three of the eight files the stdlib-dylib gate listed red while the
   dtype-representation branch was in flight (that gate went green on master, 2026-11-19), so that gate
   failure and this one probably shared the cause.
   Diagnostic recipe: `tools/memcap.py --limit-gb 8 -- python3 <wrapper> build x.mojo` where the
   wrapper does `signal.alarm(150)` and prints `_compile_imported_module`'s `module_name` per frame.

Next step: (a) find why the instantiated `rand` use compiles its import closure uncached and
inline (item 3), probably by comparing the module-cache keys of the `std.random` closure between the
direct-call build (71 s) and the generic build; (b) make an unimported prelude `sort`
resolve to the same honest stub as the imported one, or compile it; (c) close the `SIMD[.bfloat16]`
gap; (d) re-apply the two-line rendering and require `compile_stdlib.py` `U` = 0, then
`test_concrete_unrenderable_type_arg_is_not_refused` asserts `121` and this doc goes.
