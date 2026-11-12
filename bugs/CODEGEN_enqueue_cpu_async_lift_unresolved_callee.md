# CODEGEN: async `__lift_Ctx_enqueue_cpu_*` wrappers refused: unresolved callee `func(...)`

Found 2026-11-12. Pre-existing on master (identical with master's `coro.py`).

## What I ran

    python3 test_async_void_return.py

## What I saw

    FAIL test_device_context_shaped_repro_end_to_end
      cannot compile module: function(s) __lift_Ctx_enqueue_cpu_function_wrapper (async function(s)) ...
      Unsupported shape(s): __lift_Ctx_enqueue_cpu_function_wrapper: a call to unresolved callee 'func(...)'
    FAIL test_enqueue_cpu_range_shaped_repro_multiple_handles
      ... __lift_Ctx_enqueue_cpu_range_wrapper ... unresolved callee 'func(...)'

9 of 11 cases in that file pass.

## What I expected

The lifted async wrapper calls its captured callable (`func`) through a declared callable-value
local, which the compiled coroutine body supports, so the module compiles (or falls back cleanly
with the wrapper not in the refusal).

## Next step

In the async-lift pass that generates `__lift_*_wrapper`, the wrapped callable `func` must be
declared as a callable-value local (or resolved to its parameter type) before the coroutine body
is checked. Start at the "unresolved callee" refusal in the generator/coroutine body checker and
trace how `func` is bound in the lifted wrapper.
