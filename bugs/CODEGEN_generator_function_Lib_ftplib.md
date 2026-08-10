# CODEGEN_generator_function: Lib/ftplib.py

## Status (updated 2026-08-09, re-verified — reproduces identically)

**STILL FAILING**, re-confirmed against current master (fast-forwarded
to `dd7c7c6`). Identical repro to the 2026-08-07 entry below:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
[gimple_codegen] generator method FTP.'mlsd' not eligible for C++ coroutine path, falling back to honest refusal: mlsd: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) mlsd (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: tuple-valued `yield`** — the well-known,
already-catalogued C++20-coroutine-promise scope boundary (the promise
only carries a single scalar `int64_t`/`double`/`_Bool`; there is no
representation for a tuple/struct value crossing a suspend point), same
family as `bugs/CODEGEN_generator_function_Lib_dis.md`'s
`_unpack_opargs`/`findlinestarts`/`_find_imports` case. `FTP.mlsd`'s
body does `yield (name, entry)` — a 2-tuple `(str, dict)` — and
`_gen_cpp_generator_unit`'s value-type check only accepts a single
scalar type across every `yield` in the function, so a tuple-yielding
generator is refused outright. Because this is ftplib.py's only
generator and it's module-level-reachable (an `FTP` instance method),
the refusal escalates to a fatal whole-module `RuntimeError` for the
CLI's `mojo.py build` path (the error text's claimed graceful fallback
isn't actually taken for the root file being built).

(Note: the sibling struct-typed-*parameter* refusal this doc's older
entries below cross-reference — `bugs/hard/CODEGEN_generator_struct_
typed_param_refused.md`, task #147 — is now fixed, commit `5d22b29`,
and that doc has since been removed per project convention. That fix
is unrelated to `mlsd`'s failure here, which is about the yielded
VALUE's type, not a parameter's.)

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
