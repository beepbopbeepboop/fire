# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-09)

Re-verified against current master (fast-forwarded to `bf1ead2`,
after several other sibling `Tools/c-analyzer/` bugs got fixed this
session): still fails, but the failure mode has changed shape since
the 2026-08-06 note — the codegen no longer even reaches
`__init___gen.cpp`/gcc. `gen_module` now detects the unsupported
generator shape up front and refuses cleanly:

```
Error building: cannot compile module: function(s) analyze_decls, check_all
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event loop /
suspend-resume codegen for async functions, yet, so these cannot be
represented as compiled C without emitting silently wrong or broken code;
falling back to interpreting this module from source instead
```

With `MOJO_DEBUG=1` the precise reason surfaces:

```
[gimple_codegen] generator 'analyze_decls' not eligible for C++ coroutine
path, falling back to honest refusal: analyze_decls: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
[gimple_codegen] generator 'check_all' not eligible for C++ coroutine
path, falling back to honest refusal: check_all: every `yield` must carry
a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```

Root-caused precisely this time: `gimple_codegen.py`'s C++20-coroutine
generator lowering (`_gen_cpp_generator_unit`, around line 25667)
computes one shared C scalar type (`int64_t`/`double`/`_Bool`) for
every `yield` in a generator's body via `_generator_yield_ctype`; if
that returns `None` (no single scalar type covers every yielded
value), it raises `_UnsupportedGeneratorShape` and the function is
left uncompilable rather than emitting broken/mismatched C++. Both
`analyze_decls` (`yield decl, resolved` — a 2-tuple) and `check_all`
(`yield data, failure` and `yield None, None` — also 2-tuples) yield
TUPLES, not scalars, so neither is eligible.

This is still the same structural gap the 2026-08-06 note pointed at
(part of the separate, already-tracked compiled-generator/async-codegen
project, tasks #95-135), just now caught earlier and more precisely:
the coroutine promise/value machinery has no representation for a
non-scalar (tuple/object/pointer-pair) yielded value at all — genuinely
needs a whole new value-representation category in the coroutine
codegen, not a local stub or missing-case fill-in. Not attempted here,
per CLAUDE.md's guidance against forcing narrow fixes onto structural
gaps. No code change; doc corrected to match current (more precise,
earlier-failing) behavior only.

```
Error building: cannot compile module: function(s) analyze_decls, check_all
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event loop /
suspend-resume codegen for async functions, yet, so these cannot be
represented as compiled C without emitting silently wrong or broken code;
falling back to interpreting this module from source instead
Traceback (most recent call last):
  File ".../mojo.py", line 314, in build_executable
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(...)
  File ".../gimple_codegen.py", line 30700, in gen_module
    raise RuntimeError(...)
RuntimeError: cannot compile module: function(s) analyze_decls, check_all ...
```

Exit code: 1
