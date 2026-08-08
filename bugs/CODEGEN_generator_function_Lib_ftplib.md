# CODEGEN_generator_function: Lib/ftplib.py

## Status (updated 2026-08-07)

**STILL FAILING**, re-diagnosed again against current master — the
2026-08-06 note's claim that `mlsd` "now appears to compile cleanly
through the coroutine path" was WRONG (most likely an artifact of that
prior check looking at the wrong error stream/module during a
transitive-closure build, since the `MOJO_DEBUG=1` refusal line is
unambiguous once you isolate `ftplib.py`'s own build). Fresh repro:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
[gimple_codegen] generator method FTP.'mlsd' not eligible for C++ coroutine path, falling back to honest refusal: mlsd: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) mlsd (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: `bugs/hard/CODEGEN_generator_struct_typed_param_
refused.md`'s family** (the general "coroutine codegen's scalar/
container-only allow-list" scope boundary — that doc's title says
"struct-typed PARAMETER" but the same family also covers the yielded
VALUE's type, as documented in that doc and in
`CODEGEN_generator_function_Lib_test__code_definitions.md`'s note about
a third instance). `FTP.mlsd`'s body does `yield (name, entry)` — a
2-tuple `(str, dict)` — and `_gen_cpp_generator_unit`'s value-type
check only accepts a single scalar type (`int64_t`/`double`/`_Bool`)
across every `yield` in the function, so a tuple-yielding generator is
refused outright. Because this is ftplib.py's only generator and it's
module-level-reachable (an `FTP` instance method), the refusal
escalates to a fatal whole-module `RuntimeError` for the CLI's `mojo.py
build` path (same "message claims graceful fallback, doesn't actually
take it for the root file" gap documented in the struct-typed-param
doc's Symptom section).

The previously-reported `test.__doc__` "invalid use of void expression"
error (line 926) was real at the time but is no longer what blocks this
file — `mlsd`'s refusal happens first, before that code is ever
reached. Not re-verified whether the `__doc__` issue is separately
fixed or still latent; moot until `mlsd`'s tuple-yield limitation is
addressed.

Not fixed here — this is the same genuine, already-assessed
feature-sized coroutine-codegen scope boundary as task #147
(`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`), which
this session's assignment explicitly holds back from further attempts.
Widening the C++20 coroutine promise type to carry a tuple/struct value
across suspend points (rather than a single scalar) is a real feature,
not a narrow bug fix.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
