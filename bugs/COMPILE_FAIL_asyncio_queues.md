# COMPILE_FAIL: asyncio/queues.py

## Status (2026-09-05 — gap 1 of 3 CLOSED: sync-method-side Future/Event ops now lower; gaps 2 (Future-typed containers) and 3 (eager task scheduling) still open)

Gap 1 from the entry below ("sync-method-side Future ops") is now
implemented. `gimple_gen_methods.py`'s `_lower_method_call` grew an
Awaitable-protocol hook that mirrors `gimple_gen_coro.py`'s
async-body-only `_rewrite_async_expr` rewrite for ORDINARY (non-coroutine)
call sites:

- `<recv>.create_future()` → `__mojo_future_new()`
- `<recv>.Event()` / `<recv>.Future()` → `__mojo_event_new()` /
  `__mojo_future_new()`
- `<recv>.set_result(v)` → `__mojo_future_set_result(recv, v)`
- `<ev>.set()` / `.clear()` / `.is_set()` → `__mojo_event_set/_clear/_is_set`
- `<fut>.done()` / `.result()` → `__mojo_future_done` / `__mojo_future_result`

Scoping (keeps the synchronous compiled path for non-Future receivers
untouched, so the stdlib gate stays clean):
- only when `MOJO_CORO != cpp` AND this module actually emitted a
  stack-switch coroutine unit (`gen._stackswitch_coro_c_units`) — exactly
  the condition under which `gimple_module_gen.py` emits the `extern`
  decls for these shims;
- never when the receiver is a compiled struct that itself defines a
  same-named method (a real user `.set()`/`.done()` still dispatches
  normally). The Future/Event API names are otherwise unambiguous — no
  `.mojo` source and no non-asyncio stdlib module calls them
  (grep-confirmed).

Regression test: `test_coro_future_await.py::test_sync_method_side_future_ops`
(real compile+link+run — a sync struct method calls `create_future()` /
`.set_result(37)`; an async consumer `await`s the handle and reads 42).

Gate (all identical to the stage-1 baseline): test_gimple 267/0,
test_module_cache 76/0, test_coro_runtime 20/20, test_coro_future_await
3/3, compile_stdlib 664/0 (0 unexpected), stdlib dylib 0 skips,
check-selfhost clean, check-linkmode 3/0, test_gimple_async_runner 2/36
(pre-existing), test_gimple_generator_runner 80/4 (pre-existing).

**Still open — gaps 2 and 3:**
2. **Future/Event-typed struct fields + containers.** `self._getters =
   collections.deque()` (no bracket param, no annotation) still resolves
   to an opaque `int64_t` field rather than a `MojoList *`, so
   `self._getters.popleft()` hits the `int64_t.popleft() stubbed`
   fallback and does NOT round-trip the handle. `.set_result()` on the
   popped value now lowers correctly (gap 1) but is handed garbage. Needs
   RHS-driven field typing: `= collections.deque()` / `= deque[T]()` →
   `MojoList *` field, and `= locks.Event()` → int64_t-handle field (the
   latter mostly works already since `Event()` now yields `int64_t`).
   Confirmed with a `deque[Int]`-field repro: the `.append`/`.set_result`
   sites compile, the `.popleft` site stubs.
3. **Eager task scheduling.** Unchanged from below — v0 `create_task` is
   still a lazy passthrough (`_rewrite_asyncio_run`), so two sibling
   tasks can't run concurrently and a producer can't wake a parked
   consumer. Needs `create_task` to emit
   `__mojo_async_schedule_ready(handle->coro)` and `await task^` /
   `.wait()` to stop re-driving an already-scheduled task. The runtime
   primitive (`__mojo_async_schedule_ready`, `__mojo_async_notify_future`)
   already exists and is C-unit-tested.

## Status (2026-09-05 — ADVANCED: the Awaitable/Future protocol now exists in the A3 runtime and the two await SHAPES this doc tracks now compile; NOT closed — three further gaps remain)

