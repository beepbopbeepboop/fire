# CODEGEN_generator_function: Lib/test/test_frame.py

## Status (updated 2026-08-06)

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
