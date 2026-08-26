# CODEGEN_generator_function: Lib/test/test_frame.py

## Status (updated 2026-08-25 -- re-verified, unchanged)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
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
  `python3 mojo.py build` + running the binary: **no exception fires**.
  Output was `no exception 0` — division by zero silently produced `0`
  (this machine is Apple Silicon/arm64, where integer `SDIV` by zero
  returns 0 rather than trapping with SIGFPE, unlike x86). The identical
  source run via `python3 mojo.py run` (the tree-walking interpreter,
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
real `MOJO_DEBUG=1 python3 mojo.py build` run — reproduces byte-for-byte
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
`bugs/CODEGEN_generator_function_Lib_test_test_faulthandler.md`.

Single instance of the new BinaryOp-statement gap so far; not folded
into a hard-bug doc. If confirmed recurring, write
`bugs/hard/CODEGEN_generator_bare_expr_statement_unsupported.md`.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_frame.py
