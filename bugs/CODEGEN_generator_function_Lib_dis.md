# CODEGEN_generator_function: Lib/dis.py

## Status (updated 2026-08-09, re-diagnosed — root cause changed)

**STILL FAILING, but the symptom described below is now STALE.** The
previously-documented failure (`_get_instructions_bytes`'s `arg_resolver`
struct-typed parameter being refused) is **fixed** — that was
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md` (task #147,
commit `5d22b29`, doc since removed per project convention after the
fix landed). Confirmed: a fresh `MOJO_DEBUG=1` run no longer emits any
"unsupported type ... ArgResolver" refusal, and `_get_instructions_bytes`
itself is never even reached — the build now fails earlier, on three
DIFFERENT generators:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py
[gimple_codegen] generator '_unpack_opargs' not eligible for C++ coroutine path, falling back to honest refusal: _unpack_opargs: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
[gimple_codegen] generator 'findlinestarts' not eligible for C++ coroutine path, falling back to honest refusal: findlinestarts: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
[gimple_codegen] generator '_find_imports' not eligible for C++ coroutine path, falling back to honest refusal: _find_imports: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) _find_imports, _unpack_opargs, findlinestarts (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: tuple-valued `yield`** — this is the well-known,
already-catalogued C++20-coroutine-promise scope boundary (the promise
only carries a single scalar `int64_t`/`double`/`_Bool`; there is no
representation for a tuple/struct value crossing a suspend point), the
same family as `bugs/CODEGEN_generator_function_Lib_ftplib.md`'s `mlsd`
case. Confirmed by reading the exact `yield` sites in
`/Users/mrs/net/Python-3.14.6/Lib/dis.py`:

- `_unpack_opargs` (line 934): `yield (i, i, op, arg)` and
  `yield (i, start_offset, op, arg)` — a 4-tuple.
- `findlinestarts` (line 981): `yield start, line` — a 2-tuple.
- `_find_imports` (line 995): `yield (names[oparg], level, fromlist)` —
  a 3-tuple.

Because this is a module-level (not imported) generator refusal, it
escalates to a fatal whole-module `RuntimeError` for `mojo.py build`'s
CLI path (the error text's claimed graceful fallback isn't actually
taken for the root file being built).

Since these three generators are earlier in the file than
`_get_instructions_bytes`, that function's own struct-typed-parameter
codepath is never reached in the current build; whether it now compiles
cleanly (post the #147 fix) is unverified and moot until the
tuple-yield limitation is addressed.

Not fixed here — this is the same genuine, already-assessed
feature-sized coroutine-codegen scope boundary (widening the C++20
coroutine promise type to carry a tuple/struct value across suspend
points is a real feature, not a narrow bug fix), and per this session's
scope, only narrow/safe fixes clearly outside the shared inference
machinery were in scope for this pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/dis.py
