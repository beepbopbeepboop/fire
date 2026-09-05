# HARD BUG: A3 stack-switch coroutines have no mutable closure capture into a nested `async def`

## Status (2026-09-05, cross-closure stress case (item 4) NOW LANDED)

Items 1-3 AND item 4 (the cross-closure `TaskGroup` stress shape) are
DONE and verified end-to-end (real compile + link + run, real stdout)
under `MOJO_CORO=stackswitch` — see `test_coro_nested_async_capture.py`
(`test_simple_with_lock_guard_single_task`,
`test_cross_closure_taskgroup_stress` for the 10,000-task shape,
`test_cross_closure_single_scope_taskgroup`).

Item 4 fix (2026-09-05):
1. `_rewrite_asyncio_run_stmts` now MERGES the enclosing scope's active
   local_map into a further-nested sibling function's own, instead of
   discarding it — a hoisted nested async (`inc`) is still in lexical
   scope inside a sibling `def caller()`, so `caller`'s own
   `tg.create_task(inc())` gets the same qualified-`{base}_start` rename.
2. `_thread_box_through_siblings` (new): after boxing a captured local,
   every ordinary function nested in the enclosing scope that
   transitively calls the hoisted async — or references a captured
   local — receives each box handle as its own hidden trailing `Int`
   param, its calls to the async / other threaded siblings get the
   matching trailing argument, its own direct reads/writes of a
   captured name are rewritten through the box, and the call to it from
   the enclosing body forwards the enclosing scope's own box local.
3. The A3 stack-switch `TaskGroup.create_task(...)` / `.wait()`
   intrinsics: `_resolve_and_start_task` (gimple_cpp_async.py) now
   recognizes a coro-rewritten `{base}_start(args)` call, and
   `_lower_method_call`'s `tg.wait()` (gimple_gen_methods.py) gained a
   stack-switch branch that drives each collected `MojoGenerator`
   handle via `__mojo_async_run_gen` + `__mojo_gen_destroy` (no
   cpp-scheduler drain, no `{base}_translate_pending_exc` — the
   stack-switch trampoline emits neither; exception propagation matches
   the single-task stack-switch `.wait()` path exactly). `test_taskgroup
   .py` / `test_async_with_lock_guard.py` (cpp-path escape-hatch tests
   whose harness links the cpp scheduler) now pin `MOJO_CORO=cpp`
   explicitly.

Full quality gate (steps 0-4) green: check-linkmode 3/3, check-selfhost
1/1, from-scratch stdlib dylib (0 `skip` lines), compile_stdlib.py
664/664 (0 unexpected), make bootstrap, plus test_gimple.py 266/0,
test_module_cache.py 76/0, test_gimple_generator_runner.py 63/4 (4
pre-existing), test_coro_nested_async_capture.py 4/0.

### Remaining scope (v0 type limits — correctly REFUSED, not miscompiled)

`gimple_cpp_async.py` (the C++20-coroutine path) must stay live for a
capture that v0's int-literal-scalar box cannot represent —
`_nested_async_capture_plan` returns `None` and the nested async is not
hoisted (falls through to the cpp path unchanged, never a miscompile):
a captured PARAMETER, a non-int-literal initializer, a float/string/
struct capture, or a mutable outer capture into an async GENERATOR
(this fix covers only the plain `async def` branch of
`_hoist_nested_async`, not `_lower_one_async_gen`). These are genuine
future work, all currently safe.

### Original report (item 1-3 landing, 2026-09-04)

Items 1-3 below were DONE and verified end-to-end (real compile + link +
run, real stdout) against `test_async_with_lock_guard.py::
test_simple_with_lock_guard_single_task`'s exact source (see
`test_coro_nested_async_capture.py`, this project's own new test):

```mojo
def test_with_lock() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    var t0 = create_task(inc())
    t0.wait()
    print(rawCounter)                # prints 1 -- correct
```

v0 scope (by design, matching every other narrow eligibility gate this
whole file already uses -- an unsupported shape falls through to the
existing cpp path unchanged, never a miscompile): a captured free
variable must be one of the ENCLOSING ordinary function's own top-level
`var name = <int literal>` locals (no annotation, or `Int`/`int`). A
captured PARAMETER, a non-int-literal initializer, a float/string/struct
capture, or (see below) a capture reached through a SECOND closure
boundary are all left ineligible -- `gimple_gen_coro._nested_async_
capture_plan` returns `None` for any of those and the nested async def
is simply not hoisted, exactly like today.

**Implementation** (`gimple_gen_coro.py`): `_nested_async_capture_plan`
(free-variable detection, reusing `gimple_ctypes._used_idents_node`/
`_declared_vars_body` -- this module has no `gen`/type-inference access
yet, see its own top-of-file docstring, hence the int-literal-only
restriction rather than general type inference) + `_apply_nested_async_
capture` (the actual rewrite): boxes the captured local as a plain
`int64_t` heap handle (`__mojo_box_new_i64`/`_get_i64`/`_set_i64`,
`runtime/mojo_coro_gen.c` -- never a raw pointer type, matching every
other cross-boundary handle in this file, so this stays a pure AST-to-
AST rewrite with no `-fgimple` address-taken-local restriction to work
around at all), rewrites every read/write of the captured name in BOTH
the enclosing function's own body and the nested body to go through the
box, and threads the box handle as a hidden trailing parameter (plain
`Int`, so `_lower_one_async`'s existing `__mojo_gen_arg` prologue binds
it with zero further changes there) -- both the `create_task(wrapper())`
idiom and the bare `var coro = wrapper()` detached-async idiom
automatically get the extra argument appended at their call site.
`_capture_scan_body` special-cases a lock-with statement (`with
BlockingScopedLock/BlockingSpinLock(...):`) when computing free
variables, since its own guard expression (e.g. `lock` in
`BlockingScopedLock(lock)`) is elided entirely by `_rewrite_async_stmts`
and must not be misdetected as a (v0-unsupported) capture.

