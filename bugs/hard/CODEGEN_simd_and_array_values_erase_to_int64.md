# CODEGEN: SIMD values and `Array`/`Span` elements erase to `int64_t`, so their real type is unknown

**Status:** OPEN — the *diagnostic* fallout was fixed 2026-11-10 (see
"Landed" below); the type-erasure above it is not.

## Landed (2026-11-10)

`elaborate.elaborate_generic_call_inferred` no longer surfaces a
`ConformanceError` when any argument's C type is a placeholder
(`elaborate.inferred_ctype_is_specific`: `int64_t`/`int` are this codegen's
universal scalar fallbacks, and any C type absent from `_C_TO_MOJO` — `char`,
a bare `Foo *` — reads as `Int`). Such a call declines (the caller falls
through to its nominal stub) exactly as before the where-clause check landed.
An explicit `f[T](...)` still gets `error: invalid call to '<fn>': violated
constraint`, which is what `test_where_clause_call_site_diagnostic.py` pins;
the new `test_inferred_where_clause_diagnostic.py` pins the decline.

That restores the six stdlib files the where-clause enforcement
(commit `082acf923`) turned red in `stdlib-syntax`:
`std/random/philox.mojo:300`, `test/math/test_erf.mojo:23`,
`test/math/test_exp.mojo:110`, `test/math/test_ldexp.mojo:28`,
`test/math/test_math.mojo:626`, `test/math/test_tanh.mojo:49` — measured
610/610 PASSED on the master+branch merge tree after the change
(`python3 tools/memslot.py --gb 8 --label merged-full -- python3
compile_stdlib.py -j 4`).

The underlying erasure is still there, and files that hit it still compile the
call as the "unavailable in compiled mode" stub rather than a real
instantiation.

## What was measured (2026-11-10, scratch tree = master + this branch's merge)

A minimal probe through `build_stdlib_dylib.compile_module_to_c`:

```sh
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import build_stdlib_dylib as b
src = 'def f():\n    var a = Array[Float32, 4](fill={})\n    print(a[0])\n'
open('/dev/stdout','w').write(b.compile_module_to_c(src, 'arr.mojo', 'arr', linkable=False))
PY
```

emits

```c
_t1 = (int64_t)0;  /* indirect call via SubscriptExpr */
a = _t1;
_t4 = (int64_t)a;
_t3 = (MojoList *)_t4;
_t6 = mojo_list_get_int (_t3, _t5);
```

i.e. the `Array[Float32, 4](fill={})` constructor lowers to the integer `0`
(an "indirect call via SubscriptExpr" fallback), the local is `int64_t`, and
the element read is `mojo_list_get_int`. `Span(a)` then takes its element type
from `_elem_types`, which has none, so `_lower_subscript`'s untracked-`Span`
arm (`_data` is `char *`) reads ONE BYTE: the call `tanh(x[0])` reaches
`_elaborate_generic_call` with `argctypes == ['char']`, which
`elaborate.c_to_mojo` maps to `Int`, and the callee's
`where dtype.is_floating_point()` is correctly rejected for `Int`.

Other erased shapes observed at the same six sites:

| site | argument lowering | `c_to_mojo` |
|---|---|---|
| `std/random/philox.mojo:300` `log(u)` | `int64_t` (SIMD/FMA) | `Int64` |
| `test/math/test_erf.mojo:23` `erf(SIMD[.float32, 2](2))` | `int64_t` (SIMD ctor) | `Int64` |
| `test/math/test_exp.mojo:110` `exp(Float32Expable(1.0))` | `Float32Expable *` (struct ptr) | `Int` (default) |
| `test/math/test_ldexp.mojo:28` `ldexp(SIMD…, SIMD…)` | `int64_t`, `int64_t` | `Int64` |
| `test/math/test_math.mojo:626` `log1p(val)` | `int64_t` | `Int64` |
| `test/math/test_tanh.mojo:49` `tanh(x[i])` | `char` (Span byte) | `Int` |

`Scalar[dtype]` is `SIMD[dtype, 1]`, and `GimpleGen._resolve_type` answers
`int64_t` for both `Scalar[Float32]` and `DType.float32` (only `Float32` itself
answers `float`), so `Array[Scalar[dtype], N]` cannot recover its element type
from the annotation it is written with.

## Expected

1. `Array[T, N]` construction should produce a real list/array value with its
   element C type tracked (`_elem_types`), like the `List(...)` constructor
   arm in `_lower_call` does — and, for `fill=`/`N`, initialize `N` elements.
2. `Span(<that value>)` should inherit the element type (the `_span_list` arm
   already does this when the source is a tracked `MojoList *`).
3. A SIMD value should keep its scalar dtype (or at least enough of it for
   `c_to_mojo` to answer `Float32`/`Float64` rather than `Int64`);
   `SIMD[.float32, N](...)` is currently lowered by the plain call path.
4. `_resolve_type` should resolve `Scalar[X]` (i.e. `SIMD[X, 1]`) to the
   scalar C type of `X`, including when `X` is a `comptime` local bound to
   `DType.float32`/`float64`.

## Exact next step

Start with (1): in `mojo/backend_gimple/emit_calls.py::_lower_call`'s
"Generic container constructors" arm, add an `Array`/`FixedSizeArray` branch
that builds `mojo_list_new()` (or the array runtime the stdlib dylib already
uses) and records `gen._elem_types[t]` from the bracket's first type argument
via `_annotation_container_elem_type(gen, 'Array[%s]' % ann, 'MojoList *')`.
Then re-run the probe above and confirm the emitted C reads
`mojo_list_get_double` for `Array[Float32, 4]` (or get_float once (3) lands),
and re-run the two tests named in "Landed". Byte-identical generated C is NOT
expected here (this is a real representation change), so gate it with the
`test/math` files plus `test_codegen_local_bindings_cache.py`.
