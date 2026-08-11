# CODEGEN_generator_function: Lib/test/test_dbm.py

## Status (re-verified 2026-08-11, unchanged classification, error count down further)

Re-ran against current master (154 commits past the 2026-08-09 note
below, incl. this session's own generator-body struct-construction fix
— see `bugs/CODEGEN_generator_function_Lib_test_test_doctest_test_
doctest.md` — which doesn't touch anything reachable from this file).
Error count has dropped again, from 29 to **8**. `test_dbm.py`'s own
generator (`yield mod`, line 34) still contributes zero errors/warnings
of substance (only `-Wunused-*`). All 8 remaining errors are still in
transitively-imported dependency files (`Lib/test/support/__init__.py`
lines 488/1184/1186/1420/1905-1908, `import_helper.py` line 50) —
`assignment to 'int64_t *' from 'int64_t' makes pointer from integer`,
`implicit declaration of function 'print_warning'`/`'unlink'`, and one
`expected ')' before ';' token` parse error. **Classification unchanged:
NOT a generator-codegen-cluster failure.** Still out of scope for this
cluster; not investigated further.

## Status (re-verified 2026-08-09, unchanged classification, error count down further)

Re-ran `python3 mojo.py build .../Lib/test/test_dbm.py` against current
master (140 commits past the 2026-08-07 note below). Error count has
dropped again, from 31 to **29**. `test_dbm.py`'s own generator (`yield
mod`, line 34) still contributes zero errors and shows no "not eligible"
refusal — its own translation unit only produces `-Wunused-*` warnings.
All 29 remaining errors are still in transitively-imported dependency files
(`Lib/test/support/__init__.py`, `import_helper.py`, `os_helper.py`),
dominated by `assignment to 'int64_t' ... from 'char *' makes integer from
pointer without a cast` (the same untyped-var-defaults-to-int64_t family
noted elsewhere in this cluster, but on the ordinary/non-generator codegen
path here). **Classification unchanged: NOT a generator-codegen-cluster
failure.** Still out of scope for this cluster; not investigated further.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`test_dbm.py`'s own generator still shows zero signal of a problem, and
`test_dbm.py`'s own source still contributes ZERO errors (down to 31
total errors from 39, all still in transitively-imported dependency
files). Not investigated further — out of scope for this cluster.

## Status (updated 2026-08-06, superseded above — error count has since dropped, same classification)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'dbm' was not declared` .cpp error no longer reproduces.
`test_dbm.py`'s own generator (`yield mod`, line 34) does not appear
anywhere in the current 39-error output and has no "not eligible"
refusal — it appears to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure.** All 39
current errors are in transitively-imported dependency files, not
`test_dbm.py` itself — dominant pattern is `assignment to 'int64_t' from
'char *' makes integer from pointer without a cast` (20 occurrences) and
a couple of `'MojoBoundMethod' has no member named 'size'` (the same
property-access-leaves-a-bound-method family noted in `ipaddress.py`'s
current re-diagnosis). Not investigated further — out of scope for this
generator-codegen cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_dbm.py
