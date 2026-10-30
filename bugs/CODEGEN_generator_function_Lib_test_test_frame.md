# CODEGEN_generator_function: Lib/test/test_frame.py

## Status (2026-10-29, partial fix: a nested generator can call a sibling `def` — the `gen` cluster-A shape lowers)

Landed (the doc's recommended next step, the sibling-helper half of `gen`):
a nested generator's coroutine body could not see the `def`s beside it in
the enclosing function, so `yield nested()` with `nested` a sibling was
refused as an unresolved callee even when `nested` captures nothing.
`_nested_generator_sibling_defs` (`mojo/backend_gimple/cpp_async.py`) maps
each nested generator to its enclosing def's sibling defs, wired through
`module_gen.py` as `gen._nested_gen_sibling_defs`, and
`_cpp_compile_nested_sync_helpers` now considers those as candidates
alongside the generator's own nested defs. The existing rules are unchanged:
a sibling that captures an enclosing local is still refused (pinned by
`test_regression_gen_sibling_capturing_local_still_refused`).

Verified: `GEN_SRC` compiles and its C++ calls `_mojogen_gen_h_nested()`
(`test_regress_codegen_generator_frame.py`, now a positive pin); the JIT
run prints `1`. `test_gimple_generator_runner.py`: 273 pass.
`test_gimple.py`: 407 pass, 1 fail — `test_print_of_a_function_value_is_not_a_decimal_address`
(decorator `deco` on `step`, `COMPILE_FAIL_decorator_application_dropped`),
which fails identically with this change reverted.

NOT done — this file still cannot compile as a whole, and the frame part of
`gen` is unchanged:

- `gen` as written in the file: `nested()` returns `sys._getframe().f_generator`,
  so the frame-model decision above (option (a), keep refused) still stands.
- `t3`: unchanged; see the two entries below.

## Status (2026-10-29, t3 question answered — the module-level/class-method split is two lowerings, one silent; the silent half now refuses)

Question 2 below is answered by measurement. The module-level `async def t3`
does NOT go through `cpp_async`'s return-type check at all: the stack-switch
lowering in `mojo/middle/coro.py` (`_lower_one_async`) owns async units and
hard-codes their result slot as `int64_t`. For the frame shape itself the
module-level output is a runtime raise, not a silent value: `sys._getframe()`
lowers to `mojo_module_not_compiled("sys", "_getframe")`, which raises
`NotImplementedError` before the `return` is reached. So `t3` as written is
honest at module level and refused at class level, and the class-level
refusal is not over-broad for this shape.

What WAS silently wrong, and is now refused (`_async_return_refusal` in
`mojo/middle/coro.py`): an async function whose `return` values disagree on
kind (`return 1` / `return "s"`) — both were written into the one int64 slot,
and the string awaited as its pointer printed as a number. Measured, pre-fix:
`print(await f(0))` printed `4367193456`. A float `return` (`return 1.5`) was
awaited as `1`; it is refused too, since the slot cannot carry a double.
Tests: `test_async_void_return.py` (`test_async_mixed_return_kinds_refused`,
`test_async_float_return_refused`, `test_async_same_kind_returns_still_compile`).

Still open for THIS file: `gen` and `t3` as written still refuse/raise as
described in the planning entry below. The typed async result slot that would
make a float or string async return CORRECT (not merely refused) is a separate
defect: `bugs/CODEGEN_async_result_slot_is_int64_only.md`.

## Status (2026-10-29, planning round — `gen` and `t3` are both frame-introspection features; pinned, not fixed)

Measured on this branch, by compiling the real file through
`gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)`
(8 GB memslot). The file's only remaining refusal set is:

- `gen`: `a call to unresolved callee 'nested(...)'` — `yield nested()`
  where `nested` is a sibling nested def returning
  `sys._getframe().f_generator`.
- `t3`: `every return must carry a scalar value ... agree on one
  consistent type` — `async def t3()` returning `sys._getframe().f_generator`.

Facts that decide the plan:

- The compiler has NO representation for `sys._getframe()` or frame
  objects. `grep -rn _getframe` hits only tests and the regression file;
  there is no shim, no runtime symbol, no lowering. So `f_generator`
  has no type the return-type inference can unify, and `nested()` has no
  value to hold.
- `gen` minimal repro (the callable-value gap, independent of frames):
  ```
  def t0():
      def nested():
          return 1
      def gen():
          yield nested()
      g = gen()
      return next(g)
  ```
  still refuses with `unresolved callee 'nested(...)'`. This shape is
  cluster A (a sibling nested def called from a generator body, which
  the emitter treats as an unresolved callee). It IS narrow enough to be
  its own partial fix, but it is shared with `glob`/`os`/`pickletools`
  and not with frames; the frame part of `gen` still needs the frame
  model. Recommended as the NEXT step.
- `t3` minimal repro: a class-method-nested `async def` returning a
  `sys._getframe()`-derived value refuses; the same `async def` at
  module or plain-function level (with an identical body) does NOT
  refuse (checked: `nocls_selfless_use`, `nocls_no_getframe_nonscalar`
  in `.tmp/bisect3.py`). That is an inconsistency between the two
  emission paths for one async shape, not just a missing feature: either
  the module-level compile is silently emitting an unchecked return, or
  the class-method refusal is over-broad. NOT yet verified which; the
  module-level one is not confirmed to be correct at run time.

Decision needed (for the next round, not made here):

1. `t3`/`gen` frame model. Options: (a) keep `sys._getframe()` refused
   and accept that `test_f_generator` stays red for good (honest, no work);
   (b) model `f_generator` as a typed `object`-like value with a null/self
   pointer and lower the `is None` / `assertIs(g, ...)` checks (a real
   feature project: a frame shim plus generator self-identity). Recommend
   (a) for this file; it is one frame test in CPython's suite.
2. `t3` inconsistency: run the module-level `nocls_selfless_use` shape
   and check its generated C. If it returns a garbage/unchecked value,
   the fix is to make the async return check fire in that path too (the
   refusal is the honest answer). If the module-level path is correct,
   the class-method refusal is over-broad and the fix is in
   `mojo/backend_gimple/cpp_async.py` where `value_ctype` is decided.

Implementation plan (exact files, for the next round):

- `mojo/backend_gimple/cpp_async.py` ~1860-1921: the `value_ctype is None`
  branch is where a non-scalar async return is refused. The class-method
  vs module difference must be traced there (which `gen` state —
  `_cpp_func_scope_decls`, `_cpp_list_local_elem_types` — differs).
- For `gen`: the callable-value / sibling-nested-def resolution lives in
  the generator-body call lowering in `mojo/backend_gimple/cpp_core.py`
  (`unresolved callee` message). Cluster A's fix, if pursued, belongs
  there and is shared with `glob`/`os`/`pickletools`.

Tests (already landed on this branch):

- `test_regress_codegen_generator_frame.py`: the two `pass` placeholders
  are replaced with real pins. `test_regression_gen_nested_def_yield`
  asserts the `unresolved callee 'nested(...)'` refusal;
  `test_regression_t3_async_non_scalar_return` asserts the class-method
  scalar-return refusal. Both FAIL the moment the shape compiles, which
  is the signal to drop the pin and this doc entry together. They are
  pins, not fixes: neither one turns red->green in this round.

Still open: `gen` (frame part only; sibling-helper part landed — see the 2026-10-29 partial-fix entry above), `t3`. `g` is fixed (see below).

## Status (2026-10-29 — partial fix: integer division by zero now raises; `g` lowers)

Landed (root cause of `g`): integer `/`, `%` and `//` by a zero divisor
silently produced 0 on the compiled path (arm64 SDIV). Every integer division
now routes its divisor through `mojo_int_divisor` (runtime/fire_runtime.h),
which raises a catchable `ZeroDivisionError`:

- plain GIMPLE: the arithmetic tail in `mojo/backend_gimple/emit_exprs.py`
  guards integer `/` and `%`; `//` goes through `__mojo_floordiv`, which now
  checks too. The dead `_HELPERS` copy of `__mojo_floordiv` in
  `gimple_codegen.py` is removed.
- coroutine C++: `mojo/backend_gimple/cpp_core.py` guards integer `/` and `%`
  (a float divisor is never wrapped), and a bare expression statement in a
  generator body lowers to `(void)(expr);` instead of being refused. The
  divisor check is what keeps `1/0` out of C++'s constant-expression error.
- the boxed `/ // %` helpers now raise `ZeroDivisionError` (they raised
  `TypeError: division by zero`).

Pinned by `test_codegen_int_div_zero.py` (plain `//`/`/`/`%`, nonzero
unchanged, and the generator `1/0` shape). `test_gimple.py`: 402 pass, the
same 2 pre-existing failures as untouched HEAD. The file itself was NOT
re-run end to end (heavy); the gate integrator should.

NOT done — this file still cannot compile as a whole:

- `gen`: `yield nested()` where `nested` is `sys._getframe().f_generator`
  (callable-value / frame introspection; the cluster-A blocker above).
- `t3`: async `return` of a non-scalar (`frame.f_generator`), cross-path
  return-type unification.

Separate defect found on the way, since fixed: integer `%` truncated toward zero
(`-7 % 2` gave `-1`; Python gives `1`). Pinned by `test_codegen_int_div_zero.py`.

## Status (2026-09-07 — "cluster A" premise re-examined; `gen` is not a callable-value gap)

Investigated in a batch aimed at wiring `mojo_maybe_bound_call_N` into the
generator-body path. `gen` does NOT fit that model: `yield nested()` is a
*direct call to a sibling nested def*, not a call through a callable held
in a variable. And `nested()` itself is `sys._getframe().f_generator` —
pure CPython frame introspection with no compiled representation, so even
full nested-def-in-generator-body compilation would not make it lower.
`g` (`1/0` bare stmt → needs a runtime int-divide-by-zero trap) and `t3`
(async `return` of a non-scalar) are unrelated and unchanged. No code
change; none of the three is an incremental dispatch-wiring fix.

## Status (2026-09-05 — A3 stack-switch cutover: still REFUSED, clusters A + E)

Small test file. Still refused:

- `g`: `unsupported expression statement in generator body (BinaryOp)` —
  a bare `1/0` expression statement (deliberate ZeroDivisionError) as a
  generator-body statement.
- `gen`: `a call to unresolved callee 'nested(...)'` — **cluster A**
  (callable-value local; `nested` is a sibling nested def), shared with
  `glob`/`os`/`pickletools`.
- `t3`: `async` function whose `return` carries a non-scalar value.

All three are narrow shapes distilled from CPython's own frame/generator
regression tests; none has a shared high-impact fix beyond cluster A.

## Status (updated 2026-08-26 -- re-verified at current master `e60b9cd`, unchanged)

Independent fresh re-verify, this session, against current master
`e60b9cd` (122 commits past the `a913ab8` branch point the entry
immediately below was checked against). Ran
`compile_to_gimple_with_cpp(do_imports=False)` directly: byte-for-byte
identical 3-part `RuntimeError` — `g` (`unsupported expression
statement in generator body (BinaryOp)`, the `1/0` shape), `gen`
(`a call to unresolved callee 'nested(...)' is not supported...`), and
`t3` (`every return must carry a scalar value ... and all of them must
agree on one consistent type`). All three are independently
feature-sized (runtime int-div-by-zero trapping, nested-function-value
calls, cross-path return-type unification); none touched by anything
in the 122 intervening commits. Untouched.

## Status (updated 2026-08-26 -- re-verified, unchanged; full refusal set recorded for completeness)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`do_imports=False`) surfaces the FULL refusal set in
one message (not just `g`, which the last few status entries quoted in
isolation): `g` (BinaryOp `1/0` bare-statement, no runtime int-div-by-
zero trapping — the tracked blocker), plus `gen` (`yield nested()`,
where `nested` is a function nested inside `t0`'s own body — an
unresolved-callee/nested-function-value gap, same "opaque callable
value" family as `glob.py`'s blocker, not previously called out by name
in this doc but consistent with the "same whole-module fallback naming
`g`... and `t3`" note already on file since 2026-08-09), and `t3`
(`async def t3(): ... return frame.f_generator` — cross-return-type
unification, `frame.f_generator`'s inferred type disagreeing with the
promise's unified scalar type). None of these three are new discoveries
— they were already implicitly present in every prior pass's "whole-
module fallback" escalation, just not enumerated together before. All
three are independently feature-sized (runtime division trapping,
nested-function-value calls, cross-path return-type unification) and
none is touched by anything landed since 2026-08-25. Classification and
recommendation (real int-div-by-zero trapping is a legitimate standalone
feature project, not scoped to this file) unchanged. Untouched.

## Status (updated 2026-08-25 -- re-verified, unchanged)

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
test/test_frame.py` fresh against current master (past the struct-method
cross-call scalar contract "Pass 1.3e", generator-consumption-ordering
fixed-point retry + defaults-aware arg padding, `**kwargs`-forward
slot-alignment fix, coroutine-body `int()`/`float()` builtin support,
and this session's own `cls.<attr>`/`ClassName.<attr>` write fix — none
touch runtime integer division-by-zero). Per-function debug log shows
the identical refusal byte-for-byte at both retry passes: `generator
'g' not eligible for C++ coroutine path ...: unsupported expression
statement in generator body (BinaryOp)`, from the same `1/0` bare
statement inside `try: 1/0 except ZeroDivisionError`. Confirmed still a
genuine, standalone feature gap (no runtime int-div-by-zero trapping
anywhere in the compiled path, plain-GIMPLE or coroutine); not
attempted. Untouched.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. The blocker (no runtime integer division-by-zero trapping anywhere in the compiled path, plain-GIMPLE or coroutine) is unrelated to and unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still a standalone correctness-feature project; untouched.


## Status (updated 2026-08-23 — STILL-OPEN)

Unchanged from the 2026-08-18 investigation: the compiled path has NO
runtime integer division-by-zero trapping anywhere (plain GIMPLE and
coroutine paths alike), so `try: 1/0 except ZeroDivisionError` cannot
work; on arm64 SDIV-by-zero silently yields 0. A legitimate standalone
feature project per the recommendation below; nothing attempted.
(Adjacent enablers that DID land elsewhere this session — scalar-local
attribute stubs, zero-iteration stubbed-iterable loops — do not affect
this file's constant-folded `1/0` shape.) Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (investigated further 2026-08-18, still structural — not attempted)

Investigated whether the ORDINARY (non-generator, plain-GIMPLE) compiled
path already has real runtime integer-division-by-zero -> `ZeroDivisionError`
trapping that could just be ported/mirrored into the coroutine `.cpp`
emitter, per the task hypothesis. **It does not.** Confirmed empirically,
not just by absence of a grep hit:

- `grep -n "ZeroDivisionError" gimple_codegen.py` has exactly one hit —
  the exception-name string table (gimple_codegen.py:4695) used for
  matching `except ZeroDivisionError:` clauses against an exception's
  *type name* when one is already in flight. There is no call site that
  *raises* it.
- `runtime/mojo_runtime.h`'s `ZeroDivisionError` (line 603) is just an
  integer sentinel `#define` (1016) in the bootstrap exception-type table
  — never referenced by any division lowering.
- Integer division lowering (`__mojo_floordiv` in both
  `runtime/mojo_runtime.h:581` and its `__GIMPLE`-body mirror at
  gimple_codegen.py:3663, plus the plain `/`-operator path around
  gimple_codegen.py:10714-10739) does a bare C `a / b` / `a % b` with
  **no zero-divisor check anywhere**, in either the plain-GIMPLE or
  coroutine path.
- Built and ran a real, non-generator repro
  (`try: z = x // y except ZeroDivisionError: print("caught")` with `y`
  a genuine runtime-computed `0`, not a literal) via
  `python3 fire.py build` + running the binary: **no exception fires**.
  Output was `no exception 0` — division by zero silently produced `0`
  (this machine is Apple Silicon/arm64, where integer `SDIV` by zero
  returns 0 rather than trapping with SIGFPE, unlike x86). The identical
  source run via `python3 fire.py run` (the tree-walking interpreter,
  which lowers `//` straight to Python's own `//` operator) DOES print
  `caught`, confirming the interpreter path is fine and this really is a
  compiled-path-only gap, and a gap in the *plain* GIMPLE path, not
  something specific to coroutines.
- Confirmed the coroutine "sink" side (an exception raised via an
  explicit `raise` statement propagating out to a same-generator
  `try`/`except`) does have real machinery: `_cpp_raise_stmt` and
  `_cpp_try_stmt` both exist and are used elsewhere in this file's own
  generator/async support. So the exception-*catching* plumbing is not
  in question — only the *source* (turning a runtime `a/b` or `a//b`
  with `b == 0` into a raise at all) is entirely absent, and it's absent
  from BOTH the coroutine emitter and the ordinary plain-GIMPLE emitter,
  not just the coroutine one.

This changes the shape of the task from "port an existing, narrow,
already-proven runtime check into the coroutine emitter" (low risk) into
"invent real runtime integer-division-by-zero trapping for this
compiler's entire compiled arithmetic lowering from scratch" (touches
`_lower_BinaryOp`'s `/`/`//`/`%` cases, `__mojo_floordiv` in two places,
and the coroutine `.cpp` expression emitter's own division lowering —
shared machinery exercised by effectively every integer-arithmetic
expression this compiler ever compiles, in both the stdlib and any user
program). That is exactly the class of change CLAUDE.md's quality-gate
section warns needs `make check-selfhost` + a from-scratch stdlib dylib
rebuild treated as load-bearing, not optional — and per this task's own
stated stop condition ("if this genuinely requires inventing new
exception-raising machinery... STOP, revert, and document"), that is
what step 1/2's investigation found. **No code changes made; nothing to
revert.** The narrow, low-risk part of the original 2026-08-07 note
(widening `_cpp_stmt`'s `ExprStmt` case to accept a bare non-`CallExpr`
expression statement generically) was intentionally NOT done either,
since doing it in isolation here would have no observable effect (this
file's own repro still hits the compile-time-constant-fold wall the
2026-08-07 note already documented) and mixing it into this investigation
would blur which change caused what if something regressed — left for
whoever next hits a genuinely different bare-expression-statement shape,
as the 2026-08-07 note already flagged.

Recommendation for whoever picks this up next: real integer
division-by-zero trapping is a legitimate, self-contained feature
project (add a `divisor == 0` runtime check + `mojo_raise(...,
ZeroDivisionError, ...)` call to `__mojo_floordiv` and the plain `/`/`%`
lowering, verify it doesn't regress `make check-selfhost` or the stdlib
dylib skip/fail count, THEN mirror the same check into the coroutine
emitter) — but it is that project, not a fix scoped to this one file or
to generators, and shouldn't be done as a side effect of unblocking a
single test file's build.

## Status (re-verified 2026-08-09)

Re-verified against current master (fast-forwarded to `e5daa1d`) via a
real `MOJO_DEBUG=1 python3 fire.py build` run — reproduces byte-for-byte
identically to 2026-08-07: `generator 'g' not eligible for C++ coroutine
path ...: unsupported expression statement in generator body (BinaryOp)`,
same whole-module fallback naming `g` (generator) and `t3` (async).
Still a genuine feature gap (bare-statement `1/0` needs real runtime
int-division-by-zero -> Mojo-exception trapping in the compiled
coroutine path, which doesn't exist), not a narrow fix — confirmed
unchanged, no action taken.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild — reproduces
identically (same "unsupported expression statement in generator body
(BinaryOp)" refusal). Considered whether widening `_cpp_stmt`'s
`ExprStmt` case (gimple_codegen.py:22976-22980, currently only accepts
a bare `CallExpr` as a statement) to accept ANY expression generically
(`return [f"{indent}{self._cpp_expr(s.value)};"]` unconditionally,
mirroring Python's own "evaluate for side effects, discard the value"
`ExprStmt` semantics) would fix this — concluded it would NOT actually
help THIS file even though it's a plausible general improvement:
`1/0` is two INTEGER LITERAL CONSTANTS, so `_cpp_expr`'s lowering would
produce a literal C++ `(1 / 0)` — a compile-TIME constant-expression
division by zero, which g++ rejects as a hard error on its own,
regardless of whether the surrounding statement-shape refusal is lifted.
The real intent (`try: 1/0 except ZeroDivisionError as e: ...`) needs
actual runtime int-division-by-zero → Mojo-exception trapping in the
compiled coroutine path, which doesn't exist — a real feature gap, not
a narrow statement-shape fix. Not attempted here for that reason,
distinct from (though adjacent to) the general widening idea, which may
still be worth doing on its own merits for OTHER bare-expression-
statement shapes that don't hit this specific landmine — flagged for
whoever next hits a DIFFERENT bare non-call expression statement to
consider it then, with a repro that isn't a compile-time constant trap.

## Status (updated 2026-08-06, superseded above — re-verified, unchanged, investigated further)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`), now precisely classified (this file defines several
different nested `def g():` generators across different test methods;
the specific one currently refused is a different one than 2026-07-30's
note implies, since the message is more specific now).

```
[gimple_codegen] generator 'g' not eligible for C++ coroutine path, falling back to honest refusal: unsupported expression statement in generator body (BinaryOp)
```

**Root cause (new gap — narrow, single instance, not yet a hard-bug
doc):**
```python
def g():
    nonlocal endly
    try:
        1/0                     # <-- bare BinaryOp expression statement
    except ZeroDivisionError as e:
        f = e.__traceback__.tb_frame
        ...
```
`1/0` used as a bare STATEMENT (not assigned, not part of a larger
expression — deliberately, to trigger `ZeroDivisionError` via its side
effect) is a `BinaryOp` in expression-statement position. The coroutine
codegen's statement lowering (`_cpp_stmt`) has no case for a bare
`BinaryOp` expression statement inside a generator body at all —
refused wholesale, distinct from every other gap found in this cluster.

Also present (transitively, via `test.support`, not this file's own
code): the `start_threads` print()-scalar-argument gap already noted in
`“CODEGEN_generator_function: Lib/test/test_faulthandler.py”`.

Single instance of the new BinaryOp-statement gap so far; not folded
into a hard-bug doc. If confirmed recurring, write
`CODEGEN_generator_bare_expr_statement_unsupported`.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_frame.py
