# CODEGEN_generator_function: Lib/dis.py

## Status (updated 2026-08-10 — tuple-yield now FIXED, a separate pre-existing `_cpp_for_stmt` gap found+fixed too; file still doesn't build)

Re-verified against current master. The tuple-valued-`yield` fix landed
earlier this session (`_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`, boxes a tuple yield into a real runtime `MojoList *`) resolves
the "every `yield` must carry a value..." refusal this doc's 2026-08-09
status documented for `_unpack_opargs`/`findlinestarts`/`_find_imports`
— confirmed via `MOJO_DEBUG=1 python3 mojo.py build .../Lib/dis.py`: none
of the three appear in the refusal list anymore.

**Found and fixed a SEPARATE, pre-existing bug this exposed**: dis.py's
`_get_instructions_bytes` and `_find_store_names` each consume
`_unpack_opargs` (a real tuple-yielding generator) via a PLAIN
(non-`yield from`) `for` loop —
```python
for offset, start_offset, op, arg in _unpack_opargs(original_code):   # _get_instructions_bytes
for _, _, op, arg in _unpack_opargs(co.co_code):                       # _find_store_names
```
`gimple_codegen.py`'s coroutine-body `for`-loop lowering (`_cpp_for_stmt`)
had no case at all for "iterable is a call to another compiled
generator" — only `enumerate(...)` got real tuple-target handling, and
the generic fallback treated a non-`enumerate` tuple target as one bogus
comma-joined C++ identifier (`for (auto offset, start_offset, op, arg :
...)` — invalid C++) while also calling the callee through the wrong
(non-coroutine) extern "C" stub gen_module's "unknown module-level
symbol" preamble falls back to for an unrecognized callee. Also
independently confirmed as the SAME gap in `calendar.py`'s and
`weakref.py`'s own generators (see those docs) — this was a real, shared,
previously-undocumented `_cpp_for_stmt` limitation, not the tuple-yield
promise/ABI gap the earlier fix targeted.

**Fixed**: new `_cpp_for_generator_delegate` (`gimple_codegen.py`) drives
the sub-generator via its own `<base>_start/_resume/_value/_destroy` API
— the same calling convention and `_mojogen_sub_guard` RAII cleanup
`_cpp_yield_from`'s existing `yield from`-delegation already uses —
assigning each produced value into the loop target(s) (tuple-unpacked via
the same `MojoList*`-of-boxed-elements convention `_cpp_yield_tuple`/
`_emit_generator_tuple_unpack` already established) instead of
re-`co_yield`ing it. Source-order dependency (`_unpack_opargs` is defined
AFTER its callers in dis.py's real source) is handled the same way
`yield from` already handles it: a new `self._all_generator_names`
(every generator name in the module, computed once up front) lets the
new code tell "real generator, just not compiled yet" apart from "not a
generator at all", raising `_UnsupportedGeneratorShape` for the former so
gen_module's existing multi-pass retry loop picks the caller back up once
the callee is compiled.

Verified via an isolated compile: both `_unpack_opargs`-consuming
for-loops now lower through the correct `_mojogen_` API and are free of
the previous errors. Also verified END-TO-END with a standalone
compiled-and-run test program (a `for a, b in <2-tuple generator>():`
loop, a `for a, b, c in <3-tuple generator>():` loop, and an early
`break` mid-loop) — all produced the correct runtime values. Commit:
`5d8839d`.

**dis.py as a whole still does not build** — separate, unrelated gaps
remain, confirmed via a fresh isolated compile + `g++ -fsyntax-only`
after the fix (58 → 54 errors; the specific `_unpack_opargs`-for-loop
error clusters are gone, everything else is pre-existing/unrelated):
- `findlinestarts`: `for start, end, line in code.co_lines():` — a
  method call on a real Python `code` object, which this codegen has no
  native representation for at all (unrelated feature: code-object
  introspection).
- `_find_imports`: `opargs = [(op, arg) for _, _, op, arg in
  _unpack_opargs(...) if op != EXTENDED_ARG]` (a list comprehension with
  tuple-target unpack over a generator call, a DIFFERENT emission path
  from the plain-`for`-statement one just fixed) followed by
  `for i, (op, oparg) in enumerate(opargs):` — a NESTED tuple target
  inside `enumerate()`, which the existing enumage-handling branch (flat
  2-name unpack only) doesn't support either.
- Module-level dict globals (`opmap`) and the `code`/`co` parameter's real
  type aren't resolved inside a coroutine body in several of these
  functions, producing `'opmap' was not declared in this scope`-style
  errors independent of the for-loop shape.
- The whole-program (`do_imports=True`) build was already failing for
  hundreds of unrelated pre-existing errors in transitively-imported
  files before reaching dis.py's own coroutine compile at all (same
  pattern already documented for `calendar.py`/`codecs.py`) — the
  whole-program error count (500) is unchanged before/after this fix,
  confirming it wasn't reaching this stage either way.

Doc kept open — real progress made and independently verified, but
dis.py genuinely still doesn't build, for the separate reasons above.

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
