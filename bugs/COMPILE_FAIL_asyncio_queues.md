# COMPILE_FAIL: asyncio/queues.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/asyncio/queues.py`

## Status (updated 2026-08-06)

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
