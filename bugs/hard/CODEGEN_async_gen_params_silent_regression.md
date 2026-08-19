# HARD BUG: Phase 7's "async generator params" eligibility widening was never wired to the only real consumption path, producing invalid C++ (or an accidental whole-module fallback) instead of an honest front-door refusal

## Status (2026-08-19) — REAL FIX LANDED

Parametrized async generators consumed via `async for x in f(<args>):` now
genuinely compile, link, AND RUN, with correct values — not just an honest
refusal. Implemented exactly what this doc's own original "Fix" section
described as the real (nontrivial) follow-up:

- `_cpp_async_for_stmt` (`gimple_codegen.py`) now threads the call site's
  own arguments (`it.args`) into `{base}_impl(...)`, mirroring the sibling
  async-awaits-async composition call site (`_cpp_expr`'s `AwaitExpr` case,
  `call_args = ', '.join(self._cpp_expr(a) for a in target.args)`).
- It ALSO validates the supplied argument count against the async
  generator's own real parameter count (`self._async_gen_api[fn_name]
  ['params']`, the `(name, ctype)` list `_gen_cpp_async_generator_unit`
  registers) before emitting anything, raising a specific
  `_UnsupportedAsyncShape` (`"async generator 'f' called with N
  argument(s), expected M"`) on a mismatch — stricter than the sibling
  `AwaitExpr` call site, which never checks arg count at all (point (b)
  from the original "Fix" section, done "ideally safer" than the sibling).
  Confirmed via `MOJO_DEBUG=1`: the specific message IS raised at the
  point of failure; like every other in-body refusal reason already in
  this file (e.g. `yield from`, non-call `await`), it then gets folded
  into the outer, generic "cannot compile module" wrapper by the enclosing
  async-function compile attempt's own catch-all — this is pre-existing,
  uniform architecture, not something this fix changed or could bypass
  without changing that shared catch-all for every other refusal reason
  too (out of scope here).
- Keyword arguments at the `async for` call site are still refused (the
  sibling `AwaitExpr` shape never supported them either).
- The `if fn.params: return False` safety-net gate in
  `_async_gen_quick_eligible` has been REMOVED — no longer needed, since
  `_cpp_async_for_stmt` itself now honestly validates any real argument-
  count mismatch instead of relying on this quick-filter to exclude every
  parametrized async generator regardless of how it's actually called.

Verified with three real repros (see `test_gimple_async_runner.py`):
single-parameter `f(10)` (10 then 11, sums to 21), two-parameter `g(3, 4)`
(sums to 7), and the wrong-arg-count case `f()` (honestly refused, no
invalid C++, no silent whole-module fallback misattribution). Full
`test_gimple_async_runner.py` suite: 38/38 (36 prior + 2 new positive
tests; the old `async_gen_with_parameters_still_refused` test was renamed
`async_gen_wrong_arg_count_still_refused` and now asserts a real argument-
count mismatch, not "has any params at all"). CLAUDE.md's mandatory
gimple/codegen quality gate re-run clean: `test_gimple.py` (248/248),
`test_module_cache.py` (76/76), `make check-selfhost` (clean), a from-
scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:` lines), and
`compile_stdlib.py` (664/664, 0 unexpected failures) — no regression from
either quality-gate baseline. All 10 other async/generator-related test
suites (`test_gimple_generator_runner.py`, `test_async_execution.py`,
`test_async_parsing.py`, `test_async_runtime_scaffold.py`,
`test_async_void_return.py`, `test_async_with_lock_guard.py`,
`test_mutable_async_capture.py`, `test_nested_async_generic.py`,
`test_taskgroup.py`, `test_dual_cpp_elaboration.py`) also pass clean.

## Status (2026-08-18) — prior safety-net-only fix (superseded above)

Previously **FIXED** (as a safety-net minimum bar, not the real feature)
by restoring the pre-Phase-7 eligibility gate (`if fn.params: return
False` back in `_async_gen_quick_eligible`, `gimple_codegen.py`). Found
while investigating `test_gimple_async_runner.py`'s 5 newly-failing
`test_async_build_refused`-style tests (see the sibling
`bugs/hard/CODEGEN_async_value_consuming_call_and_forward_reference_
capability_gains.md` doc for the OTHER 4 of those 5, which turned out to
be genuine capability gains, not regressions — this is the one real
silent-regression among the five). This safety-net gate has now been
removed by the real fix documented above.

## Symptom

`test_gimple_async_runner.py`'s `async_gen_with_parameters_still_refused`
test asserted that a parametrized `async def f(n: int): yield n` consumed
via `async for x in f():` (the test's own source calls `f()` with the
required argument omitted) is honestly refused by
`gimple_codegen.compile_to_gimple_with_cpp` with a `"cannot compile
module"` message. It started failing — `compile_to_gimple_with_cpp`
returned successfully instead.

Building the returned `.cpp` for real (the way `test_gimple_async_runner.
py`'s own `_build_async_program` does, mirroring the real dual-output
build path) fails at the `g++` stage, NOT at `compile_to_gimple_with_cpp`:

```
error: too few arguments to function '_mojoasyncgen_f_Task _mojoasyncgen_f_impl(int64_t)'
    _mojoasyncgen_f_handle __agen_h_x = _mojoasyncgen_f_impl ().h;
                                        ~~~~~~~~~~~~~~~~~~~~~^~
```

