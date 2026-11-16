# CODEGEN: a bracketed generic call inside a generic instantiation compiles to a silent 0

**Status (2026-11-13):** open. Found while fixing `stdlib-dylib` (the gate job went red on
`b3e501b60` + `e920f3a03`); the job is green again without this being fixed, because the
stdlib calls that exercise it take the same stub path they took before `b3e501b60`.

## Repro

Built with `python3 fire.py build <file> -o <bin>`:

    def ident[n: Int](x: Int) -> Int:
        return x + n

    def wrap[i: Int](x: Int) -> Int:
        return ident[7](x) + i

    def main():
        print(wrap[1](5))

- **Expected:** `13` (`ident[7](5) = 12`, plus `i = 1`).
- **Observed (current tree):** `1` — `ident[7](5)` was emitted as the stub `(int64_t)0`
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

1. Find where a bracketed call inside an elaborated body loses its instantiation. The probe above
   prints `1`; the emitted C for `wrap` will show the `(int64_t)0` stub. Compare the top-level path
   (`main` -> `ident[7]`, which works) with the nested path in `elab_intu._collect_inner`'s
   `visit` (`mojo/backend_gimple/elab_intu.py`). Hypothesis, NOT measured: the nested call is never
   registered because `_collect_inner` walks only the bodies of instantiations it materializes,
   and `ident` is reached only through `wrap`'s own elaboration. Confirm by dumping the registered
   work keys while compiling the repro before changing anything.
2. Once the nested `ident[7]` materializes, re-measure `probe` = `13`.
3. Then retry the `_type_expr_to_ann` rendering of `StringLiteral`/`DottedLiteral` and close the
   `benchmark`/`_rng`/`simd`/`_amdgpu` gaps it exposes, one at a time.
4. Tests: `test_elaboration_recursion_diagnostic.py::test_concrete_unrenderable_type_arg_is_not_refused`
   asserts only that the build is not refused. Tighten it to assert `13` once step 2 lands, and
   delete this doc in the same commit.
