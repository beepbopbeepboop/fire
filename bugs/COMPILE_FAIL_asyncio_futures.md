# COMPILE_FAIL: asyncio/futures.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/asyncio/futures.py`

## Status (updated 2026-08-10 — NOT actually blocked by tuple-valued yield; unaffected by this session's tuple-yield fix)

This session implemented real tuple-valued-`yield` support
(`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`/`_generator_yield_ctype`). Re-checked this file against it:
**`Future.__await__` was never actually blocked by tuple-yield** — its
own most recent (2026-08-09) analysis below already correctly
identifies the real blocker as a value-carrying `return` inside a
generator (`return self.result()`), a distinct gap this session's fix
does not touch (`_cpp_stmt`'s `ReturnStmt` case inside a generator body,
not the `YieldExpr`/promise-value-type machinery the tuple-yield fix
changed). Confirmed via a fresh re-run: `MOJO_DEBUG=1` reports the
IDENTICAL refusal message, character-for-character, as the 2026-08-09
status below — completely unchanged. This file was evidently included
in this session's initial file list by a broad keyword match ("tuple"-
adjacent language in its own doc, drawing an analogy between the two
gaps), not because tuple-yield is its actual blocker. No change to this
doc's classification; left open, unaffected.

## Status (updated 2026-08-06)

Re-ran; the original doc's snippet was stale/uninformative (a truncated
context line, not the real error). Current failure is an honest
up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) __await__ (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

`Future.__await__` uses `yield` (the standard `await`-protocol
implementation shape: `def __await__(self): ... yield self ...`). This
is a generator codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

Exit code: 1

### Re-verified 2026-08-09 against master `6feddbf` — reproduces, precise root cause confirmed

`MOJO_DEBUG=1` pinpoints the exact refusal reason (previously not
captured):

```
[gimple_codegen] generator method Future.'__await__' not eligible for
  C++ coroutine path, falling back to honest refusal: `return <value>`
  inside a generator is not supported (a generator's `return` ends
  iteration with no value, unlike an ordinary function's `return`)
```

Reading the actual source (`futures.py:292-298`):

```python
def __await__(self):
    if not self.done():
        self._asyncio_future_blocking = True
        yield self  # This tells Task to wait for completion.
    if not self.done():
        raise RuntimeError("await wasn't used with future")
    return self.result()  # May raise too.
```

Root cause (`gimple_codegen.py`'s `_cpp_stmt`, `ReturnStmt` case,
~line 24664): a generator's C++20 coroutine promise type in this
codegen has no channel for a Python generator's `return <value>`
(which in real Python semantics raises `StopIteration(value)` to the
driving `next()`/`.send()` call — the exact mechanism `yield from`/
`await` protocol implementations rely on to hand back a final result,
as this file's `__await__` does with `self.result()`). The coroutine
promise's `return_void()` only supports a bare `return`/fall-off-the-
end; a value-carrying `return` is refused outright rather than risk
emitting C++ that silently drops the value. This is the SAME class of
gap as the already-tracked tuple-valued-yield refusal
(`_infer_generator_yield_ctype`'s deliberate `None` return for
`TupleExpr`) — a shape the current single-scalar-yield coroutine
promise design genuinely cannot represent, not a missing case in an
otherwise-adequate lowering. Threading a real "return value" channel
through the promise type (plus every `yield from`/`await`-composition
call site that would need to actually consume it) is a broad change to
shared coroutine-promise machinery, not a narrow fix — matches this
project's structural-gap classification. Not attempted here.
