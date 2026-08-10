# CODEGEN_generator_function: Lib/gettext.py

## Status (updated 2026-08-09)

Re-verified against current master (post-merge `7df52a0`). Still fails,
still NOT a generator-codegen-cluster failure — `gettext.py`'s one
generator (`_expand_lang`, `yield value`/`yield ''`) again shows up ONLY
in the warnings section of the build log (`_expand_lang_584a43`), no
errors, no `MOJO_DEBUG=1` "not eligible" refusal. Confirms the
2026-08-07 reclassification still holds.

Current error list has shifted again (line numbers move release to
release as unrelated fixes land elsewhere in the stack):
```
gettext.py:208:23 error: passing argument 1 of 'mojo_strlen' makes pointer from integer without a cast
gettext.py:217:25 error: passing argument 1 of '_mojo_at_char' makes pointer from integer without a cast
gettext.py:472:1  error: invalid types for 'trunc_mod_expr'   (npgettext's `self.CONTEXT % (context, msgid1)`)
gettext.py:485:1  error: invalid types for 'trunc_mod_expr'   (npgettext's `self.CONTEXT % (context, msgid1)`, 2nd call site)
gettext.py:554:10 error: too many arguments to function 'mojo_open_file'; expected 1, have 2
gettext.py:114:10 error: too many arguments to function 'mojo_enumerate'; expected 1, have 2
gettext.py:843:46 error: stray '\' in program / missing terminating ' character / expected ';' ...
```
The 208/217 pair is one root cause, not two: `c2py()`'s `result, nexttok
= _parse(_tokenize(plural))` (line 203) then `for c in result:` (line
208) — `result`'s inferred type collapses to a scalar (`int64_t`-ish)
instead of the real string/sequence type `_parse` returns, so both the
`mojo_strlen` call (line 208's `for` iteration) and `_mojo_at_char`
(line 217's `elif c == ')'`-adjacent codegen) get fed an int where a
`char *` is expected — matches the previously-documented "untouched"
208 line, now confirmed to have a sibling symptom at 217 from the same
cause. 472/485 are the SAME dynamic-`%`-format-string gap already
called out as deliberately out-of-scope. 554 (`mojo_open_file` 1-vs-2
arg — `open(mofile, 'rb')`, the mode string isn't modeled) is confirmed
still real and, per the note below, IS the same recurring gap suspected
in `turtle.py`'s re-diagnosis: `gimple_codegen.py`'s `mojo_open_file`
runtime shim (declared at line ~32669: `int64_t mojo_open_file(char
*path);`) only ever takes a path, never a mode — a systemic modeling
gap (would need runtime.c changes + mode-string handling), not a narrow
one-line fix. NEW this pass: `mojo_enumerate` has the identical 1-vs-2-
arg gap for the `start` parameter (`enumerate(_binary_ops, 1)` at line
114, a plain dict-comprehension, not generator-related) — same shape of
bug, different builtin.

`gettext.py:843` is a confirmed **red herring**, same #line-stamping
artifact documented in `glob.py`'s doc: `gettext.py` is only 657 lines
long, so line 843 cannot be real source. Checking the cached `.ci`
confirms the last `#line` stamp for `gettext.py` is `#line 657
"...gettext.py"`, immediately followed by unstamped code from a
transitively-imported module (`textwrap.py`'s `TextWrapper` — the
`_classattr_TextWrapper__letter` identifier in the error is textwrap's,
not gettext's). Not gettext.py's bug at all; mis-attributed by GCC's
line counter continuing past the last stamp.

**Classification unchanged: NOT a generator-codegen-cluster failure.**
Remaining errors are a small cluster of distinct, non-narrow, non-
generator gaps (a `_parse()`-return-type inference bug, the known %-
format gap, and TWO builtins — `open()`/`enumerate()` — missing their
optional second argument in the runtime shim). None attempted here —
out of scope for this generator-codegen pass; `mojo_open_file`'s gap in
particular looks worth its own dedicated non-generator bug doc given it
now has 2 confirmed sightings (gettext.py, turtle.py).

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
