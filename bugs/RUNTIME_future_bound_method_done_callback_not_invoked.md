# Status update 2026-10-29

Investigation completed. Root cause located in emitted GIMPLE for bound-method async calls (e.g. `await w.run(f)`), NOT in the done-callback dispatch itself.

Evidence from emitted C (`test_coro_future_await.py` snippet, compiled via `gimple_codegen.compile_to_gimple`):
- `main_co` creates future `f` (handle non-zero) and passes it to `w.run(f)`.
- Call site emits `__mgco_Watcher_run_start (_t5, _t7);` but `_t7 = (int64_t)0;` (hardcoded zero).
- Inside `Watcher.run` body (`__mgco_Watcher_run_body`), `f = _t1` where `_t1 = __mojo_gen_arg(__c, _t2)` with `_t2 = 1` — so the receiver (`self`) is correct but the second argument (the future handle) is missing; `add_done_callback(0, ...)` and `set_result(0, 9)` become no-ops because `!f`.
- Consequently `future_fire_callbacks` never fires and output is just `0\n`.

The done-callback tag-1 lowering (`self.on_done` -> `MojoBoundMethod*`) and runtime dispatch (`__mojo_future_invoke_callback`) are correct; the failure is upstream in argument lowering for bound async method calls. Fix requires correcting the call-site emission for `await w.run(f)` (likely in `emit_methods.py` / `cpp_async.py` argument list construction for `MojoGenerator *` starts).

Quick regression test: `test_future_done_callback_bound_method` (line ~608) — already fails before fix, passes only when argument passing is repaired.

NOT FIXED in this session; requires emission fix in codegen, not runtime.
