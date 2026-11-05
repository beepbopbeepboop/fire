# Plan: contextlib async/coroutine codegen

Source bug: bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md

## Decomposition

Step 1 — *args/**kwargs packing at call sites (done)
Step 2 — async for / await through callable-valued params
Step 3 — coroutine eligibility for kwonly params
Step 4 — Re-build Lib/contextlib.py end-to-end

## Repro (2026-11-05, re-run)
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py` now completes (exit 1, ~193s) and emits the contextlib-specific refusal verbatim:

```
cannot compile module: function(s) __aexit__, __aexit__, _exit_wrapper, inner (async function(s), declared `async def`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend/resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
```

The stdlib dylib is still dragged in (many unrelated module errors precede it), but the gate fires and names exactly `__aenter__`/`__aexit__`/`_exit_wrapper`/`inner`. Step 2 (async for / await through callable-valued params) and Step 3 (kwonly params) are prerequisites; the refusal itself is the Step 4 gate and remains open.
