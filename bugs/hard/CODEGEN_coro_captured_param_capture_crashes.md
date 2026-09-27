# HARD BUG: a nested `async def` capturing an enclosing function's PARAMETER crashes the compiler

**State: OPEN.** Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_coro_nested_async_closure_capture.md`. That doc's headline closure —
Increment E, "struct capture now WORKS" — is real and verified. But the
Increment B it also records as landed (captured **parameter**) has never
worked since Increment E landed: it raises an unhandled `ValueError` out of
the compiler on every annotated-param capture, and the regression suite that
was supposed to catch it is orphaned (0/9, not in `tools/suite.py`) and partly
asserts the pre-Increment-E answer.

Split out on purpose: "nested-async struct capture works" and "a captured
parameter works" are separate claims, and putting them in one file is what let
the second die inside the first's closing commit.

## 1. Capturing an enclosing parameter is a hard compiler crash

    def run(seed: Int) raises:
        @parameter
        async def bump():
            seed += 2
        var t0 = create_task(bump())
        t0.wait()
        print(seed)

    def main():
        run(10)

CPython: `12`. This compiler: a raw Python traceback, no binary, no Mojo-level
diagnostic.

    ValueError: not enough values to unpack (expected 3, got 2)
      File ".../mojo/middle/coro.py", line 2666, in _apply_nested_async_capture
        box_kind = {n: k for n, (_d, k, _s) in cap_map.items()}

Reproduces for every annotated scalar param type — `Int`, `Float64` and
`String` all crash identically. It is not the shape, it is the code path.

Root cause: a tuple-arity mismatch introduced when Increment E widened the
capture-plan entry from 2 fields to 3.

- `mojo/middle/coro.py:2445` — the Increment B branch still builds a **2-tuple**:
  `plan[n] = (None, k)`, where `None` is the (absent) `VarDecl`.
- `mojo/middle/coro.py:2666`, `:2674`, `:2681` — Increment E's
  `_apply_nested_async_capture` unpacks **3-tuples** `(decl, kind, struct_name)`
  on all three of its passes over `cap_map`.

So the branch is reached and then dies. Not a refusal, not a fallback to the
cpp path — a `ValueError` escaping through `module_gen.gen_module_impl` into
the user's terminal.

`git log -S` dates the regression precisely: commit `bd4eefc` ("nested-async
closure capture -- non-literal init, captured param, float/string box
(Increments A/B/C)") wrote the 2-tuple and had 2-tuple consumers; commit
`ad7d0ea` ("Six bugs/hard docs: ...") added `_BOX_STRUCT_OF`, widened the
consumers to 3-tuples, and closed the bug doc — **without touching the
producer**. `ad7d0ea` is the same commit that wrote the `**State: CLOSED.**`
banner and Increment E's "LANDED" section.

The one-line fix is `plan[n] = (None, k, None)`; the structural fix is to give
the plan a named shape instead of a positional tuple that three passes unpack
blindly. Given the third field is only meaningful for Increment E's struct
captures, a `namedtuple`/small dataclass would make the next widening a
type error at the producer rather than a `ValueError` in a consumer.

## 2. The regression suite for this feature is orphaned, and one case asserts the wrong answer

`test_coro_nested_async_capture.py` is **0 passed, 9 failed**, and it is not
registered in `tools/suite.py` — `python3 tools/suite.py --list` shows the
whole `coroutine` bucket is one test, `coro` = `test_coro_runtime.py`. So no
gate step runs this file, and the `coro 20/20` in CLAUDE.md is 20 C-runtime
cases, not one of these.

The 9 failures are three different things, and the removed doc's Verification
section attributes all of them to one:

| # | cause |
|---|---|
| 7 | `_RUNTIME_SRCS` (`test_coro_nested_async_capture.py:64-71`) still names the **pre-rename** runtime files: `mojo_async_runtime.cpp`, `mojo_coro.c`, `mojo_coro_gen.c`, `mojo_async_sched.c`, `mojo_coro_ctx_aarch64.S`. All five are `fire_*` now; the file exists as `runtime/fire_async_runtime.cpp`. The harness dies compiling the runtime, before the program under test is ever compiled. |
| 1 | `test_captured_parameter` — item 1 above, `ValueError` from `coro.py:2666`. **Not** the missing-file problem, and the removed doc's "8/9 … both are this checkout's pre-existing missing runtime/mojo_async_runtime.cpp" folds it in wrongly. |
| 1 | `test_struct_capture_refused_to_cpp` — **asserts the pre-Increment-E behaviour and now fails on correct code.** Its own failure detail is `box shim present -- struct capture was wrongly boxed`. Increment E deliberately made struct capture boxed, so `check(..., '__mojo_box_new_' not in c)` (`:414-415`) is now an anti-test: fixing item 1's sibling behaviours while leaving this file alone keeps it red, and "fixing" it the easy way would re-break Increment E. |

**This is the same failure mode as `CODEGEN_bytes_silent_wrong_values.md`: a
test that encodes the pre-fix answer as expected output is not merely stale,
it is the reason the defect survives.** Renaming the five runtime files in
`_RUNTIME_SRCS` turns 7 dead cases into live ones; expect some of them to
fail, which is the correct outcome, not a regression.

The gate-level coverage that *does* exist is fine and green: `test_gimple.py`
316/316, including `nested_async_struct_capture_boxes_pointer` and
`nested_async_gen_capture_from_async_for_refused`. But both assert on the
**generated C**, never on stdout, so neither can see a wrong *value* — which is
why Increment E's `prints 15` had to be verified by hand, as the removed doc
admits.

## 3. Lower severity, capture-independent: a nested async generator driven by `async for` in its OWN function

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
  captured into one nested async prints `2 6 2.0 ab`.
- **Increment A, non-literal initializer**: `var n = compute()` captured,
  `n += 1` → `43`.
- **Increment C, float and string boxes**: `acc += 1.5` twice → `3.0`;
  `msg += "b"` → `ab`.
- **Item 4, cross-closure `TaskGroup` stress**: `caller()` in a sibling nested
  function creating 10x10 tasks through the captured-`rawCounter` box prints
  `100`. (The doc's 10,000-task figure was not re-run — the `TaskGroup` import
  chain does not build through `fire.py build` in this checkout for unrelated
  stdlib reasons, so this was verified through the single-TU stack-switch path
  at 10x10 instead.)
- **Increment D's honest refusal**, for the shape the doc actually scopes:
  message names the construct and the reason, on both backends.

## Also drifted: a baseline both removed docs cite

`python3 test_coro_bugs.py` now reports `CFAIL=1 LOWERED=2 RAISE=6`. Both
removed docs record its baseline as `LOWERED=3/RAISE=6`. The newly-CFAILing
module is `ipaddress`, which lowers to 77 `__mgco_` refs and then fails
`gcc -fgimple -fsyntax-only` with `expected expression before 'sizeof'`
(`Lib/ipaddress.py:1548`) after a long chain of imported-module errors
(`_collections_abc`, `dis`, `enum`, `dataclasses`, `re._compiler`, `typing`,
`argparse`, `ast`). **Not attributed** — pinning it needs a build of the
parent commit, which the no-git-mutation constraint for this verification pass
forbade. Flagged so the next session does not read the stale number as
current.

## Where

- `mojo/middle/coro.py:2445` (producer, 2-tuple) vs `:2666`/`:2674`/`:2681`
  (consumers, 3-tuple) — item 1.
- `test_coro_nested_async_capture.py:64-71` (dead runtime filenames) and
  `:377-415` (`test_struct_capture_refused_to_cpp`, inverted expectation) —
  item 2. Its module docstring at `:1-44` also still describes the
  cross-closure shape as unimplemented ("`local_maps` is keyed by the DIRECT
  enclosing function only"), which item 4 above contradicts.
- `tools/suite.py` — the absence of any registered step for
  `test_coro_nested_async_capture.py`.
