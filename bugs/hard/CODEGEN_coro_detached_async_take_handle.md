# HARD BUG: A3 stack-switch coroutines have no "detached async" (`_take_handle()` / GPU device-context dispatch) support

## Status (2026-09-04, identified during the A3 async-porting session — not attempted)

See `doc/COROUTINE.html` for the full A3 stack-switch coroutine project
and `CODEGEN_coro_nested_async_closure_capture.md` for the other
identified prerequisite (mutable closure capture into a nested
`async def`) — these are the two remaining gaps blocking full
`gimple_cpp_async.py` (§5.6) deletion after this session's async
porting (v0 core, `asyncio.sleep`/`sock_recv`, async generators via
`async for`, `create_task`/`create_raising_task`/`Task`/`RaisingTask`/
`.wait()`, `with BlockingScopedLock` elision — all landed and verified
this session).

**What "detached async" is** (existing cpp-path mechanism,
`gimple_gen_methods.py` ~line 793-825): `std.gpu.host.DeviceContext`'s
`enqueue_cpu_function`/`enqueue_cpu_range` (`device_context.mojo`) wrap a
plain, synchronous host callback in a coroutine closure with no
`await`s of its own, then extract its raw handle two ways:

```mojo
coro._set_noop_callback()      # no-op in this codegen -- see below
var handle = coro^._take_handle()
```

and hand `handle` (an `int64_t`, NOT this codegen's usual coroutine-
handle type) to `AsyncRT_DeviceContext_enqueueHostFunction`/
`...Range` (`runtime/mojo_async_runtime.h`/`.cpp`), which is itself a
deliberate synchronous simplification (see that function's own
docstring and `bugs/CODEGEN_device_context_host_function_enqueue_
synchronous_stub.md`) — no real GPU stream ordering, it just calls
`resume_fn(handle)` once (the wrapped closure has no internal
suspension point, so one resume always drives it to completion) then
`destroy_fn(handle)`.

The cpp path's `_take_handle()` lowering (`gimple_gen_methods.py`
~line 822) just reinterprets the SAME `MojoAsync *` handle the
coroutine's own `_start()` produced as a plain `int64_t`, matching
what `mojo_coro_resume_generic(int64_t)`/`mojo_coro_destroy_generic
(int64_t)` (the type-erased, promise-agnostic resume/destroy pair —
see `mojo_async_runtime.h`'s own docstring on why ONE such pair can
serve every compiled coroutine in the C++20 design) expect.

**Why this is likely NARROWER than the closure-capture gap**: A3's
`MojoGenerator *`/`MojoCoro *` handles are ALREADY plain, uniform,
promise-agnostic pointers (that is the whole point of the stack-switch
design — see `doc/COROUTINE.html` §7's backend-ABI table), and
`__mojo_gen_resume`/`__mojo_gen_destroy` (this session's `gimple_gen_
coro.py` additions, used generically for `create_task`/`.wait()`
support) are ALREADY the exact type-erased "resume/destroy any
compiled coroutine" pair `mojo_coro_resume_generic`/`destroy_generic`
provide on the cpp path. Closing this bug is therefore likely:

1. Recognize `.{_set_noop_callback,_take_handle}()` (zero-arg member
   calls) on a value that is a stack-switch coroutine handle
   (`MojoGenerator *`), in `gimple_gen_coro.py`'s own rewrite (mirroring
   the cpp path's `func.obj` `MojoAsync *`-type check, but for our
   `MojoGenerator *`): `_set_noop_callback()` -> no-op; `_take_handle()`
   -> the handle value itself, reinterpreted as int64_t (already true by
   construction -- `MojoGenerator *` IS what `__mojo_gen_resume`/
   `_destroy` already take, cast to int64_t).
2. A plain-C equivalent of `AsyncRT_DeviceContext_enqueueHostFunction`/
   `...Range` that calls `__mojo_gen_resume`/`__mojo_gen_destroy`
   instead of `mojo_coro_resume_generic`/`destroy_generic` -- likely a
   thin addition to `runtime/mojo_coro_gen.c` reusing the exact
   synchronous-dispatch shape the existing stub documents (no real
   change in semantics, just the resume/destroy primitive underneath).
3. Whatever construct-time eligibility gate the cpp path uses
   (`_lower_async_closure_construct` et al. — an `async def` closure
   with no `await` of its own, consumed only via `_take_handle()`) needs
   a stack-switch-side equivalent in `gimple_gen_coro.py`'s eligibility
   checks.

Not attempted this session -- no `device_context.mojo`-shaped source was
built or tested against the new path. Scope note: until this lands,
`gimple_cpp_async.py` must stay live for any module using
`DeviceContext.enqueue_cpu_function`/`enqueue_cpu_range` (real GPU-host
dispatch code) -- deleting it first would regress that path to
interpreted fallback.