Built the real Awaitable protocol on the A3 stack-switch coroutine
substrate (the feature every prior entry deferred). Landed this pass:

- **Runtime (`runtime/mojo_coro_gen.c` + `mojo_async_sched.c` +
  `mojo_wd.h`)**: a heap-allocatable `MojoFuture` handle (plain int64_t,
  like every other cross-boundary coro handle). `__mojo_future_new` /
  `_set_result` / `_done` / `_result`; `__mojo_event_new` / `_set` /
  `_is_set` / `_clear` (Event = a latching Future). `await` parks via a
  new `MOJO_WD_FUTURE` wait-descriptor (payload = the handle), forwarded
  upward through every enclosing await drive loop exactly like SLEEP/READ;
  the scheduler records `(handle -> outermost coro)` in a wait table and
  `__mojo_future_set_result` / `__mojo_event_set` call
  `__mojo_async_notify_future` to move every parked waiter back onto the
  ready queue. Real cross-coroutine wakeup + multi-waiter fan-out are
  unit-tested at the C level in `runtime/test_mojo_future.c` (wired into
  `test_coro_runtime.py`, 20/20).

- **Codegen (`gimple_exprtypes.py` `_async_quick_eligible` /
  `_await_call_ctype`; `gimple_gen_coro.py`; `gimple_module_gen.py`
  externs)**: `_async_quick_eligible` no longer rejects `await <local
  Future variable>` or `await <expr>.wait()` — the two shapes named all
  over this doc. `_await_drive_stmts` lowers `await <future handle>` ->
  `__mojo_async_await_future(__c, h)` and `await <ev>.wait()` ->
  `__mojo_async_await_event_wait(__c, h)`. Inside an async body,
  `create_future()` / `Event()` / `.set_result(v)` / `.set()` / `.done()`
  / `.is_set()` rewrite to the shims (confined to async-coroutine-body
  lowering — the synchronous compiled path is untouched).

- **Tests**: `test_coro_future_await.py` (real compile+link+run):
  `await <future>` returns the resolved result box; `await <ev>.wait()`
  compiles and runs. `test_gimple.py` 267/0, `test_module_cache.py` 76/0,
  `compile_stdlib.py` 664/0 (0 unexpected), stdlib dylib 0 skips,
  `make check-selfhost` / `check-linkmode` clean.

**Still missing before queues.py itself compiles+runs end-to-end:**
1. **Sync-method-side Future ops.** `Queue.put_nowait` / `get_nowait` call
   `getter.set_result(None)` from ORDINARY (non-async) methods; the
   `.set_result` -> shim rewrite currently only fires inside async bodies.
   Needs the same rewrite in the general method/call lowering
   (`gimple_gen_methods.py` / `gimple_gen_calls.py`).
2. **Future/Event-typed struct fields + containers.** `self._finished`
   (an Event field), `self._getters: deque[Future]` — field-type
   inference has to carry an int64_t-handle type for these, and
   `self._getters.append(putter)` / `self._getters.popleft()` have to
   round-trip the handle.
3. **Eager task scheduling.** v0 `create_task` is a lazy passthrough (no
   scheduler enqueue), so two sibling tasks can't actually run
   concurrently — a producer can't wake a consumer that's already parked.
   The runtime supports it (`__mojo_async_notify_future` +
   `__mojo_async_schedule_ready`); the codegen needs create_task to emit
   an eager `__mojo_async_schedule_ready(handle->coro)` AND `await task^`
   to stop re-driving an already-scheduled task. Filed as the concrete
   next step here rather than a separate doc since it's this feature's
   own remaining half.

Infrastructure committed; doc kept open.

## Status (re-verified 2026-08-26, this session, master fast-forwarded to `9c0e7a8` — DOCUMENTED-NOT-FIXED, unchanged)

