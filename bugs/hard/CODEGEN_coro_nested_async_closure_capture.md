# HARD BUG: A3 stack-switch coroutines have no mutable closure capture into a nested `async def`

## Status (2026-09-25 — Increment E: struct capture now WORKS; Increment D now refuses honestly instead of emitting broken C)

Both remaining-scope items in the 2026-09-05 entry were addressed. Neither
was "finish the feature", and the doc is explicit about which is which.

### Increment E — struct capture: LANDED (it was smaller than "feature-sized")

`_strict_init_kind` returned `None` for a struct-typed initializer, so a
captured struct made the whole capture plan refuse. But a struct is just a
POINTER, and the capture cell is already an `int64_t` holding a
pointer-sized value — so it needs **no new cell type at all**, only the
int↔pointer round trip at the read/write boundary, which this codegen
already has for exactly this problem (`_apply_async_struct_param_erasure`
erases a struct-typed param's pointer bit-pattern through `__mojo_gen_arg`):

- `_strict_init_kind` now recognises a same-module class constructor call
  and returns `'i'`. Deliberately narrow: an unannotated call of a name
  that is *not* in `_STRUCT_NAMES` still returns `None`, so this cannot
  start boxing arbitrary call results.
- `_outer_boxable_locals` records the struct name alongside the kind, and
  `_apply_nested_async_capture` registers it per box HANDLE (not per source
  name — the same captured name is re-boxed once per enclosing scope) in a
  new `_BOX_STRUCT_OF`.
- `_cap_rewrite_expr`/`_cap_rewrite_stmts` go through two new helpers,
  `_box_get_call` / `_box_set_args`, which wrap the getter in
  `UnsafePointer[T](...)` and the setter's value in `.address`. Those lower
  to this codegen's usual int → `void *` → `T *` two-step (GIMPLE rejects a
  direct `int64_t` → `T *` cast, per the existing note).

Note the mutation `p.x = p.x + 5` is a `MemberExpr` assignment TARGET, not
a bare-name target, so it needed no new statement case — the field write
goes through the recovered `T *`, which is exactly right.

Verified by real compile+link+run: `outer` capturing `var p = Point(10)`
into a nested `async def` that mutates it now prints `15`; on the
unmodified tree the A3 backend **refused the whole module**
(`bump: only a plain identifier assignment target is supported`). The
existing int / float / string captures all still work, including a mixed
struct + int capture in one function (verified: `6`, `2.0`, `ab`, `2`).
Regression test: `nested_async_struct_capture_boxes_pointer`.

### Increment D — `async for` into a nested async generator: still not supported, but now an HONEST refusal

Threading the capture box through the `async for` driver and the consuming
coroutine remains the real work. What changed is the failure mode. The doc
previously claimed the unrepresentable case "falls to the cpp path cleanly
instead of emitting an undefined reference" — **it did not.** Verified: the
cpp generator emitter has no capture model at all, so it emitted the
generator body referencing the captured name in a scope where it does not
exist, and the build died on

```
d1_gen.cpp:136:5: error: 'acc' was not declared in this scope; did you mean 'acct'?
```

— a hard error pointing into *generated* code, blaming the program for a
compiler gap. Worse, the C++ emitter for async generators is a **different
function** from the one for plain generators (`_gen_cpp_async_generator_unit`
vs `_gen_cpp_generator_unit`), so gating only the latter would have left
this path untouched — worth recording, since the two are easy to confuse.

Now `_hoist_nested_async` records these generators (bare and
`__mgco_<outer>_<gen>`-qualified) in `_UNTHREADABLE_NESTED_ASYNC_GENS`, and
**both** C++ generator emitters consult it and raise
`_UnsupportedGeneratorShape`. The same program now fails with a message that
names the construct and the reason:

```
cannot compile module: function(s) gen (async generator function(s), ...)
Unsupported shape(s): gen: is a nested async generator that captures
enclosing locals which are only read from a further-nested `async def`
sibling's `async for`/await drive loop; the capture box cannot be threaded
into a driven consumer
```

Regression test:
`nested_async_gen_capture_from_async_for_refused` in `test_gimple.py`.