i.e. `compile_to_gimple_with_cpp` silently "succeeds" while emitting C++
that cannot itself be compiled — worse than a silent wrong runtime value
in one respect (a real build genuinely fails, loudly, so nothing wrong
ever RUNS), but still a real regression in this file's own contract: every
other refusal in this suite is caught cleanly by
`compile_to_gimple_with_cpp` itself, with a clear message, not deferred to
a confusing downstream `g++` diagnostic several build stages later.

A SECOND, related failure mode: if the async generator is called with the
argument count its own signature actually requires (`f(10)` instead of the
test's `f()`), `_cpp_async_for_stmt`'s own long-standing `not it.args`
check refuses the call — but that failure is only ever observed as the
GENERIC whole-module "no suspend/resume state machine" fallback (the same
message any unrelated unsupported async/generator shape produces), not a
message that has anything to do with parameters specifically. Confirmed by
hand:

```python
async def f(n: int):
    yield n
    yield n + 1

async def main_driver():
    total = 0
    async for x in f(10):        # correct arg count this time
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
```

`compile_to_gimple_with_cpp` raises `"cannot compile module: function(s)
main_driver ... no suspend/resume state-machine transform ... falling
back to interpreting this module from source instead"` — a real refusal,
but not evidence params genuinely work; it's evidence they don't, via a
different code path than the test's own (buggy, wrong-arg-count) repro.

## Root cause

Commit `1b736d7` ("Phase 7: Async generator params + with") removed
`_async_gen_quick_eligible`'s `if fn.params: return False` gate and taught
`_gen_cpp_async_generator_unit` (the async generator's OWN C++ signature
emission) to accept and type real parameters. That half of the feature is
genuinely implemented.

But `_cpp_async_for_stmt` — `async for <var> in <call>():`, the ONLY
lexically-legal way real Python (and this codegen) ever consumes an async
generator — was never updated in the same commit (or any later one). Its
own docstring still says, verbatim, unchanged since before Phase 7: "This
narrow step supports exactly one shape: a plain identifier loop target,
over a **bare, argument-less call**". Its actual eligibility check is:

```python
it = s.iterable
if not (isinstance(it, CallExpr) and isinstance(it.func, IdentExpr)
        and not it.args and not getattr(it, 'kwargs', None)
        and it.func.name in self._async_gen_api):
    raise _UnsupportedAsyncShape(...)
```

`not it.args` is unconditional — it does not distinguish "the callee takes
no parameters" from "the callee takes parameters but this call textually
supplies zero arguments anyway" (a real-arg-count mismatch that ought to
be its own, separate, honest diagnostic, but isn't checked at all). When
`it.args` IS empty (the test's own shape — and the shape anyone
mechanically "un-refusing" a parameter-less-looking call site would most
naturally reach for), this check passes regardless of `f`'s real
signature, and the call-site codegen unconditionally emits
`{base}_impl ()` — zero arguments, always — with no reference to
`api['params']` at all:

```python
lines = [
    f"{indent}{base}_handle {handle_var} = {base}_impl ().h;",
    ...
]
```

So for a required-but-omitted argument, invalid C++ is emitted (the g++
failure above). For a correctly-supplied argument, the `not it.args` guard
itself refuses the call outright (the generic whole-module fallback).
Either way, real parameter *values* are never threaded from an `async
for`'s call site into the generator's own compiled signature — the
"params now supported" premise from Phase 7's commit message was never
actually true for the one real consumption path, and no test anywhere in
`test_gimple.py`/`test_gimple_async_runner.py` ever exercised
params-through-`async for` positively (Phase 7's own commit removed the
old `async_generator_with_param_honest_fallback` test with the comment
"params now supported", but added no replacement compile+run+correctness
test in its place).

## Fix

Restored the pre-Phase-7 gate in `_async_gen_quick_eligible`
(`gimple_codegen.py`):

```python
if fn.params:
    return False
```

This is the safe minimum bar per this project's own default posture
("restore refusal when a real fix looks nontrivial") — a genuinely
correct fix would need to update `_cpp_async_for_stmt` to (a) thread
`it.args` through into `{base}_impl(...)` the same way the sibling
async-awaits-async composition call site already does (`_cpp_expr`'s
`AwaitExpr` case, `call_args = ', '.join(self._cpp_expr(a) for a in
target.args)`), AND (b) validate the supplied argument count against
`api['params']` before proceeding (refusing honestly, not emitting
invalid C++, on a mismatch) — real, but nontrivial, follow-up work, out of
scope for restoring this regression's safety bar.

## Verification

- `python3 test_gimple_async_runner.py`: `async_gen_with_parameters_still_
  refused` back to PASS; 36/36 overall (was 31/36 before this session).
- Hand-verified both repros above (the test's own 0-arg-call shape, and
  the corrected `f(10)` shape) both now raise a clean `"cannot compile
  module"` from `compile_to_gimple_with_cpp` itself — no more deferred
  `g++`-stage failure.
- Full CLAUDE.md quality gate re-run (see this session's own commit
  message / sibling capability-gain doc for the shared gate results this
  fix was verified alongside).

## Confirmed occurrences

- `test_gimple_async_runner.py::async_gen_with_parameters_still_refused`
  (this session, 2026-08-18).
