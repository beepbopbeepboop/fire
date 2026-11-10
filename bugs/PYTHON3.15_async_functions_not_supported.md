# PYTHON3.15_async_functions_not_supported

## Summary
fire cannot compile modules containing `async def` functions. Error:
```
cannot compile module: function(s) __anext__, aclose, athrow (async function(s), declared `async def`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume co...
```

## Source (CPython 3.15.2)
- Lib/asyncio/ (multiple files), Lib/_py_warnings.py (indirectly)
- Python/ceval.c (coroutine/async generator handling)
- PEP 492 (coroutines with async/await syntax)

## Status
Open. Need async/await state-machine transform.