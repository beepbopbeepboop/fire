# Future `add_done_callback(self.method)` is never invoked

## Status

OPEN. Found 2026-10-29 while repairing `test_coro_future_await.py`. Now that the
test links, this case runs and the callback never fires:

    FAIL  bound-method done-callback invoked with self  detail='0\n'

Expected stdout `bound-method callback\n0\n`; got `0\n`. The callback
`Watcher.on_done` is registered with `f.add_done_callback(self.on_done)` and
`f.set_result(9)` should call it as `fn(self, fut)` (tag 1 ->
`mojo_bound_method_call_1`). It prints nothing.

## Reproduce

    python3 tools/memslot.py --gb 8 --label repro -- python3 test_coro_future_await.py

The case is `test_future_done_callback_bound_method` (line ~608). The sibling
cases (plain function, closure, `set_exception` callback) pass, so the
bound-method tag-1 dispatch is the suspect.

## Next step

1. Dump the generated C for the test program and check how the bound method
   value `self.on_done` is lowered at the `add_done_callback` call site: it must
   produce a `MojoBoundMethod*` with tag 1, not a bare function pointer.
2. Check the done-callback dispatch in `runtime/fire_async_runtime.cpp` /
   `fire_async_sched.c` for tag 1, and whether the callback is dropped on
   `set_result`.
3. Fix the tag or lowering, keep the test case, then delete this doc.
