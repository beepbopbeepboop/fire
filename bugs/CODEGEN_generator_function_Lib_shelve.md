# CODEGEN_generator_function: Lib/shelve.py

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; the 2026-08-09 "59 remaining toplev occurrences" claim was a grep-methodology false positive; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included. Re-checked the 2026-08-09
section's own claim below ("the struct _*_toplev pattern... is not
entirely eliminated (59 remaining toplev occurrences in this log)")
precisely: of the 60 lines matching the substring `toplev` in a fresh
rebuild's log, 59 are `gcc -fgimple`'s own "In function '_X_toplevel'"
context-line annotations (this codegen's real, unrelated per-module
`_toplevel()`/`_{module}_toplevel()` init-function NAME, which merely
CONTAINS the substring "toplev") plus one occurrence of `pickle.py`'s
own `_Pickler__save_toplevel_by_name` symbol — zero of the 60 are
actual `invalid use of undefined type 'struct _X_toplev'` errors. The
2026-08-09 claim conflated a substring-grep artifact with the real
error class; corrected here. The ONE genuine struct-`_toplev`-family
error that WAS present (a different symptom shape, `struct
'_root_toplev' has no member named '_lazy_annotationlib'`, from
transitively-imported `typing.py`) is a related-but-distinct bug this
session found+fixed: `_gen_struct_method`/`_gen_lifted_closure`
(gimple_codegen.py) never set `self._current_module_ctx`, misrouting a
`global`-statement write inside a class method (typing.py's
`_LazyAnnotationLib.__getattr__`, compiled first in its module) to the
wrong module's globals struct. Also fixed a related `_safe_coerce_
emit` gap (`.`-accessed struct-field LHS not recognized, only
`->`-accessed). Full writeup in `bugs/hard/COMPILE_FAIL_module_toplev_
struct_never_fully_defined.md`'s history and this session's commit.

Effect on this file: total build error count dropped 552 -> 540 (12
fewer — shelve.py's large transitive closure, via `dbm`, apparently
hits the `_current_module_ctx` bug at more than one site; not traced
further since none implicate shelve.py's own code or generator either
way). `Shelf.__iter__` remains unaffected (still compiles cleanly); the
`pickle.py`/`argparse.py`/`codecs.py`/`typing.py`/... cluster remains
this file's real blocker. No reclassification — shelve.py still does
not build.

## Status (updated 2026-08-09)

Re-re-verified against current master (real `mojo.py build` rebuild, real
`gcc-mp-15`/`g++-mp-15` per `build_config.py`). Classification unchanged:
**NOT a generator-codegen-cluster failure.** `Shelf.__iter__`
(`yield k.decode(self.keyencoding)`) still shows zero signal of any
problem — no "not eligible" refusal, no error attributed to
`shelve.py` itself (0 occurrences in the error list). Total build
errors continue to drop: 552 now (down from 1038 in the 2026-08-07
pass), still 100% in transitively-imported files, none in
`shelve.py`'s own source. Dominant clusters this pass: `Lib/pickle.py`
(350 errors — by far the largest single contributor now),
`Lib/argparse.py` (45), `Lib/codecs.py` (36), `Lib/typing.py` (20),
`Lib/inspect.py` (14), `Lib/enum.py` (12), plus smaller counts in
`posixpath.py`/`contextlib.py`/`os.py`/`functools.py`/`gettext.py`/
`weakref.py`/`tokenize.py`/`threading.py`. The `struct _*_toplev`
pattern previously reported as fully gone is not entirely eliminated
(59 remaining `toplev` occurrences in this log), but is a minor
contributor next to `pickle.py`. None of this implicates `shelve.py`'s
generator or its own code. Not investigated further — out of scope for
this generator-codegen cluster; not deleting the doc since the file's
full build (`mojo.py build`) still fails (`git rm` per this project's
process is reserved for files whose target source 100% compiles clean
end-to-end, not just "this file's own lines contribute 0 errors").

## Status (updated 2026-08-07, superseded above)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`Shelf.__iter__` still compiles cleanly (no "not eligible" refusal), and
`shelve.py`'s own source contributes ZERO errors to the build (down from
1189 to 1038 total errors, all still in OTHER transitively-imported
files). The `struct _locale_toplev`/`struct _threading_toplev`
"undefined module-namespace pseudo-struct" pattern noted below is GONE
(0 occurrences now — fixed by `bugs/hard/COMPILE_FAIL_module_toplev_
struct_never_fully_defined.md`'s "mechanism 2" landing since
2026-08-06/07, same fix already confirmed for glob.py/mailbox.py/
modulefinder.py in this session). Not investigated further — the
remaining 1038 errors are still entirely in shelve.py's transitive
dependency closure (dbm backends, etc.), out of scope for this cluster.

## Status (updated 2026-08-06, superseded above — struct_toplev errors since independently fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'keys'` .cpp error no longer reproduces.
`shelve.py` has one generator, `Shelf.__iter__` (`yield
k.decode(self.keyencoding)`, line 96) — it does NOT appear anywhere in
the current error list (1189 errors total, all in OTHER transitively-
imported files), and `MOJO_DEBUG=1` shows no "not eligible" refusal
naming it: `Shelf.__iter__` now appears to compile cleanly through the
coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
`shelve.py` transitively pulls in a very large dependency closure (via
`import dbm`, which tries multiple backend modules) and the current
build fails entirely on hundreds of errors in THOSE other files —
dominant patterns: `expected expression before 'int64_t'`/`'char'`/
`'int'` (108/87/66 occurrences), `invalid use of undefined type 'struct
_locale_toplev'`/`'struct _threading_toplev'` (the same recurring
"undefined module-namespace pseudo-struct" pattern seen in this
session's `glob.py`/`modulefinder.py`/`mailbox.py` re-diagnoses, here
for `locale`/`threading` instead of `subprocess`/`genericpath`), and
`expected declaration specifiers or '...' before 'Signature'`/
`'Parameter'`/`'partial'` (looks like the SAME malformed-declaration
pattern seen in `codecs.py`'s current re-diagnosis). None of these
implicate shelve.py's own code or its generator. Not investigated
further — entirely out of scope for this generator-codegen cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/shelve.py