### Verification

`test_gimple.py` 316/316, `test_gimple_runner.py` 76/76,
`test_gimple_generator_runner.py` 120/120, `test_generators.py` 29/29,
`test_module_cache.py` 81/81, `test_coro_bugs.py` LOWERED=3/RAISE=6 —
identical to baseline. `test_taskgroup.py` fails 3/3 and
`test_coro_nested_async_capture.py` 8/9 **identically on the unmodified
tree** — both are this checkout's pre-existing missing
`runtime/mojo_async_runtime.cpp` (the real file is `fire_async_runtime.cpp`),
not regressions; that is also why Increment E's runtime evidence is a
hand-built `fire.py build` binary rather than a harness test.

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

### Increments A / B / C landed 2026-09-06

`gimple_gen_coro.py`'s nested-async capture box is no longer
int-literal-scalar only:

- **Increment A — non-int-literal initializer.** `_outer_boxable_locals`
  (was `_outer_int_locals`) accepts any `var name = <init>` whose kind is
  statically confident: an explicit `Int`/`Float64`/`String`-family
  annotation, a `_strict_init_kind` match (literal, another typed local,
  `int()`/`len()`/`float()`/`str()`…, a homogeneous BinaryOp), or a call
  to a same-module `def … -> <scalar>` (`_FUNC_RET_KIND`, e.g.
  `var rawCounter = compute()`). An opaque unannotated call of unknown
  return type still returns `None` → cpp path.
- **Increment B — captured PARAMETER.** `_nested_async_capture_plan` now
  also boxes a directly-captured parameter of the enclosing function:
  the raw param is renamed `__capsrc_<n>` and a `var <n> =
  __mojo_box_new_*(__capsrc_<n>)` init is prepended, so the bare name
  denotes the box handle in the body exactly as a boxed body-local does.
  Kind from the param annotation or the unanimous call-site contract;
  unknown → `None` → cpp path.
- **Increment C — float / string capture.** Typed box cells:
  `__mojo_box_new_d/_get_d/_set_d` (double) and `__mojo_box_new_p/_get_p/
  _set_p` (`char *`), runtime/mojo_coro_gen.c. `_BOX_SHIMS` picks the
  triple from the capture kind; the handle stays a plain `int64_t` so the
  hidden-trailing-param threading is unchanged. **struct** capture is
  still refused (`_strict_init_kind` → `None` → cpp path).

Regression tests: `test_coro_nested_async_capture.py`
(`test_nonliteral_initializer_capture`, `test_captured_parameter`,
`test_float_capture`, `test_string_capture`,
`test_struct_capture_refused_to_cpp`) — all real compile + link + run.

### Remaining scope (still correctly REFUSED to cpp, not miscompiled)

- **struct capture** — `_nested_async_capture_plan` → `None`.
- **mutable outer capture into an async GENERATOR consumed via `async
  for`** (Increment D). `_hoist_nested_async`'s async-generator branch
  now mirrors the plain-`async def` capture plan/apply (so a directly-
  driven nested async-gen capture is boxed, and an unrepresentable one
  falls to the cpp path cleanly instead of emitting an undefined
  reference), but the realistic consumption — `async for x in g():`
  inside a *sibling* `async def` — is deliberately refused by the new
  `_called_from_nested_async` guard: the box-handle threading covers
  `outer`'s body and ordinary nested siblings only, not a nested async's
  own `_async_for_drive_stmts` call sites. Threading the box through the
  async-for driver + the consuming coroutine is the remaining work.

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

`gimple_cpp_async.py` (the C++20-coroutine path) must stay live for the
two remaining refused shapes: a **struct** capture, and a mutable outer
capture into an **async GENERATOR consumed via `async for` in a sibling
`async def`** (see "Remaining scope" above). Both are correctly refused
rather than miscompiled; deleting the cpp path before they land would
regress real coverage from compiling to source-interpreted fallback.
(Int-literal / non-literal-init / captured-parameter / float / string
captures — items 1-4 and Increments A/B/C — are all handled by the
stack-switch path now.)
