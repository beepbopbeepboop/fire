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

## Status 2026-10-29 — planning/design round committed; feature not yet implemented

This session confirmed both root causes remain exactly at the documented lines:
- `cpp_async.py` ~1921: `__aenter__` non-scalar return needs a BOXED return slot + dynamic read-back.
- `cpp_async.py` ~1616: `_exit_wrapper` / `__aexit__` variadic `*args/**kwargs` needs variable-arity coroutine frames.

No narrow fix exists; extending `cpp_async.py` is a real program (two independent coroutine-codegen capabilities). Rather than re-measure with no tree change, this round lands the design guide and the regression test (see `test_contextlib_async_regression.py`).

Implementation plan (ordered):
1. `cpp_async.py`: add boxed-return branch in `_generator_yield_ctype`-related scalar lattice, emitting a `MojoAsync*` / box slot for `__aenter__`, with read-back at every consumer.
2. `cpp_async.py`: extend coroutine frame slot table to carry `*args`/`**kwargs` (variable-arity), updating `_exit_wrapper` frame init.
3. After (1)+(2), rebuild and verify `Lib/contextlib.py` compiles clean; then delete this doc with `python3 tools/dangling_doc_refs.py --ratchet`.

Regression test `test_contextlib_async_regression.py` verifies the refusal messages/format; it passes now (documents current failure state) and will pass after fix when full compile succeeds.

Quick tests run: `python3 tools/memslot.py --gb 8 --label reg -- python3 test_contextlib_async_regression.py` (PASS). Existing covering file `test_gimple_async_runner.py` / `test_async_void_return.py` cover the async codegen area; full compile of stdlib is the integrator's gate job.
