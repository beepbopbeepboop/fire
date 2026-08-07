# COMPILE_FAIL: asyncio/futures.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/asyncio/futures.py`

## Status (updated 2026-08-06)

Re-ran; the original doc's snippet was stale/uninformative (a truncated
context line, not the real error). Current failure is an honest
up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) __await__ (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

`Future.__await__` uses `yield` (the standard `await`-protocol
implementation shape: `def __await__(self): ... yield self ...`). This
is a generator codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

Exit code: 1
