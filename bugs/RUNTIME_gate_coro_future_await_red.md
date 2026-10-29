# Gate job `coro-future-await` is red: runtime/mojo_coro.c does not compile (await of futures)

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL  test_await_resolved_future_value  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c: No su
FAIL  test_await_event_wait_bound_method  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c: No 
FAIL  test_sync_method_side_future_ops  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c: No su
FAIL  test_eager_task_scheduling_concurrency  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c:
FAIL  test_deque_field_future_handle_roundtrip  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.
FAIL  test_async_struct_method_queue_roundtrip  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.
```

## What to check first

cc1 fatal error compiling runtime/mojo_coro.c; test_await_resolved_future_value and test_await_event_wait_bound_method.

## Next step

1. Run `python3 tools/suite.py coro-future-await` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
