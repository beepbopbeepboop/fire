SPLIT: COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union-part2, COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union-part3 (part1 fixed: variadic async `__aexit__` start-call packing, pinned by `test_asyncio_run_module_scope_regress.py::variadic_aexit_awaited_in_main`)
# COMPILE_FAIL: Lib/contextlib.py — blocked on the async/coroutine codegen (title STALE)

## Status 2026-11-19 -- order-dependence in async-method eligibility fixed; the remaining three are the dynamic-await wall

Landed: `mojo/middle/coro.py::lower` built `_ASYNC_METHOD_NAMES` in ONE
source-order pass, but whether an async method is eligible depends on that
set (`await self.thing.aclose()` is only accepted once `aclose` is a known
compiled async method). A method was therefore judged against only the async
methods defined before it, so `AsyncClosing.__aexit__` (line 389, awaits
`.aclose()`) was refused because `AsyncExitStack.aclose` sits later in the
file. It is now a fixpoint (names only grow, so it terminates). Pinned by
`async_method_awaits_later_defined_async_method` in
`test_gimple_generator_runner.py`. Measured on `Lib/contextlib.py` through
`compile_to_gimple_with_cpp`: the refusal list went from
`__aexit__, __aexit__, _exit_wrapper, inner` to `__aexit__, _exit_wrapper, inner`.

Measured reasons for the three that remain (A3 `_eligible_async*` and
`_async_awaits_ok`/`_await_stmt_ok` in `mojo/middle/coro.py`); all are the same
wall, an `await` of an object whose type is dynamic:

- `_GeneratorContextManager`-async `__aexit__` (line 218):
  `await anext(self.gen)`, `await self.gen.athrow(value)`,
  `await self.gen.aclose()` -- `self.gen` is whatever `func(*args, **kwds)`
  returned (an async generator object of unknown type), plus try/except/else/
  finally with awaits in the handlers.
- `inner` (line 99) / `_exit_wrapper` (line 650): `await func(*args, **kwds)`
  / `await callback(*args, **kwds)` where the callee is a PARAMETER. Even the
  minimal `def mk(cb, x): async def w(): await cb(x)` is refused
  (`_await_stmt_ok` only accepts a known async name, a handle, or a method
  whose name is a compiled async method), and `*args, **kwds` forwarding needs a
  variable-arity call through a function value, which the C ABI of
  `__mgco_<f>_start` (fixed scalar parameters) cannot express.

Next step (needs a design decision, not more probing): a first-class
async-callable value -- a boxed callable whose call takes `(MojoList *args,
MojoDict *kwds)` and returns a coroutine handle, with a matching dynamic
await on a handle of statically unknown kind. Until that exists, contextlib's
async half cannot compile; that is the whole remaining blocker.

## Status 2026-10-29 (third session) — the call-arity defect landed; the doc stays open

Landed (partial, real behaviour change): a call to a coroutine or generator
with a `*args` parameter now packs its positional arguments into the `*args`
list. Before, the packing was missing at every call site:

- `gen(1, 2, 3)` against `def gen(*xs)` passed the arguments flat, a C "too
  many arguments" error. Now packed (`_pack_generator_star_args`,
  `_generator_star_slot` in `mojo/backend_gimple/emit_calls.py`; the method
  site in `emit_methods.py`).
- `await f(1, 2, 3)` / `async for x in f(...)` lowers to `__mgco_<f>_start`,
  which the api registry (keyed by source name) did not find, so it fell
  through to an ordinary call and passed `1` alone, silently. Now resolved by
  the api's `base` (`_generator_api_for_start_symbol`).
- The `*args` local was declared `int64_t *xs` (the raw parameter name keeps
  its star, which the C emitter reads as a dereference), so the packed list
  was never read. Fixed in the coroutine prologue (`_local_param_name`,
  `mojo/middle/coro.py`).
- The `*args` element kind now comes from the call-site contract (a
  `('list', kind)` per trailing positional, `_visit_call`), so `str` and
  `double` elements are stored and read with their own accessors.

Regression cases: `run_star_args_call_tests` in
`test_gimple_generator_runner.py` (7 cases). On a clean HEAD export all 7
fail; on this tree all pass. `test_gimple_generator_runner.py` 280/280 and
`test_gimple_async_runner.py` 39/39.

The doc's own step-0 shape now gives the right answer under the default
A3 backend: `async def __aexit__(self, *exc_details)` awaited with three
arguments returns `len(exc_details) + self.n` (`103`, pinned by
`star_args_async_method_aexit_shape`). The arity defect this session filed is
therefore fixed for generators, methods and the await/async-for paths.

NOT verified and NOT done:

- `Lib/contextlib.py` itself was NOT re-built. **Verified 2026-11-17**: it DOES
  still refuse on the default path -- `python3 fire.py build Lib/contextlib.py`
  exits 1 -- but with a DIFFERENT gate than the one recorded here. The
  refusal is now the plain async one:

      RuntimeError: cannot compile module: function(s) __aexit__, __aexit__,
      _exit_wrapper, inner (async function(s), declared `async def`) -- this
      codegen compiles every function into a single straight-line C function
      and has no suspend/resume state-machine transform for generators, nor an
      event loop / suspend-resume codegen for async functions, yet

  not `*args/**kwargs parameters not supported for compiled async functions`.
  So the legacy cpp gate is gone from this path and the shape that stops the
  module is simply `async def` -- which is the same wall as every other
  COMPILE_FAIL_* file here. (The build also reports `unable to locate module
  'nt'` while resolving the import closure; that is a separate module-path
  matter and is not what stops it.)
- Element typing for the `*args` body is still wrong in two ways, both
  separate defects, filed:
  the int-element list-param loop target typed `char *` (arithmetic on an int
  element read a pointer; now fixed, doc deleted), and
  `bugs/CODEGEN_coro_star_args_str_double_elements_yield_as_int.md` (a `str`
  or `double` element is yielded as an int). Neither blocks the packing, but
  any `contextlib` body that does arithmetic or yields a loop element over a
  `*args` parameter will hit them. The contextlib bodies have not been probed
  for that.
- `__aenter__` returning a non-scalar value (the other half of the 2026-10-29
  plan below) is untouched.

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

## Repro (this session)

`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py` still
exits non-zero. Refusal reproduced verbatim:

```
cannot compile module: function(s) __aexit__, __aexit__, _exit_wrapper, inner
(async function(s), declared `async def`) -- this codegen compiles every function
into a single straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen for async
functions, yet, so these cannot be represented as compiled C without emitting
silently wrong or broken code; falling back to interpreting this module from
source instead
```

Blocker unchanged: async/coroutine codegen. No code change attempted this session.
