# Gate job `coro-detached-async` is red: runtime/mojo_coro.c does not compile in the gate

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL  test_detached_async_single_handle_actually_invoked  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/
FAIL  test_detached_async_range_multiple_handles  exception: compile of /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_coro.c failed: cc1: fatal error: /Users/mrs/net/chatgpt/claude/work-spanfix/runtime/mojo_cor
```

## What to check first

cc1 fatal error compiling runtime/mojo_coro.c (see excerpt); test_detached_async_*.

## Next step

1. Run `python3 tools/suite.py coro-detached-async` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
