# CODEGEN_generator_function: Lib/pickletools.py

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (`c79a013`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py`.
Identical refusal reproduces exactly:

```
[gimple_codegen] generator '_genops' not eligible for C++ coroutine
  path, falling back to honest refusal: unsupported expression in
  generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator
  function(s), contain a `yield`/`yield from`) — ...
```

Still exactly `_genops`'s `getpos = lambda: None` (pickletools.py:34
in this checkout — the `if hasattr(data, "tell"): ... else: getpos =
lambda: None` fallback). No new information; the 2026-08-07
classification below (`bugs/hard/CODEGEN_generator_lambda_expr_
unsupported.md`, feature-sized, needs a lifted-closure-style value
category for `LambdaExpr` in the coroutine body model) still stands.
Not re-attempted here.

## Status (updated 2026-08-07, classified — doc reference now exists)

**Classification: `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`**
— this file's `_genops`/`getpos = lambda: None` is that doc's own
first confirmed occurrence (written 2026-08-07). Investigated there and
assessed feature-sized (needs a new "callable-typed local variable"
value category in the coroutine body model — see that doc's "Why this
is feature-sized, not narrow" section); not re-attempted here, no new
information found that would change that assessment.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py
[gimple_codegen] generator '_genops' not eligible for C++ coroutine path, falling back to honest refusal: unsupported expression in generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `_genops`:
```python
def _genops(data, yield_end_pos=False):
    ...
    if hasattr(data, "tell"):
        getpos = data.tell
    else:
        getpos = lambda: None          # <-- the refused expression
    while True:
        pos = getpos()
        ...
        yield opcode, arg, pos
```
`getpos = lambda: None` assigns a `LambdaExpr` to a local inside the
generator's own body. The coroutine codegen's expression lowering
(`_cpp_expr`) has no case for `LambdaExpr` at all — every AST node shape
it doesn't recognize is refused via `_UnsupportedGeneratorShape` at that
statement, and (same escalation as the struct-typed-param and dynamic-
`raise` gaps found elsewhere in this cluster) refusing a MODULE-LEVEL
generator like this one hard-fails the entire file's `mojo.py build`.

**New, narrow gap — not yet folded into a hard-bug doc** (only one
instance seen in this cluster so far). A `lambda` literal used as a
plain callable value (assigned to a local, later called with `()`) is a
common enough Python idiom that this is likely to recur; if a second/
third instance turns up elsewhere in this cluster, fold into a new
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` — the likely
minimal fix shape (worth noting for whoever picks it up) mirrors how
this codegen already handles ordinary (non-generator) closures elsewhere
via `_gen_lifted_closure`: lower the lambda to a lifted, non-capturing-
or-capturing helper function the SAME way, then have `_cpp_expr`'s
`LambdaExpr` case just reference that lifted function's pointer, rather
than inventing new lambda-specific C++ codegen inside the coroutine path.

Not fixed here — narrow-looking but touches expression-lowering inside
the coroutine `.cpp` emission path, which this task's guidance flags as
warranting its own dedicated verification pass rather than a drive-by
change during cluster classification.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/pickletools.py
