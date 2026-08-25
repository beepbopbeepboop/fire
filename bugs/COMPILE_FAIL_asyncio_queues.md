# COMPILE_FAIL: asyncio/queues.py

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
