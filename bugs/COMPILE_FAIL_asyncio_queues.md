# COMPILE_FAIL: asyncio/queues.py

## Status (updated 2026-08-26, worktree fix/opencode-group4 — re-verified fresh,
## unchanged; confirmed out of scope as a feature-sized runtime project)

Re-verified fresh. Identical refusal: `function(s) get, join, put (async
function(s), declared async def)` with an EMPTY per-function
"Unsupported shape(s)" suffix — confirming all three are rejected by
`_async_quick_eligible`'s await-shape pre-filter BEFORE any translation
is attempted, exactly as this doc's analysis below describes. The three
bodies await:
- `await putter` / `await getter` — a bare local Future OBJECT
  (`self._get_loop().create_future()`), not any recognized call shape;
- `await self._finished.wait()` — an Event.wait() bound-method call.

Making these eligible requires the real Awaitable protocol in the
compiled async runtime: allocatable Future/Event handles with waiter
queues and cross-coroutine wakeup (`set_result`/`Event.set` resuming a
suspended coroutine) — i.e., a new scheduler primitive alongside the
existing timer queue. That is a feature-sized asyncio-runtime project,
not a compiler-side narrow fix; per this campaign's scope rules it is
explicitly NOT attempted here. Note for a future session: the
generator-side machinery this doc's sibling futures.py needed landed
2026-08-26 (value-carrying generator returns via per-unit extern "C"
`{base}_return_slot` globals — see that doc's 2026-08-26 entry) and is
reusable context for the eventual Task/Future design, but does not
change this file's blocker.

Doc kept open.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, superseded above)

Re-ran an isolated `compile_to_gimple` check fresh (post this session's
4 coroutine-emitter fixes landed for COMPILE_FAIL_Apple___main__.md:
`mojo_c_getenv`/platform/subprocess runtime-call whitelist, zero-arg
`print()`, `char* * int` string-repeat lowering, f-string interpolation
in `_cpp_expr`'s `StringLiteral` case — none touch `_async_quick_
eligible`'s await-shape pre-filter). Confirmed byte-for-byte identical
refusal: `function(s) get, join, put (async function(s), declared
async def)`. See COMPILE_FAIL_asyncio_futures.md's updated entry for
why this file and that one, despite sharing the same async-codegen
subsystem, do NOT share one narrow fix (different mechanisms: this
file is rejected by the pre-filter before ever reaching the promise/
suspension machinery futures.py's gap lives in). Widening
`_async_quick_eligible` to the real `Awaitable` protocol (arbitrary
`await <local Future>` / `await <bound-method call>`) remains
feature-sized; not attempted. Doc kept open.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. The blocker (`get`/`join`/`put`'s `await <local Future>` / `await <bound-method call>` shapes, outside `_async_quick_eligible`'s narrow whitelist) is unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still structural; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/asyncio/queues.py`

## Status (re-verified 2026-08-23 against master 626f3f0 — unchanged, STILL-OPEN structural)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/asyncio/
queues.py` fresh: still fails with the IDENTICAL up-front refusal —
`cannot compile module: function(s) get, join, put (async function(s),
declared async def)`. Unaffected by anything landed since the last
pass (including this cluster's fd909e9, which touches only the
generator-body call fallback, not the async pre-filter): the blocker
remains exactly the `_async_quick_eligible` await-shape whitelist gap
pinned down below — `await <local Future variable>` (`putter`/
`getter`) and `await <bound-method call>` (`self._finished.wait()`)
are still unrecognized await shapes. Generalizing suspension to the
real Awaitable protocol remains a broad shared-machinery change;
not attempted.

## Status (updated 2026-08-06 — historical)

Re-ran; the original doc had an empty error snippet. Current failure is
an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) get, join, put
(async function(s), declared `async def`) — this codegen compiles every
function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

This is an async-function codegen refusal, part of the separate,
already-tracked compiled-generator/async-codegen project (tasks
#95-135) — not investigated further here per that project's scope.

Exit code: 1

### Re-verified 2026-08-09 against master `d3d4c68` — reproduces, precise root cause pinned down

Still reproduces verbatim (same three functions, same message). Read
the actual source (`Lib/asyncio/queues.py`) to find exactly why `get`,
`join`, `put` fail `_async_quick_eligible` (`gimple_codegen.py` ~line
2205), since `MOJO_DEBUG=1` gives nothing more here — the module-level
pre-filter rejects the function before `_gen_cpp_async_unit` (which is
what emits `MOJO_DEBUG` notes) is ever attempted:

```python
async def put(self, item):
    while self.full():
        ...
        putter = self._get_loop().create_future()
        self._putters.append(putter)
        try:
            await putter                # <-- awaits a bare local Future variable
        except:
            ...

async def get(self):
    while self.empty():
        ...
        getter = self._get_loop().create_future()
        self._getters.append(getter)
        try:
            await getter                # <-- same shape
        except:
            ...

async def join(self):
    if self._unfinished_tasks > 0:
        await self._finished.wait()     # <-- awaits a bound method call
```

`_async_quick_eligible`'s `AwaitExpr` whitelist only recognizes a
handful of specific shapes: `asyncio.sleep(...)`, a bare call to
another already-compiled top-level `async def` (`IdentExpr` callee), 
`asyncio.sock_recv(...)`, `create_task(...)`/`create_raising_task(...)`,
and a subscript-callee call (comptime-bracket-parametrized nested async
closures). It has no case for:

- `await <local variable>` — awaiting an already-constructed `Future`
  object directly (not a call expression at all), as `put`/`get` do
  with `putter`/`getter`.
- `await <bound-method call>` — `self._finished.wait()`, an `AttrExpr`
  callee (a call to another *object's* async method), as `join` does.

This is the same class of "narrow enumerated await-shape whitelist"
structural gap as the already-tracked async subprocess/stream
composition gap (`create_subprocess_exec`/`.communicate()`/
`.readexactly()` — also an unrecognized-await-shape refusal in this
same pre-filter), not the Future.__await__ value-carrying-`return` gap
tracked separately in `COMPILE_FAIL_asyncio_futures.md` (that one is
about the generator/coroutine promise's `return_void()`-only design;
this one never gets that far — `queues.py`'s `get`/`join`/`put` are
plain `async def`s, not generators, and are rejected purely on the
shape of what they `await`).

Widening `_async_quick_eligible`/`_gen_cpp_async_unit` to support
awaiting an arbitrary local `Future`-typed variable or an arbitrary
bound-method call to another async method would mean generalizing this
codegen's await-suspension machinery from "a fixed enumerated set of
recognized await targets" to "the real `Awaitable` protocol" — a broad
change to shared coroutine-suspension machinery (the same kind of
change this project's history flags as high-risk-for-silent-regression
when done narrowly), not a one-spot fix. Structural, not attempted
here.
