# `async def` method on a compiled struct segfaults (asyncio.Queue shape)

## Status

OPEN. Found 2026-10-29 while repairing `test_coro_future_await.py` (the stale
`mojo_*` runtime file paths were fixed; see `RUNTIME_gate_coro_future_await_red`
history). Now that the test links, this case runs and dies:

    FAIL  test_async_struct_method_queue_roundtrip  exception: program exited -11, stderr=

Exit -11 is SIGSEGV with no stderr output. Expected stdout: `42\n`
(`put(41)` parks nothing, `get()` pops 41, `main_co` returns 42).

## Reproduce

    python3 tools/memslot.py --gb 8 --label repro -- python3 test_coro_future_await.py

The failing case is `test_async_struct_method_queue_roundtrip` (line ~259). Its
program: a struct `Q` with `deque` fields, `async def get` that parks a bare
`create_future()` on `self._getters` and `await`s it, plus `async def put`.

## What is known

- The receiver-slot start function and `__mgco_<Struct>_<method>_start`
  trampoline (the gap-4 work the test's docstring describes) are the code path.
- The segfault happens at run time, not compile time: the generated C compiles
  and links.

## Next step

1. Compile the program's generated C (`gimple_codegen.compile_to_gimple` on the
   test source) and run it under lldb (`tools/gdbtool`) to find the faulting
   frame. Check whether `self` (the `Q` receiver slot) is valid in the
   coroutine after the first suspension at `await getter`.
2. Fix the receiver-slot lifetime in the method coroutine start function, add
   a regression test (the existing case already pins it), then delete this doc.
