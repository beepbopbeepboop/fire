# CODEGEN_generator_function: Lib/tokenize.py

## Status (updated 2026-08-06)

**STILL FAILING**, but the failure has moved well before the generator
codegen stage. Re-diagnosed against current master (`2b0c4c5`); the
2026-07-30 `'detect_encoding' was not declared` .cpp error no longer
reproduces, and — notably — `MOJO_DEBUG=1` when `tokenize.py` is built as
the TOP-LEVEL file shows NO "not eligible" refusal for `tokenize()`
itself at all (contrast with `bugs/CODEGEN_generator_function_Lib_enum.md`'s
re-diagnosis, which — reaching `tokenize.py` only as a TRANSITIVE import
— did see `tokenize`'s own `yield from
_generate_tokens_from_c_tokenizer(...)` refused for delegating to a
non-Python/C-extension generator target; that refusal apparently isn't
even reached when building this file directly, because the build aborts
earlier).

Current failure is two ordinary top-level name collisions with this
codegen's builtin/libc name handling, reached BEFORE the generator
eligibility pass runs at all:

```
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:63:8: error: conflicting types for 'any'; have 'char *(MojoList *)'
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:2275:31: error: conflicting types for 'perror'; have 'int64_t()' {aka 'long long int()'}
/Users/mrs/net/Python-3.14.6/Lib/tokenize.py:124:9: error: invalid use of void expression
```
`tokenize.py` defines its own top-level `def any(*choices): return
group(*choices) + '*'` (line 61) and (unconfirmed line, not located in
this pass) a `perror`-named symbol — both collide with this codegen's
own builtin-name (`any()`) / libc (`perror`) handling, an ordinary
free-function-naming gap unrelated to generators.

**Classification: NOT actually diagnosable as a generator-codegen-
cluster issue from the current build output** — the file never reaches
far enough into compilation for `tokenize()`'s own generator eligibility
to be evaluated when built as the top-level target. Given the OTHER
(enum.py-transitive) run DID see `tokenize()` refused for the C-extension
`yield from` delegation target, that refusal — cross-referenced in
`bugs/CODEGEN_generator_function_Lib_enum.md` and
`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md` —
is presumably still real and would resurface once the `any`/`perror`
name-collision blockers are fixed. Not investigated further here (name-
collision fix is out of scope for this generator-codegen cluster).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tokenize.py
