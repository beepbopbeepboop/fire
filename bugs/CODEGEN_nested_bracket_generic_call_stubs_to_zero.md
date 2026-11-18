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