**Item 4, the cross-closure case — LANDED 2026-09-05 (see Status above)**
(`test_locks_mojo_shaped_10000_task_stress`):

```mojo
def test_with_lock_stress() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0
    ...
    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    def caller() raises:
        var tg = TaskGroup()
        for _ in range(0, maxI):
            for _ in range(0, maxJ):
                tg.create_task(inc())        # <-- inc() called from a SIBLING function
        tg.wait()

    caller()
    print(rawCounter)
```

Root cause, confirmed via direct repro: `gimple_gen_coro._rewrite_
asyncio_run_stmts`'s per-function `local_maps` lookup (the mechanism
that rewrites a hoisted nested async's bare-name call to its qualified
`{base}_start`) is keyed ONLY by the DIRECT enclosing function
(`test_with_lock_stress`), not propagated into a further-nested SIBLING
function's own body (`caller`) -- `fn_lm = lmaps.get(s.name, {})`
discards the parent scope's already-active local_map instead of merging
it in. `caller()`'s own `tg.create_task(inc())` call is therefore never
rewritten, `inc` no longer exists under its bare name anywhere in the
compiled output (only under the qualified base), and
`gimple_gen_methods.py`'s generic `TaskGroup.create_task(...)` handling
hits its own pre-existing, correct "only supported for a call to
another compiled async function this module already compiled" honest
refusal (falls back to interpreting the module from source -- NOT a
miscompile; confirmed via direct repro of this exact source under
MOJO_CORO=stackswitch).

Closing this needs two more things layered on top of the landed v0:
1. Propagate the local_map down through nested sibling scopes (`fn_lm =
   {**lm, **lmaps.get(s.name, {})}` instead of discarding the parent's
   `lm` -- a real fix matching actual Python lexical-scoping semantics,
   not a hack).
2. Thread the box handle(s) THROUGH `caller()` too: `caller` itself
   needs to receive `rawCounter`'s box as a hidden parameter, its own
   call to `inc()` needs it appended, and the call to `caller()` from
   `test_with_lock_stress` needs it forwarded -- a genuine transitive-
   closure-through-an-ORDINARY-(non-async)-nested-function problem, the
   same class the ordinary compiled path's own transitive-closure-
   capture fix (2026-07-27) solved for plain closures, but not
   automatically inherited here since `caller`'s only reference to
   `inc` is a CALL to a hoisted top-level function by name (not a
   direct capture of `rawCounter`), which the ordinary closure-lifting
   pass's own free-variable scan doesn't even see (a nested `def`/
   `async def` binding was never added to `enriched_scope` there in
   the first place).

**Verified NOT to be a lock-elision bug**: `with BlockingScopedLock`/
`BlockingSpinLock` elision itself was verified correct and safe
independently of capture, using a plain parameter instead of a captured
outer local (`create_task(inc(5)).wait()` on `async def inc(n: Int) ->
Int: with BlockingScopedLock(n): return n + 1` returns 6, correct), and
the safety guard (an `await` inside the lock body must be honestly
refused, never silently elided) was also verified correct.

## Why this belonged in `bugs/hard`

The ordinary (non-async, non-generator) compiled path already solved
general `{mut}`-capture closures once (2026-07-27, commits `90dbbbe`/
`5b2aefb`/`bd9d82d`/`09286a5`) with real regression history, but that
convention takes a stack local's ADDRESS (safe there only because
`-fgimple`'s address-taken-local restriction is worked around with its
own heap-boxed-pointer indirection) — the A3 stack-switch body running
on its own separate stack was a genuinely new interaction that
convention had never been exercised against. Landed v0 above sidesteps
the whole question by using a plain runtime-call-allocated `int64_t`
handle instead of ever taking `&local` at all (see gimple_gen_coro.py's
own `_BOX_NEW`/`_BOX_GET`/`_BOX_SET` docstring) — simpler than reusing
the ordinary path's convention directly, and sufficient for the
int-literal-scalar v0 scope.

## Scope note (§5.6 cutover)

`gimple_cpp_async.py` (the C++20-coroutine path) must stay live for:
the cross-closure case above (item still open); any capture of a
non-int-literal-initialized local, a captured PARAMETER, or a
non-scalar (float/string/struct) capture (v0 scope, all by design, all
still correctly refused rather than miscompiled); and any `async`
GENERATOR with a mutable outer capture (this fix only covers the plain
`async def` branch of `_hoist_nested_async`, not `_lower_one_async_gen`'s
sibling branch) — deleting the cpp path before ALL of these land would
regress real coverage (`test_locks.mojo`, `test_async_with_lock_guard.
py`'s stress test) from compiling to source-interpreted fallback.
