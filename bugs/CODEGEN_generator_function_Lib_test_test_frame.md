# CODEGEN_generator_function: Lib/test/test_frame.py

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
