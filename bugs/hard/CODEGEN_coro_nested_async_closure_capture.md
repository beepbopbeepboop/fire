# HARD BUG: A3 stack-switch coroutines have no mutable closure capture into a nested `async def`

## Status (2026-09-04, identified during the A3 async-porting session — not attempted, real prerequisite identified)

See `doc/COROUTINE.html` for the full A3 stack-switch coroutine project.
This session ported `async def`/`await`/`asyncio.sleep`/`asyncio.sock_recv`/
async generators (`yield`+`await` combined via `async for`)/
`create_task`/`create_raising_task`/`Task`/`RaisingTask`/`.wait()`/
`with BlockingScopedLock(...)` elision to the new stack-switch substrate
(`gimple_gen_coro.py`), all verified against the real (cpp-path)
`test_gimple_async_runner.py`/`test_async_with_lock_guard.py` test
sources — most of those literally verbatim, not paraphrases.

**What's missing:** `gimple_gen_coro.py`'s nested-`async def` support
(`_hoist_nested_async`, used by the `create_task(wrapper())` idiom) only
handles a nested function whose body references its OWN parameters and
ordinary top-level names — never a variable declared in the ENCLOSING
(ordinary) function's own scope. There is no free-variable detection, no
boxing, and no hidden-argument threading to let a nested async function
read *or mutate* an outer local.

This blocks the real test suite's own lock-guard shapes
(`test_async_with_lock_guard.py`), both of which mutate an outer local
from inside the nested async function:

```mojo
def test_with_lock() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1          # <-- mutates test_with_lock's own local

    var t0 = create_task(inc())
    t0.wait()
    print(rawCounter)                # must observe the mutation
```

and the 10,000-task stress-test variant (`test_locks_mojo_shaped_10000_task_stress`),
which additionally calls the nested closure from a DIFFERENT sibling
closure (`caller()`), compounding the capture with cross-closure
transitive capture.

**Verified NOT to be a lock-elision bug**: `with BlockingScopedLock`/
`BlockingSpinLock` elision itself (the mechanism these two tests are
built to exercise) was verified correct and safe independently, using a
plain parameter instead of a captured outer local:

```mojo
async def inc(n: Int) -> Int:
    with BlockingScopedLock(n):
        return n + 1
# create_task(inc(5)).wait() -> 6, correct
```

and the safety guard (an `await` inside the lock body must be honestly
refused, never silently elided) was also verified correct. So closing
this bug is a pure prerequisite — closure capture — not a lock-guard fix.

## What closing this needs

1. Free-variable analysis on a nested `async def`/`async` generator's
   body: which identifiers resolve to the ENCLOSING function's locals
   (not its own params, not module globals, not builtins).
2. A representation for a captured variable that both sides (enclosing
   function and the coroutine body running on its own separate stack)
   can read *and write* — almost certainly a heap box (a pointer the
   enclosing function keeps live across the `create_task`/`.wait()` call
   and the nested body dereferences), mirroring how the existing ordinary
   (non-async) compiled path already handles `{mut}`-capture closures
   (see `general-mut-closure-capture-fix-2026-07-27` in project memory —
   heap-boxed pointer locals, not `&stack_local`, because `-fgimple`
   rejects address-taken locals later cast/returned).
3. Threading the box(es) as extra hidden arguments into the nested
   function's `__mgco_<outer>_<inner>_start`/`_body` (alongside its own
   declared params) — extending `_hoist_nested_async`'s `base`/arg-count
   bookkeeping and `_lower_one_async`'s prologue.
4. The cross-closure case (`caller()` invoking `inc()` defined in a
   DIFFERENT enclosing function) needs the capture chain to survive
   crossing that second closure boundary too.

## Why this belongs in `bugs/hard`

The ordinary (non-async, non-generator) compiled path already solved
general `{mut}`-capture closures once (2026-07-27, commits `90dbbbe`/
`5b2aefb`/`bd9d82d`/`09286a5`) with real regression history — the fix
above should study and likely directly reuse that heap-boxed-pointer
convention rather than re-deriving it, but the A3 stack-switch body
running on its own separate stack (not an ordinary same-stack nested
closure) is a new interaction that convention was never exercised
against.

## Scope note (§5.6 cutover)

Until this is fixed, `gimple_cpp_async.py` (the C++20-coroutine path)
must stay live for any `async def`/generator that captures a mutable
outer local — deleting it before this lands would regress the real
`test_locks.mojo` stdlib coverage and `test_async_with_lock_guard.py`'s
own real-capture test cases from compiling to source-interpreted
fallback.