Fresh isolated `compile_to_gimple_with_cpp` probe of `Lib/asyncio/
queues.py` directly (bypassing the transitive-import path so the
module's OWN refusal is reached, not the collections/inspect fallback
noise the whole-tree `mojo.py build` run hits first). Byte-for-byte
identical refusal to every prior pass: `function(s) get, join, put
(async function(s), declared async def)` — `_async_quick_eligible`'s
await-shape pre-filter rejects all three before any translation is
attempted (`await <local Future variable>` for `get`/`put`, `await
self._finished.wait()` — a bound-method call — for `join`). This
session's own landed change (real `filter(func, iterable)` coroutine-
body codegen, see COMPILE_FAIL_importlib_metadata___init__.md) touches
only the generator-body CallExpr emitter, nowhere near the async
pre-filter; confirmed unrelated. Closing this needs the real Awaitable
protocol (allocatable Future/Event handles with waiter queues and
cross-coroutine wakeup) — a feature-sized asyncio-runtime project,
explicitly out of scope per this campaign's own repeated conclusion
across a dozen+ independent sessions. Not attempted. Doc kept open.

## Status (re-verified 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch, unchanged)

Re-read `_async_quick_eligible` (`gimple_exprtypes.py:184-255`) directly,
then ran a fresh isolated `gimple_codegen.compile_to_gimple_with_cpp(
do_imports=False)` probe against this file only (bypassing the
transitive-import fallback that ate the whole 300s budget in the prior
`mojo.py build`-driven entry below). Byte-for-byte identical refusal:
`function(s) get, join, put (async function(s), declared async def)`.
Confirmed from the whitelist source itself that `await <local Future
variable>` (`putter`/`getter`) and `await <bound-method call>`
(`self._finished.wait()`) are genuinely unrecognized shapes — closing
them needs the real Awaitable protocol (allocatable Future/Event
handles, waiter queues, cross-coroutine wakeup), a feature-sized
asyncio-runtime project. Not attempted; no code change.

## Status (re-verified 2026-08-26, worktree fix/opencode-genlib2 — fresh bounded build confirms unchanged: entire 300s budget spent in transitive source-fallbacks, own refusal unreached)

Fresh safety-watched `python3 mojo.py build .../Lib/asyncio/queues.py`
(own watcher, killed at 302s): identical behavior to the canalyzer2
entry below — the run emits only two honest transitive-import fallback
lines (`collections`: `Counter[...] = ...` subscript store; `inspect`:
`OrderedDict[...] = ...` subscript store) and then spends its WHOLE
budget silently interpreting those modules from source, never reaching
queues.py's own module-level refusal. RSS stayed well under the kill
thresholds. queues.py's OWN blocker is untouched by anything landed:
`get`/`join`/`put`'s `await <local Future>` / `await <bound-method
call>` shapes remain outside `_async_quick_eligible`'s whitelist;
closing them still needs the real Awaitable protocol (allocatable
Future/Event handles + waiter queues + cross-coroutine wakeup) — a
feature-sized asyncio-runtime project, explicitly out of scope. Doc kept
open.

## Status (updated 2026-08-26, wtOpencode_canalyzer2 — re-verified fresh; own
## blocker unchanged, build now can't even REACH the module refusal in 300s)

Fresh bounded `python3 mojo.py build .../Lib/asyncio/queues.py`
(watcher-killed at 300s): the run never reaches queues.py's own
module-level refusal anymore — it spends the entire budget inside the
documented >300s inline source-fallback for its TRANSITIVE imports,
which now fail as `collections`'s `Counter[...] = ...` and `inspect`'s
`OrderedDict[...] = ...` subscript-store refusals (both honest
fallbacks; see COMPILE_FAIL_collections___init__.md). queues.py's OWN
blocker is untouched by anything landed: `get`/`join`/`put`'s
`await <local Future>` / `await <bound-method call>` shapes remain
outside `_async_quick_eligible`'s whitelist, and closing them needs the
real Awaitable protocol (allocatable Future/Event handles + waiter
queues + cross-coroutine wakeup) — a feature-sized asyncio-runtime
project, still explicitly out of scope. Doc kept open.

## Status (updated 2026-08-26, worktree fix/opencode-group4 — superseded above)

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
