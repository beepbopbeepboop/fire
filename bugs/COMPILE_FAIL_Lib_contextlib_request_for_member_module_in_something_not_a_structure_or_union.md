# COMPILE_FAIL: Lib/contextlib.py — blocked on the async/coroutine codegen (title STALE)

## Status 2026-10-01 — re-measured, unchanged, and the two causes are now bounded separately

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py`
on this tree: **exit 1**, and the refusal names exactly the two functions and
the two per-function reasons the 2026-09-30 entry recorded:

```
cannot compile module: function(s) __aexit__, __aexit__, _exit_wrapper, inner
(async function(s), declared `async def`) -- ... Unsupported shape(s):
  __aenter__: every `return` must carry a scalar value
  __aexit__ : *args/**kwargs parameters not supported for compiled async functions
```

Nothing moved, and nothing in this session's work touched
`mojo/backend_gimple/cpp_async.py`'s async eligibility gate.

The title remains STALE (the `request for member '__module__'` error it is
named after stopped being this file's blocker long before 2026-08-06, as this
doc's own history says); it is kept rather than renamed because the bug — this
file does not compile — is real, and a doc whose title is wrong is still worth
more than a doc that has to be re-found.

### What is actually needed, sized

Both causes are in `cpp_async.py`'s coroutine codegen, and they are
independent, which the single refusal message hides:

1. **`__aenter__` returning a non-scalar.** An async context manager's
   `__aenter__` must return something. The coroutine's promise slot is
   typed by `_generator_yield_ctype`'s scalar lattice, so there is nowhere to
   put a `MojoAsync *` or a `MojoList *`. Fixing it means a BOXED return slot
   plus dynamic read-back at every consumer — the same
   `_actual_types`-vs-static-type problem as
   `identifier-field-key identity`, one level up.
2. **`*args`/`**kwargs` in a coroutine frame.** `_exit_wrapper` and
   `__aexit__` take them, and the frame has fixed slots. This is genuinely a
   new capability (a variable-arity coroutine), not a missing branch.

Neither is a narrow fix; neither is related to imports, decorators or symbol
qualification, which is what this doc was originally filed under.

## Status (2026-09-30 — rewritten; not an import-qualifier bug, not attempted)

Its current blocker is NOT an import/qualifier problem and not the one
in the title: it is the async/coroutine codegen. The refusal is raised from
`mojo/backend_gimple/module_gen.py`'s async-function eligibility gate
("cannot compile module: function(s) ... (async function(s), declared
`async def`)"), and the per-function reasons are emitted verbatim by
`mojo/backend_gimple/cpp_async.py` — `__aenter__`: "every `return` must
carry a scalar value" (line ~1878) and `__aexit__`: "*args/**kwargs
parameters not supported for compiled async functions" (line ~1616). Both
are still exactly those two messages in the current tree.

That is: non-scalar `__aenter__`-return boxing/type-erasure plus
variadic `__exit_wrapper` parameters in the C++20 coroutine frame — a
genuinely large feature, and not in the decorators/import-qualifiers area
this doc was filed under. Filed here originally for a `request for member
'__module__'` GCC error that stopped happening long before 2026-08-06 (the
title and the original note are STALE, as the 2026-08-06 entry below
already said); the accumulated "re-verified unchanged" entries after that
are what a `bugs/` entry is supposed to stop being, so they are gone.

**Next step** (unchanged in substance, now stated once): extend
`cpp_async.py`'s coroutine codegen to box non-scalar `__aenter__` returns
and to carry `*args`/`**kwargs` in the coroutine frame. Nothing about
imports, decorators or symbol qualification is involved.

## Status 2026-10-29 (second session) — trigger not yet isolated; regression test withdrawn

The earlier 2026-10-29 entry's `test_contextlib_async_regression.py` was a
tautology: it built the refusal string itself and asserted substrings of that
literal, so it could never fail and proved nothing about the compiler. It is
deleted. Nothing in this session changed `mojo/backend_gimple/`.

What this session measured:

- In-process `gimple_codegen.compile_to_gimple_with_cpp` ACCEPTS each of these
  without refusing (`.tmp`-only probes, not committed):
  - `async def __aenter__(self) -> String: return "hi"` in a struct
    (called and uncalled);
  - `async def __aexit__(self, *exc_details): pass` in a struct (called and not);
  - `async def f(*args): pass` (called and not).
  So the two refusals in `cpp_async.py` (~1921 and ~1652/2891) are NOT reached
  through that entry point for these shapes. Do not treat `compile_to_gimple_with_cpp`
  acceptance as evidence the shapes compile correctly: it is the same
  silent-eager-execution entry point `test_gimple_async_runner.py` documents.
- The refusal that matters is raised by `mojo/backend_gimple/module_gen.py`
  ~line 11190 (`cannot compile module: ...`), which runs only on the
  `relaxed_imports=False` path of a whole-module compile. The tiny `fire.py build`
  repros built fine, but a combined repro (`fire.py build` of a file with
  `async def __aenter__`, `__aexit__(*exc_details)`, and `async def f(*args)`
  all called) pulled in the stdlib dylib build, which fails on unrelated
  `mojo_raise_zero_division` goto errors in `std/benchmark/*.mojo`
  (`benchmark.mojo:218`, `_progress.mojo:85`, `span.mojo:916`). That build finished with exit 1 and
  NO `cannot compile module` line, so the module_gen refusal was not hit. Its
  real error is a C arity mismatch at the call site: `.tmp/repro/called.mojo:510:9:
  error: too many arguments to function '__mgco_Box___aexit___start'; expected 2,
  have 3` -- a call `await b.__aexit__(1, 2, 3)` to a `*exc_details` async method
  is lowered with the caller's three arguments against a 2-parameter start
  function. This is a separate defect, filed here because it is on the same
  variadic-async path: a call site to a variadic coroutine must pack the extra
  arguments the same way the callee's frame does. Start by reading the
  `__mgco_..._start` emission in `cpp_async.py` and the call lowering that
  supplies its argument list.

Next step (exact, in order):
0. Minimal reproducer for the arity defect above is `Box` with
   `async def __aexit__(self, *exc_details)` called as `await b.__aexit__(1, 2, 3)`.
1. Find the minimal refused shape through the `module_gen.py` path: call the
   module generator directly on the source (not `fire.py build`, which drags in
   the stdlib dylib), on a copy of `Lib/contextlib.py` reduced one function at a
   time, and bisect until the refusal message is produced by one function. Record
   the minimal source in this doc.
2. Only then write the regression test: it calls that same entry point on that
   minimal source and asserts the refusal is ABSENT. It must fail before the fix.
3. The fix itself is still the two `cpp_async.py` extensions described in the
   2026-10-29 plan below (boxed non-scalar `__aenter__` return; variadic
   `*args`/`**kwargs` in the coroutine frame). Neither is started.

## Status 2026-10-29 — planning/design round (first session; plan still valid in substance)

Implementation plan (ordered):
1. `cpp_async.py`: add boxed-return branch in `_generator_yield_ctype`-related scalar lattice, emitting a `MojoAsync*` / box slot for `__aenter__`, with read-back at every consumer.
2. `cpp_async.py`: extend coroutine frame slot table to carry `*args`/`**kwargs` (variable-arity), updating `_exit_wrapper` frame init.
3. After (1)+(2), rebuild and verify `Lib/contextlib.py` compiles clean; then delete this doc with `python3 tools/dangling_doc_refs.py --ratchet`.
