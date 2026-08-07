# CODEGEN_generator_function: Lib/gettext.py

## Status (updated 2026-08-07)

Of the 4 errors listed below, the `gettext.py:445:1: error: invalid
conversion in gimple call` one is now FIXED — root cause was
`_gen_stmt_FromImportStmt`'s wrong `'int'` default for an unknown
function-scoped-imported symbol's return type (`from struct import
unpack` inside `GNUTranslations._parse`, line 353); see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` (Mechanism 1) for the full writeup. The other three
(`mojo_strlen` pointer/int conversion at line 208, `trunc_mod_expr` at
line 472 — the SAME dynamic-%-format-string gap documented as
deliberately out-of-scope in that doc's "Not fixed" section — and
`mojo_open_file` arg-count at line 554) are untouched, still open.

## Status (updated 2026-08-06, PARTIALLY STALE — see above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'_token_pattern' was not declared` .cpp error no longer
reproduces. `gettext.py` has one small generator (`_expand_lang`,
`yield value`/`yield ''`, lines 95-96) — it does not appear anywhere in
the current error list, and `MOJO_DEBUG=1` shows no "not eligible"
refusal naming it: gettext.py's own generator now appears to compile
cleanly through the coroutine path. (Note: this build is one of the
slowest in this cluster — ~44 minutes wall clock — consistent with the
already-documented, unrelated `bugs/hard/PERF_nested_module_compile_
walk_ast_quadratic_rescan.md` perf issue for a moderately large
transitive import graph.)

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are all unrelated to generators — dominant pattern is
`%`-formatting/modulo type errors and pointer/int conversion bugs in
gettext.py's own translation-catalog parsing code:
```
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:208:23: error: passing argument 1 of 'mojo_strlen' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:445:1: error: invalid conversion in gimple call
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:472:1: error: invalid types for 'trunc_mod_expr'
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:554:10: error: too many arguments to function 'mojo_open_file'; expected 1, have 2
```
Not investigated further — out of scope for this generator-codegen
cluster (the `mojo_open_file` 2-vs-1-arg error also appeared in
`turtle.py`'s current re-diagnosis — may be a recurring non-generator
gap worth its own report).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/gettext.py
