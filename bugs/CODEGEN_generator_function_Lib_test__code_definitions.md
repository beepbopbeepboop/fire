# CODEGEN_generator_function: Lib/test/_code_definitions.py

## Status (updated 2026-08-23 — STILL-OPEN)

Re-ran the repro against this branch: byte-for-byte identical refusal
(`asyncgen_spam: *args/**kwargs parameters not supported for compiled
async generators`). Nothing in this pass touched async-generator
eligibility; classification unchanged (feature-sized: varargs widening +
first-class non-consumed construction). Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-11)

Re-verified against current master; reproduces identically:
```
[gimple_codegen] async generator 'asyncgen_spam' not eligible for C++
coroutine path, falling back to honest refusal: asyncgen_spam:
*args/**kwargs parameters not supported for compiled async generators
```

Attempted a real fix this session: widen `_gen_cpp_async_generator_unit`
(`gimple_codegen.py:28385`) to accept a single `*args` parameter as a
`MojoList *`, mirroring the existing convention ordinary (non-async,
non-generator) compiled functions already use for varargs (see the
`has_varargs`/`seen_varargs` handling around `gimple_codegen.py:22879`).
The method's own docstring already states a hand-written, Mojo-
independent GCC-15 repro confirmed real parameters are SAFE with this
promise shape ("Scope is kept parameter-less anyway... not because the
repro found trouble, but because there is no need to widen scope") — so
the refusal itself isn't protecting against a known-unsafe shape.

**Hit a deeper, concrete blocker that makes the `*args` refusal moot
either way**: `_code_definitions.py`'s actual use of `asyncgen_spam` is
`asynccoro_spam = asyncgen_spam(1, 2, 3)` — a bare MODULE-LEVEL call
that constructs the async-generator object but never consumes it via
`async for` (real Python semantics: calling an async-generator function
just returns the object; no body executes until iterated — this file
never iterates it, just stores it in a list, `FUNCTION_LIKE_APPLIED`).
Confirmed via a minimal, `*args`-free, isolated repro
(`async def f(): yield 1` / `x = f()` at module level, zero parameters,
the exact shape this doc's OWN already-passing `test_gimple.py` case
"async_generator_no_consumer_still_compiles_as_dead_code" claims to
cover) that this bare-construction-without-consumption shape has **no
codegen support at all**: `x = f()` fails with `implicit declaration of
function 'f'` — `self._async_gen_api` (populated once
`_gen_cpp_async_generator_unit` succeeds) is only ever READ from one
site in the whole file (`gimple_codegen.py:26060`, inside the `async
for` consumption lowering) — there is no lowering path for a plain
assignment/expression statement that merely constructs an async-
generator value without immediately iterating it. (The existing
passing test's function `f` is genuinely unreferenced anywhere in that
test's source — "no consumer" there means "never called at all", not
"called but not iterated": a materially different, easier shape.)

This matches this session's already-confirmed structural gap class: "an
opaque callable/generator VALUE (constructed but not immediately
consumed) has no representation" in this codegen's type model — giving
async-generator objects a real first-class value representation
(storable in a variable/list, consumable later or never) is a design-
level project (a whole new value-representation + lifetime story for a
coroutine handle), not a narrow stub gap. Even if the `*args` refusal
were lifted (harmless on its own — no regression risk, kept as a
genuine partial improvement), THIS file's actual call shape would still
fail on the separate, deeper "bare non-consumed construction" gap.
**No code change made** — traced how far the `*args` widening alone
would go (design-level, in `_gen_cpp_async_generator_unit`'s param loop)
but stopped short of implementing it: it wouldn't move this file's build
forward on its own (the deeper "bare non-consumed construction" gap
above blocks it regardless), and implementing it partially — without
also building call-site vararg-packing for async-generator constructors,
never done anywhere in this codegen — would add unverified surface area
for no observable gain. Doc kept open, not deleted.

## Status (updated 2026-08-09)

Re-verified against current master with a fresh real rebuild
(`MOJO_DEBUG=1 python3 mojo.py build .../Lib/test/_code_definitions.py`,
real `gcc-mp-15`/`g++-mp-15` via `mojo.py`'s own resolution). Reproduces
byte-for-byte identically to the 2026-08-06 note below, same message,
same `RuntimeError`:
```
[gimple_codegen] async generator 'asyncgen_spam' not eligible for C++ coroutine path, falling back to honest refusal: asyncgen_spam: *args/**kwargs parameters not supported for compiled async generators
Error building: cannot compile module: function(s) asyncgen_spam (async generator function(s), ...) — falling back to interpreting this module from source instead
```
Confirmed by reading `_gen_cpp_async_generator_unit`
(`gimple_codegen.py:27322`) directly: the `*args`/`**kwargs` refusal is
unconditional and, per that method's own docstring, DELIBERATE — a
documented scope boundary ("Scope is kept parameter-less anyway... not
because the repro found trouble, but because there is no need to widen
scope beyond this step's one target shape... to close out the project"),
not an oversight. This is correctly classified as a known,
intentionally-scoped structural gap (the same family as
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`), not a
narrow bug — no code change made in this pass.

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a more specific reason than the 2026-07-30 note.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py
[gimple_codegen] async generator 'asyncgen_spam' not eligible for C++ coroutine path, falling back to honest refusal: asyncgen_spam: *args/**kwargs parameters not supported for compiled async generators
Error building: cannot compile module: function(s) asyncgen_spam (async generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause:**
```python
async def asyncgen_spam(*args):
    for arg in args:
        yield arg
```
`asyncgen_spam` is an ASYNC generator (`async def` + `yield`) whose only
parameter is `*args`. The async-generator codegen step
(`_gen_cpp_async_generator_unit`) explicitly refuses `*args`/`**kwargs`
parameters outright (same deliberate scope boundary already documented
for plain generators and plain async functions in
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md` — that doc's
title says "struct-typed" but the underlying mechanism/scope-limit family
is the same: `_gen_cpp_generator_unit`/`_gen_cpp_async_unit`/
`_gen_cpp_async_generator_unit` all independently refuse any parameter
shape outside a fixed scalar/container allow-list, and `*args`/`**kwargs`
are refused unconditionally regardless of what's actually inside them).
As with the other member of this family, refusing a module-level
generator escalates to a fatal whole-module `RuntimeError`.

Not folded into the existing hard-bug doc's title/scope in this pass
(that doc is scoped to the struct-typed-parameter case specifically) —
flagged here as a confirmed second trigger of the same underlying
"coroutine codegen's parameter-shape allow-list is narrower than the
scalar/container types themselves" family; worth either broadening that
hard-bug doc's scope or spinning off a sibling doc
(`CODEGEN_generator_varargs_param_refused.md`) if a third instance
turns up.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py
