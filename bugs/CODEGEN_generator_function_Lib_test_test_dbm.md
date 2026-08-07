# CODEGEN_generator_function: Lib/test/test_dbm.py

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
