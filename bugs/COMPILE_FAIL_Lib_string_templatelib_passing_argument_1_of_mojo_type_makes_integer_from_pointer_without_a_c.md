# COMPILE_FAIL: Lib/string/templatelib.py — passing argument 1 of 'mojo_type' makes integer from pointer without a cast [-Wint-conversion]

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
passing argument 1 of 'mojo_type' makes integer from pointer without a cast [-Wint-conversion]
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_passing_argument_n_of_x_makes_integer_from_pointer_.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/string/templatelib.py`
