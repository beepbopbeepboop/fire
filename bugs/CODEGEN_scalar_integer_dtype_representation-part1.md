# CODEGEN: one integer dtype -> C type resolver for `Scalar` / `SIMD` annotations (part 1)

## Goal

Give every integer dtype one C representation and make every
annotation-shaped resolution site answer it, so a `Scalar[DType.X]` value's C
type no longer depends on which spelling the resolver was reached through.

This is the representation half of `bugs/hard/CODEGEN_scalar_integer_dtype_representation.md`;
parts 2 and 3 build on it.

- `mojo/middle/types.py`: replace the float-only table `_SIMD_FLOAT_DTYPE_CTYPE`
  with one dtype table (suggested `_DTYPE_CTYPE`) whose keys are the lowercase
  dtype spellings (`int8` ... `uint64`, `index` -> `int64_t`, `uindex` ->
  `uint64_t`, and the existing `float32`/`float64` entries), absorbing the
  integer entries that today live only in `emit_calls._DTYPE_CAST_CTYPES`.
  `_dtype_token_ctype` keeps normalising every spelling
  it normalises today (tuple, tuple-REPR, `DType.`/`dtype.`/leading dot, bare
  scalar name, `f32`/`f64`) and reads that one table. Its docstring stops saying
  "float".
- `mojo/middle/types.py`: `_simd_float_dtype_ctype` becomes the dtype resolver
  for a bracket (`_simd_dtype_ctype` or similar) and normalises its first
  comma-separated part through `_dtype_token_ctype`, so
  `SIMD[DType.uint32, 4]` resolves. `_mojo_type`'s bracket branch accepts
  `Scalar` alongside `SIMD` (a width-1 SIMD is a scalar; `Scalar[X]` is the
  same type) and resolves `X` through the same helper. That is the pointer
  element fix: `UnsafePointer[Scalar[DType.uint8]]` currently falls through the
  recursive `_mojo_type('Scalar[...]')` to `int64_t` and must answer
  `uint8_t *`. Keep the `SIMD` width validation unchanged.
- `mojo/backend_gimple/emit_calls.py`: delete the second dtype table
  `_DTYPE_CAST_CTYPES` (CLAUDE.md: one table, no duplicate implementation).
  `_dtype_cast_ctype` keeps its `DottedLiteral` / `MemberExpr` shape decoding
  and then calls `gimple_ctypes._dtype_token_ctype`. The `SIMD`/`Scalar`
  constructor arm in `_lcx_generic_ctor` must accept any scalar C type from
  `_CAST_SCALAR_CTYPES` as the constructor's `_target`; today only
  `float`/`double`/`__fp16`/float8 are accepted and every integer falls back to
  `int64_t` (measured: `var a = Scalar[DType.uint8](250)` emits `int64_t a`).
- `_float_dtype_arg_ctype` stays FLOAT-only: it feeds `bitcast[...]` /
  `SIMD[...](from_bits=)`, where an integer target is still the `int64_t` word.
  Filter the shared table by the float C types (and keep the float8 lookup)
  rather than returning the first match.
- `mojo/middle/infra_infer.py:150-209` (`_resolve_type`'s `Scalar`/`SIMD` arm)
  already reads `gimple_ctypes._dtype_token_ctype`; confirm it now resolves the
  integer spellings and needs no second mapping. Its pointer-element arm falls
  through to `_mojo_type`, so the `Scalar` arm above is what makes
  `UnsafePointer[Scalar[...]]` agree with the parameter.

## Acceptance

- The resolver answers every integer dtype and the pointer element:
  `_mojo_type('Scalar[DType.uint8]') == 'uint8_t'`,
  `_mojo_type('Scalar[DType.int16]') == 'int16_t'`,
  `_mojo_type('SIMD[DType.uint32, 4]') == 'uint32_t'`,
  `_mojo_type('UnsafePointer[Scalar[DType.uint8]]') == 'uint8_t *'`;
  `_dtype_token_ctype` answers the same for `DType.uint8`, `.uint8`, `uint8`,
  `UInt8`, `('DType', 'int16')` and the tuple-REPR spelling.
- The doc's repro lowers to one representation in both spellings:
  `_Bool first <=hash> (uint8_t * ctrl, uint8_t target)` (the symbol carries
  the existing module hash suffix; match it with a regex).
- A local `var a = Scalar[DType.uint8](250)` emits `uint8_t a`, and
  `var p = UnsafePointer[Scalar[DType.uint8]].alloc(4)` emits `uint8_t * p`.
- gcc accepts the repro's read-through-the-pointer/compare shape and the
  swisstable/philox shapes when a `struct` with a `var b:
  Scalar[DType.uint8]` field is used and a loop runs `ctrl[i]` over an
  `UnsafePointer[Scalar[DType.uint8]]` (the `gimple_compiles` helper in the
  Done-when test compiles with `gcc -fgimple -fsyntax-only`). This is the
  guard against the measured 53-error disagreement class.
- Floats are unchanged: `_mojo_type('Scalar[DType.float32]') == 'float'`,
  `_mojo_type('SIMD[DType.float64, 2]') == 'double'`, and the float8 refusal
  tests still pass.

## Done when

Add `test_scalar_integer_dtype_resolution()` to `test_gimple.py` (the file's
`gimple_compiles` helper already lowers a source string to C; the function
asserts the resolver answers above, the repro's `uint8_t * ctrl, uint8_t
target` signature, and the `uint8_t` local/pointer declarations) and call it
from that file's `run_tests()` so the registered `gimple` job runs it too. Run,
from the worktree root:

    python3 -c "import test_gimple as t; t.test_scalar_integer_dtype_resolution()"

It prints `PASS` and exits 0.
