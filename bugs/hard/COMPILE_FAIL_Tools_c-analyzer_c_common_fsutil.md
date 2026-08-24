# COMPILE_FAIL (hard): Tools/c-analyzer/c_common/fsutil.py

## Status (re-verified 2026-08-23, unchanged)

Re-ran against current master tip (`626f3f0`): identical outcome to the
2026-08-20 update below. `iter_files` is still refused for exactly the
same reason — its `get_files = (lambda *a, **k: _walk(*a, walk=_files,
**k))` is a parameterized `*args`/`**kwargs`-forwarding lambda, which
the (real, but deliberately narrow) zero-arg/single-plain-param lambda
support does not attempt:

```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: a `lambda` with more than one
parameter, a `*`/`**`-forwarding parameter, or a parameter default is
not supported as a value inside a compiled generator/coroutine body
(only a zero-argument lambda or a single plain-parameter lambda, e.g.
`lambda: None` / `lambda x: x`, is supported)
Error building: cannot compile module: function(s) iter_files ...
```

The whole-module pre-check aborts at `iter_files`, so
`process_filenames`'s 4-tuple yield (second documented blocker) is not
re-flagged this run — presumably still present behind it, unverified.
Both gaps remain structural per the analysis below; no code change —
doc re-verified only.

## Status (updated 2026-08-20, LambdaExpr blocker narrowed, NOT closed for this file)

`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` has been fixed
for a ZERO-ARGUMENT `lambda` literal / a bound-method-as-VALUE read off
a struct whose real methods are statically known (see that doc's own
2026-08-20 update for the mechanism — a `std::function<int64_t()>`
declared-type category, a native-capturing-C++-lambda `LambdaExpr`
case, and a bound-method case reusing the struct's already-known
mangled method symbol). `iter_files`'s own occurrence does NOT qualify:
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
is a lambda WITH parameters (`*a, **k`), which the fix deliberately
does not attempt — its one declared-type category has a fixed
zero-argument signature (this project's real corpus, both confirmed
`CODEGEN_generator_lambda_expr_unsupported.md` occurrences, only ever
needed 0-arg callables; a `*args`/`**kwargs`-forwarding lambda would
also need the separate, deliberately-unfixed `bugs/hard/CODEGEN_args_
kwargs_signature_assumed_forwarding_only.md` gap even if a parameterized
lambda itself were supported). Re-verified directly via `MOJO_DEBUG=1` +
`compile_to_gimple_with_cpp`: `iter_files` is still refused, now with a
more precise message confirming exactly this:
```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: a `lambda` with parameters is not
supported as a value inside a compiled generator/coroutine body (only a
zero-argument lambda, e.g. `lambda: None`, is supported)
```
`process_filenames`'s separate tuple-valued-yield blocker (below) is
unaffected/unchanged. Net: this file remains blocked by the same two
structural gaps as the 2026-08-09 update — LambdaExpr support is now
real for one shape but not the shape THIS file needs, and tuple-valued
yield is untouched.

## Status (updated 2026-08-09, re-verified: TWO blockers now, both known structural gaps)

Re-verified fresh via `MOJO_DEBUG=1 python3 mojo.py build`. `iter_files`
still hits the exact same `LambdaExpr`-in-generator-body blocker as the
2026-08-07 finding below (`unsupported expression in generator body:
LambdaExpr`) — unchanged, still tracked at
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`, still not a
narrow fix (see that doc's "feature-sized" writeup).

Additionally, the module-level generator pre-check now also flags a
SECOND generator in this same file, `process_filenames` (line 151):

```
[gimple_codegen] generator 'process_filenames' not eligible for C++
coroutine path, falling back to honest refusal: process_filenames:
every `yield` must carry a value, and all values must agree on one
scalar type (int64_t/double/_Bool)
```

Its body is `yield filename, relfile, check, solo` — a 4-tuple-valued
`yield`. This is a confirmed instance of the OTHER already-known,
already-catalogued structural gap for this session ("Tuple-valued
`yield` in a generator (structural, no fix)" — the compiled generator
coroutine path only supports a single scalar-typed value per `yield`,
not a tuple). Not attempted, per that gap's established structural
classification.

Net effect: this file is blocked by TWO independent, already-
catalogued structural gaps (tuple-valued yield + LambdaExpr-in-
generator-body), neither narrow, neither attempted here. The file will
not compile until BOTH are addressed (a real generator-coroutine
tuple-value-carrying mechanism, and real LambdaExpr support inside a
compiled generator body) — both feature-sized efforts, not one-spot
fixes.

## Status (updated 2026-08-07, LambdaExpr blocker root-caused, feature-sized, doc written)

The `LambdaExpr` blocker noted just below (`get_files = (lambda *a,
**k: _walk(*a, walk=_files, **k))`) has now been root-caused and
folded into a proper hard-bug doc:
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` (2 confirmed
occurrences — this file and `Lib/pickletools.py`'s `_genops`).
Investigated and found to be feature-sized, not a narrow fix — see
that doc's "Why this is feature-sized, not narrow" section. Not
attempted here. This file's `iter_files` remains refused.

## Status (updated 2026-08-07)

**NOT resolved** (task #140), despite the root-cause bug this doc
points to (`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.
md`, task #138) now being FIXED. Confirmed via `MOJO_DEBUG=1`: `iter_
files` is no longer blocked by the arg-forwarding/self-recursion gap —
but this file STILL fails to compile, now hitting a DIFFERENT, genuinely
separate, previously-MASKED blocker in the same function:
```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: unsupported expression in
generator body: LambdaExpr
```
`iter_files`'s own body (line 285 of the real file) has:
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
a lambda expression (with its own `*args`/`**kwargs` forwarding)
assigned to a local — entirely unrelated to yield-from/self-recursion,
and out of this narrow generator-body codegen's scope on its own
merits. This was always there; the arg-forwarding bug just refused
`iter_files` earlier (via the blanket whole-module pre-check) before
ever reaching this line. Not investigated/fixed further — a distinct,
new potential hard-bug candidate (LambdaExpr support inside a compiled
generator body) for a future session, not in scope for task #138's fix.

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`

Root cause (current): see
`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md` in this
directory (that file has the minimal test case). Summary: `iter_files` is a
generator using a recursive `yield from iter_files(...)` call with
keyword-only parameters; this file hits a blanket "generator not supported"
pre-check and fails to compile before even reaching the C++ coroutine
codegen.

**This is NOT the bug originally reported here.** The original report
(below, preserved for history) was about `create_backup`'s `exc.filename`
attribute access ("request for member 'filename' in something not a
structure or union"). That specific error **no longer reproduces** — the
generator pre-check above now fires first and blocks the whole module
before `create_backup` is ever reached, masking whatever the original
symptom's current status actually is (fixed or still-latent — unconfirmed
either way).

## Current error (2026-08-05, after commit 12ff719)

```
$ python3 mojo.py build Tools/c-analyzer/c_common/fsutil.py
Error building: cannot compile module: function(s) iter_files (generator function(s), contain a `yield`/`yield from`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
```

Exit code: 1 (despite the message claiming a fallback, `mojo.py build`
does not actually fall back — no object file is produced).

## Original report (2026-07-xx, superseded — kept for history)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function 'create_backup_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:44:14: error: request for member 'filename' in something not a structure or union
   44 |         return os.path.abspath(filename)
      |              ^~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:47:8: error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   47 |     return _fix_filename(filename, relroot)
      |        ^
```

(Both the reported line and error text as they existed then; the file
compiled far enough to reach `create_backup`/`fix_filename` at that time,
which is no longer the case now that the generator check blocks it
earlier.)
