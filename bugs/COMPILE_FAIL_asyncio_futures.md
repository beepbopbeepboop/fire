# COMPILE_FAIL: asyncio/futures.py

## Status (2026-09-05 — Awaitable/Future RUNTIME now exists; this file's own compile blocker was already closed 2026-08-26, runtime residual partially addressed)

The compile/link blocker this doc tracks (`Future.__await__` /
`__iter__`'s value-carrying generator return) was resolved 2026-08-26 —
`mojo.py build .../futures.py` exits 0. The remaining residual was
"await-composition (a compiled Task consuming `__await__`'s return slot)"
plus transitive `collections`/`inspect` source-fallback.

This pass built the Awaitable/Future protocol runtime on the A3
stack-switch substrate (see `COMPILE_FAIL_asyncio_queues.md`'s 2026-09-05
entry for the full description): heap-allocatable `MojoFuture`/Event
handles with a waiter list and cross-coroutine wakeup
(`runtime/mojo_coro_gen.c` / `mojo_async_sched.c` / `mojo_wd.h`), plus
codegen lowering of `await <future>` / `await <ev>.wait()` /
`create_future()` / `.set_result()`. C-level cross-coroutine wakeup is
unit-tested (`runtime/test_mojo_future.c`); `await <resolved future>`
end-to-end in `test_coro_future_await.py`.

This does NOT by itself change futures.py's status — futures.py defines
`Future` as a Python class with `__await__` as a generator, which the
compiled path lowers differently from the native-handle model this
runtime provides; wiring `Future.__await__`'s `yield self` onto
`__mojo_async_await_future` (so a real Python `Future` subclass composes
with the native waiter list) is the next step. Doc kept open; the
compile blocker it was opened for stays closed.

## Status (updated 2026-08-27/28 — the link-mode module-value gap below is FIXED; ADVANCED, not closed: a separate, pre-existing, out-of-scope transitive gap remains)

Implemented the fix this doc's own prior entry precisely specified:
`gimple_gen_resolve.py`'s `_register_link_imports`, in the "not a
concrete export" branch for a `from PKG import SUBMODULE`-bound name,
now checks `gen._from_import_name_is_submodule(stmt.module, name)` and
routes the submodule into `gen._link_inline_modules` (the SAME fallback
mechanism nearby branches already use for a module this scan couldn't
otherwise link against) — this inline-compiles the submodule into the
same translation unit, which naturally populates `func_return_types`
for all its top-level defs via the normal `imported_stmts` machinery, so
a later bare-value read (`isfuture = base_futures.isfuture`) resolves
through `_lower_MemberExpr`'s existing `node.member in
gen.func_return_types` branch instead of falling through to the
AttributeError.

Verified via a minimal 2-file package repro (`pkg/base.py`: `def
isfuture(x): return True`; `pkg/main.py`: `from . import base;
isfuture = base.isfuture; ...; isfuture(1)`) — this exact shape
previously reproduced the `AttributeError: isfuture` crash; with the
fix it now builds AND runs correctly (`./main` prints `yes`, exit 0).

Re-verified against the real file: `python3 mojo.py build
.../Lib/asyncio/futures.py` no longer reaches the `isfuture` crash —
the `from . import base_futures` / `isfuture = base_futures.isfuture`
shape this doc tracks is resolved. The whole-program build still does
not complete within the 300s safety window: it now spends its budget
falling back to interpreting `collections/__init__.py` and `inspect.py`
from source, both blocked by the separately-tracked, explicitly
out-of-scope `Counter[...] = .../OrderedDict[...] = ...` dict-subclass
subscript-store gap (see `bugs/COMPILE_FAIL_collections___init__.md`).
That gap is unrelated to this doc's own tracked blocker and pre-dates
this fix. Doc stays open (file doesn't build end-to-end within budget)
but the LINK-MODE MODULE-VALUE GAP THIS DOC TRACKS IS CLOSED.

## Status (re-verified 2026-08-26, this session — runtime residual root-caused MORE PRECISELY, not fixed)

Fresh `python3 mojo.py build .../Lib/asyncio/futures.py`: still exits
0 ("Built: futures"). Fresh run: still `Unhandled exception:
AttributeError: isfuture` (unchanged crash).

Root-caused further this session, past the "module-API gap" framing
below: the trigger is `from . import base_futures` (line 14) followed
by `isfuture = base_futures.isfuture` (line 20) — a plain FUNCTION
defined in a real sibling module, read as a VALUE (not called) and
bound to a module-level global. Minimal 2-file repro (package
`__init__.py` + `base.py` defining `def isfuture(x): return True` +
`main.py` doing `from . import base; isfuture = base.isfuture`)
reproduces the identical crash — confirms this is NOT asyncio-specific
or CPython-specific, a general gap.

Traced into `mojo.py build`'s actual pipeline: `driver.compile_program`
(link-mode: per-import dylibs + CAS + reflection), NOT the single-TU
`do_imports=True` inline path `gimple_module_gen.py`'s
`modules_to_compile`/`_compile_imported_module` machinery drives (that
inline mechanism DOES correctly register an imported module's
functions into `func_return_types`, verified via tracing — but
`compile_module_to_c`/`build_stdlib_dylib.py`'s harness, and by
extension `compile_stdlib.py`'s gate check, ALSO default to
`do_imports=False`, so neither exercises this path — this bug is
invisible to the standard gate). `_lower_MemberExpr` (gimple_gen_exprs.py
~line 778) DOES have a real, working branch for exactly this shape
("module_name in gen.imported_symbols and node.member in
gen.func_return_types" -> emit a `_funcptr_<csym>` value) — the gap is
upstream of that check, somewhere in how `driver.compile_program`'s
link-mode path populates (or fails to populate) `func_return_types`
for a module bound via a bare `from . import <submodule>` (as opposed
to `from <submodule> import <symbol>`, which likely follows a
different, working registration route via per-import dylib reflection).

NOT attempted this session: root-causing further requires
understanding `driver.py`'s link-mode module-resolution/reflection
system in more depth than this pass's remaining time allowed, and this
project's own history warns against a rushed fix to shared
call-resolution machinery. Recorded here precisely so a future pass
doesn't have to re-discover the do_imports=False vs. link-mode
distinction from scratch.


## Status (updated 2026-08-26, worktree fix/opencode-group4 — RESOLVED at the
## compile/link level: the build now EXITS 0 and produces a binary; both
## `Future.__await__` and `Future.__iter__` compile as real C++20 coroutines)

The long-standing blocker — a value-carrying `return self.result()`
inside a generator body — is FIXED this session. Design (deliberately
NOT the "promise return_value(v) method" this doc's earlier entries
assumed was required): the C++20 rule makes return_void XOR
return_value mandatory per promise (this promise needs return_void for
every ordinary generator), and this project's GCC 15 has a documented
coroutine-frame-layout bug with extra promise FIELDS — so instead each
ELIGIBLE generator unit now emits its own `extern "C" <T>
{base}_return_slot = 0;` global; the body's valued `return <expr>`
stores `(T)(expr)` into it right before co_return. Python's
StopIteration(value) semantics are thereby materialized without
touching the shared promise shape at all. Eligibility is conservative
(at least one valued return; NO bare return anywhere; body's LAST
top-level statement is the valued return so no path completes without
storing); anything else keeps the honest refusal.

Two supporting inference fixes were needed:
- `_generator_yield_ctype(..., include_returns=False)` for the
  GENERATOR translation path: the walk's ReturnStmt branch (built for
  async functions) was poisoning yield-type unification whenever a
  generator's return expression didn't resolve (`return self.result()`
  → None → whole-generator refusal).
- bare `yield self` in a generator METHOD now types as the receiver's
  own struct pointer (`_infer_simple_expr_ctype`'s new
  `self_struct_ctype` param), composing with the existing
  struct-pointer-yield support instead of defaulting to int64_t and
  then failing g++ on `co_yield self`.

Verified end-to-end: fresh `python3 mojo.py build .../Lib/asyncio/
futures.py` **exits 0** ("Built: futures", 0 compiler errors); the
companion .cpp passes `g++ -std=c++20 -fsyntax-only` clean. Full
mandatory gate: `test_gimple.py` 256/256, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
EXIT=0 with **0 skip lines**.

Runtime residual (NOT a compile gap): the binary's top-level init hits
module-API gaps of transitively-imported real-CPython modules
(consistent with pathlib/zipfile._path's documented residuals) —
await-composition (a compiled Task consuming __await__'s return slot)
remains future async-runtime work, but the file itself compiles,
links, and produces a binary, which is what this COMPILE_FAIL doc
tracks.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, superseded above)

Re-ran an isolated `compile_to_gimple` check fresh (post this session's
4 coroutine-emitter fixes landed for COMPILE_FAIL_Apple___main__.md:
`mojo_c_getenv`/platform/subprocess runtime-call whitelist, zero-arg
`print()`, `char* * int` string-repeat lowering, f-string interpolation
in `_cpp_expr`'s `StringLiteral` case). None of those touch this file's
blocker — confirmed byte-for-byte identical refusal: `function(s)
__await__, __iter__ (generator function(s), contain a yield/yield
from)`. `Future.__await__`'s `return self.result()` still has no
promise `return_value(v)` channel to lower into (see the 2026-08-09
analysis below, still accurate). Also confirmed: this and
COMPILE_FAIL_asyncio_queues.md do NOT share a narrowly-fixable root
cause despite both being in the same async-codegen-eligibility/
promise-design gap family — this file's gap is the coroutine PROMISE's
missing value-return channel (reached only after a function/method IS
accepted as coroutine-eligible); queues.py's gap is the earlier
`_async_quick_eligible` AWAIT-SHAPE whitelist rejecting it before that
promise machinery is ever reached. Two different mechanisms in the
same subsystem, not one fix. Structural, not attempted; doc kept open.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. The blocker (`Future.__await__`'s value-carrying `return self.result()` inside a generator -- the coroutine promise has no `return_value(v)` channel) is unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still a promise-design-level gap; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/asyncio/futures.py`

## Status (re-verified 2026-08-23 against master 626f3f0 — unchanged, STILL-OPEN structural)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/asyncio/
futures.py` fresh: still fails with the IDENTICAL up-front refusal —
`cannot compile module: function(s) __await__ (generator function(s),
contain a yield/yield from)`. Unaffected by the compiled-generator
work landed since the last pass (including this cluster's fd909e9,
which only tightened the coroutine-body refusal contract): the blocker
remains exactly the value-carrying `return self.result()` inside a
generator analyzed below — the C++20-coroutine promise in this codegen
still has `return_void()` only, no `return_value(v)` channel, and no
`yield from`/`await` consumer machinery to read one back. Feature-sized
promise-design change, not attempted; see the 2026-08-09 analysis below.

## Status (updated 2026-08-10 — historical)

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
