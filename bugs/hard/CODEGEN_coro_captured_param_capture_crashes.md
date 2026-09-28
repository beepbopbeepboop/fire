# HARD BUG: a nested `async def` capturing an enclosing function's PARAMETER crashes the compiler

**State: item 1 FIXED 2026-09-27; items 2 and 3 still OPEN.** Found
2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_coro_nested_async_closure_capture.md`. That doc's headline closure —
Increment E, "struct capture now WORKS" — is real and verified. But the
Increment B it also records as landed (captured **parameter**) had never
worked since Increment E landed: it raised an unhandled `ValueError` out of
the compiler on every annotated-param capture, and the regression suite that
was supposed to catch it is orphaned (0/9, not in `tools/suite.py`) and partly
asserts the pre-Increment-E answer.

Split out on purpose: "nested-async struct capture works" and "a captured
parameter works" are separate claims, and putting them in one file is what let
the second die inside the first's closing commit.

## Status

### Item 1 — FIXED. The `ValueError` is gone; captured parameters box and mutate correctly.

Root cause confirmed as the doc states: a tuple-arity mismatch. The Increment
B producer built a 2-tuple while Increment E's three consumer passes unpacked
3-tuples. **Fixed structurally, not with the one-liner** the doc offers as the
alternative: the plan's entries are now a small named class `_Capture`
(`decl` / `kind` / `struct_name`) with ONE constructor, and both producers
(`_outer_boxable_locals` for a body-local, `_nested_async_capture_plan` for a
parameter) go through it. A future widening is then a missing attribute at the
producer rather than a `ValueError` three passes downstream, and the two
producers cannot disagree about the shape at all — which is exactly the
coupling that let the regression through, since being in the same file
type-checks nothing about a tuple's arity.

Verified (all via `fire.py build`, `MOJO_CORO=stackswitch` default, real
compile + link + run, CPython alongside):

| program | CPython | compiled |
|---|---|---|
| the doc's repro (`seed: Int`, `seed += 2`) | `12` | `12` |
| `seed: Int` + `ratio: Float64` + `tag: String` in ONE nested async | `12 2.0 ab` | `12 2.0 ab` |
| three params **and** a struct local in the same nested async | `2 2.0 ab 2` | `2 2.0 ab 2` |
| Increment E struct capture (`p.x += 5`, `p = Point(10)`) | `15` | `15` |
| Increment C (`acc += 1.5` twice, `msg += "b"`) | `1.5 ab` | `1.5 ab` |

The third row is the one that mixes both plan producers in a single
`cap_map`; the fourth and fifth are unchanged-behaviour checks on the two
increments the crash was hiding behind.

**A doc claim this contradicts.** The doc's "Verified genuinely fixed" list
records Increment A (`var n = compute()` captured, `n += 1` → `43`) as working
"via … `fire.py build`". Re-tested on the pre-fix tree: it did **not** build.
`_strict_init_kind` consults `_FUNC_RET_KIND`, which is populated only from
`return_type` ANNOTATIONS, so `def compute(): return 42` (unannotated) left
`var n = compute()` unboxable, the capture plan came back `None`, the nested
async fell through to the C++ path, and that emitter threaded a capture
parameter into `_mojoasync_run_bump_start(int64_t *)` that the `create_task`
call site did not pass:

    inc_a.mojo:20:9: error: too few arguments to function
    '_mojoasync_run_bump_start'; expected 1, have 0

Identical on a pristine copy of the pre-fix tree, so not a regression from
anything here. It is now fixed as a side effect of the other bug's work:
`_scan_func_ret_kinds` reads an unannotated `def`'s return kind off its
unanimous scalar-literal `return`s (`_literal_return_kind`), so the same
program prints `43`. With an explicit `-> Int` it already worked before.

### Item 2 — still OPEN. The regression file is orphaned at 0/9.

Not touched, deliberately: another agent owns
`test_coro_nested_async_capture.py`'s comments, and the brief for this pass
was to leave that file alone. What fixing it takes, measured:

Renaming the five pre-rename runtime filenames in `_RUNTIME_SRCS`
(`mojo_async_runtime.cpp` → `fire_async_runtime.cpp`, `mojo_coro.c` →
`fire_coro.c`, `mojo_coro_gen.c` → `fire_coro_gen.c`, `mojo_async_sched.c` →
`fire_async_sched.c`, `mojo_coro_ctx_aarch64.S` → `fire_coro_ctx_aarch64.S`,
and `mojo_coro_ctx_generic.c` → `fire_coro_ctx_generic.c` on the non-arm64
branch — seven strings in total, `:64-71` and `_CORO_CTX_SRC` above it) turns
**0 passed / 9 failed into 8 passed / 1 failed**, measured on a throwaway copy
with only those renames applied. The 8 that come alive include this bug's own
case, verbatim:

    PASS  captured parameter seed=10, +2 -> 12

So item 1 is now covered by a *registered* test too
(`nested_async_captures_enclosing_param_int` and
`nested_async_captures_param_and_struct_local` in
`test_gimple_generator_runner.py`, both stdout-asserting and both in the
`coroutine` bucket's dependency chain), and this file remains the only
missing coverage for the other six cases.

The one case that stays red is `test_struct_capture_refused_to_cpp` (`:384`),
and it is red for the reason this doc gives: it asserts the pre-Increment-E
behaviour. Its own failure detail is `box shim present -- struct capture was
wrongly boxed`. Its `except RuntimeError` arm also still describes the old
world — Increment E makes struct capture BOXED and lowerable, so the shape
compiles and the "refused (cpp path), not boxed" branch is now dead code.
Fixing it means inverting the assertion to "compiles AND boxes AND prints the
right value", which is a behavioural change to a test nobody has re-derived
since Increment E landed. Not attempted here.

Also still true and still worth fixing: the file is in no bucket in
`tools/suite.py`, so none of this runs in the gate.

### Item 3 — still OPEN, and deliberately not attempted.

The `async for x in gen():` driven in the ENCLOSING function printing `0`
instead of `11`. Unchanged by this pass. The doc's own attribution is right
and worth restating because it is why this is not a capture bug: the same
wrong `0` appears with no capture at all, so it is the generic "a
`MojoGenerator *` is not a driveable iterable in compiled code" gap, which
lives in the ordinary loop lowering and is warned about at compile time
(`mojo_unsupported_iter`).

## 1. Capturing an enclosing parameter was a hard compiler crash — FIXED, see Status

    def run(seed: Int) raises:
        @parameter
        async def bump():
            seed += 2
        var t0 = create_task(bump())
        t0.wait()
        print(seed)

    def main():
        run(10)

CPython: `12`. This compiler, before the fix: a raw Python traceback, no
binary, no Mojo-level diagnostic.

    ValueError: not enough values to unpack (expected 3, got 2)
      File ".../mojo/middle/coro.py", line 2666, in _apply_nested_async_capture
        box_kind = {n: k for n, (_d, k, _s) in cap_map.items()}

Reproduced for every annotated scalar param type — `Int`, `Float64` and
`String` all crashed identically. It was not the shape, it was the code path.

Root cause: a tuple-arity mismatch introduced when Increment E widened the
capture-plan entry from 2 fields to 3. Both halves of it are now described in
Status; the line numbers in this section are the pre-fix ones and the fix is
the named `_Capture` shape rather than the `(None, k, None)` one-liner, for
the reason given there.

## 2. The regression suite for this feature is orphaned, and one case asserts the wrong answer — still OPEN

`test_coro_nested_async_capture.py` is **0 passed, 9 failed**, and it is not
registered in `tools/suite.py` — `python3 tools/suite.py --list` shows the
whole `coroutine` bucket is one test, `coro` = `test_coro_runtime.py`. So no
gate step runs this file, and the `coro 20/20` in CLAUDE.md is 20 C-runtime
cases, not one of these. Status above gives the measured effect of fixing the
filenames; this section is the diagnosis, unchanged.

The 9 failures are three different things, and the removed doc's Verification
section attributes all of them to one:

| # | cause |
|---|---|
| 7 | `_RUNTIME_SRCS` (`test_coro_nested_async_capture.py:64-71`) still names the **pre-rename** runtime files: `mojo_async_runtime.cpp`, `mojo_coro.c`, `mojo_coro_gen.c`, `mojo_async_sched.c`, `mojo_coro_ctx_aarch64.S`. All five are `fire_*` now; the file exists as `runtime/fire_async_runtime.cpp`. The harness dies compiling the runtime, before the program under test is ever compiled. |
| 1 | `test_captured_parameter` — item 1 above, `ValueError` from `coro.py:2666`. **Not** the missing-file problem, and the removed doc's "8/9 … both are this checkout's pre-existing missing runtime/mojo_async_runtime.cpp" folds it in wrongly. Since item 1 is fixed this case is now masked by the missing-file problem like the other 7, which is why it needs the rename before it can pass — not before it can be *correct*. |
| 1 | `test_struct_capture_refused_to_cpp` — **asserts the pre-Increment-E behaviour and now fails on correct code.** Its own failure detail is `box shim present -- struct capture was wrongly boxed`. Increment E deliberately made struct capture boxed, so `check(..., '__mojo_box_new_' not in c)` (`:414-415`) is now an anti-test: fixing item 1's sibling behaviours while leaving this file alone keeps it red, and "fixing" it the easy way would re-break Increment E. |

**This is the same failure mode as `CODEGEN_bytes_silent_wrong_values.md`: a
test that encodes the pre-fix answer as expected output is not merely stale,
it is the reason the defect survives.** Renaming the five runtime files in
`_RUNTIME_SRCS` turns 7 dead cases into live ones; expect some of them to
fail, which is the correct outcome, not a regression. Measured: 8 pass, and
the 1 that fails is the anti-test, not a real defect.

The gate-level coverage that *does* exist is fine and green: `test_gimple.py`
(324/324 as of 2026-09-27), including `nested_async_struct_capture_boxes_pointer`
and `nested_async_gen_capture_from_async_for_refused`. But both assert on the
**generated C**, never on stdout, so neither can see a wrong *value* — which is
why Increment E's `prints 15` had to be verified by hand, as the removed doc
admits. Item 1's coverage is now stdout-asserting and in a file the `coroutine`
bucket's chain does reach
(`test_gimple_generator_runner.py::nested_async_captures_enclosing_param_int`,
`::nested_async_captures_param_and_struct_local`); the other six cases in the
orphaned file still have no gate coverage at all.

## 3. Lower severity, capture-independent: a nested async generator driven by `async for` in its OWN function — still OPEN

The removed doc scopes its exclusion narrowly and correctly: the unthreadable
case is `async for x in gen():` inside a *further-nested `async def` sibling*,
and that IS honestly refused (verified — the
`capture box cannot be threaded into a driven consumer` message). But the same
construct consumed in the **enclosing** function, which the doc never lists as
excluded, builds, runs, exits 0 and prints a wrong value:

    def outer() raises:
        var acc = 0
        async def gen():
            acc = acc + 1
            yield 10
        async for x in gen():
            acc = acc + x
        print(acc)

CPython (`async def outer` + `asyncio.run`): `11`. Compiled: `0`.

Not attributed to the capture machinery: the identical wrong `0` appears with
**no capture at all** (`async def gen(): yield 10` + `async for`), so this is
the generic "a `MojoGenerator *` is not a driveable iterable in compiled code"
gap, and `fire.py build` does emit a warning for it:

    mojo_unsupported_iter: 'for' loop over unsupported iterable type c12.mojo:6:
      MojoGenerator * (codegen has no lowering for this container/iterator shape;
      the loop body runs zero times)

Recorded because the removed doc's §5.6 scope note says both refused shapes
are "correctly refused rather than miscompiled", and this neighbouring shape is
neither refused nor correct — it is warned-about-and-wrong. The capture box IS
emitted for it (`__mojo_box_new_i64`/`_get_i64`/`_set_i64` all present in the
generated C), so it looks handled from the outside.

## Verified genuinely fixed, for the record

So nobody re-opens them (all real compile + link + run via the A3 stack-switch
path, `MOJO_CORO=stackswitch`, plus `fire.py build`):

- **Increment E, struct capture**: `var p = Point(10)` mutated in a nested
  `async def` prints `15`. Also the mixed case — struct + int + float + string
  captured into one nested async prints `2 6 2.0 ab`. **Re-verified
  2026-09-27** as part of item 1's fix (Increment E must keep working while the
  plan entries it added a field to are being reshaped): `15` still.
- **Increment A, non-literal initializer**: `var n = compute()` captured,
  `n += 1` → `43`. **Re-verified 2026-09-27, and this doc's claim needed
  correcting**: it did not build before this pass, for an unannotated
  `def compute()`. See Status. It prints `43` now, and did before if
  `compute` carried an explicit `-> Int`.
- **Increment C, float and string boxes**: `acc += 1.5` twice → `3.0`;
  `msg += "b"` → `ab`. **Re-verified 2026-09-27**: `1.5 ab`.
- **Item 4, cross-closure `TaskGroup` stress**: `caller()` in a sibling nested
  function creating 10x10 tasks through the captured-`rawCounter` box prints
  `100`. (The doc's 10,000-task figure was not re-run — the `TaskGroup` import
  chain does not build through `fire.py build` in this checkout for unrelated
  stdlib reasons, so this was verified through the single-TU stack-switch path
  at 10x10 instead.) **Re-verified 2026-09-27** on the renamed harness: both
  the 100-task single-scope and the **10,000-task** cross-closure cases print
  `10000`, so the smaller figure above is the conservative one, not the real
  ceiling.
- **Increment D's honest refusal**, for the shape the doc actually scopes:
  message names the construct and the reason, on both backends.

## Also drifted: a baseline both removed docs cite — now attributed

`python3 test_coro_bugs.py` reported `CFAIL=1 LOWERED=2 RAISE=6` here
(2026-09-27), measured **identically on a pristine pre-fix copy of the
tree**, so none of it was attributable to the item-1 fix. Both removed docs
record the baseline as `LOWERED=3/RAISE=6`, so the `CFAIL=1` was a real
drift and the stale number was the `LOWERED`.

**Attributed, same session, later pass**: the CFAILing module is
`ipaddress` (`Lib/ipaddress.py:1548`, `self.hosts = self.__iter__`, 77
`__mgco_` refs then `gcc -fgimple -fsyntax-only` fails with `expected
expression before 'sizeof'`) — its own doc,
`bugs/CODEGEN_generator_function_Lib_ipaddress.md`, already scopes this as
needing "a dynamic-class-object-as-callable-value model", explicitly
"genuinely feature-sized, not attempted": the same missing first-class-
callable-value representation `CODEGEN_generator_lambda_expr_unsupported.md`
(variadic lambda call sites) and
`COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` (kw-only param invoked
as callee) are both blocked on. Not a fresh mystery. The count is now
`CFAIL=1 COMPILE=1 LOWERED=2 RAISE=5` — `test_test_string_test_string`
moved off RAISE to COMPILE as a side effect of unrelated fixes landed the
same session (container ctor-arg typing, loop-target rebind, `print`
dispatch); not independently chased down further since COMPILE is already
a clean outcome.

## Where

Line numbers are pre-fix; the shapes they named are now as follows.

- `mojo/middle/coro.py` — `_Capture` (the plan's named entry, replacing the
  2-tuple/3-tuple pair), its two producers `_outer_boxable_locals` and
  `_nested_async_capture_plan`, and its three consumer passes in
  `_apply_nested_async_capture` — item 1.
- `test_coro_nested_async_capture.py:64-71` (dead runtime filenames, plus
  `_CORO_CTX_SRC` just above) and `:384-424`
  (`test_struct_capture_refused_to_cpp`, inverted expectation) —
  item 2. Its module docstring at `:1-44` also still describes the
  cross-closure shape as unimplemented ("`local_maps` is keyed by the DIRECT
  enclosing function only"), which item 4 above contradicts.
- `tools/suite.py` — the absence of any registered step for
  `test_coro_nested_async_capture.py`. The human owns this file; the row to
  add is a `cmd` test over `test_coro_nested_async_capture.py` in the
  `coroutine` bucket, and it should not be added until the filenames and the
  inverted expectation are fixed, or the gate gains a permanently red step.
