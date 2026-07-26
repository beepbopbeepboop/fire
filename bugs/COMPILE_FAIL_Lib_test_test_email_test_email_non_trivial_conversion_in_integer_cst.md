# COMPILE_FAIL: Lib/test/test_email/test_email.py — non-trivial conversion in 'integer_cst'

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
non-trivial conversion in 'integer_cst'
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_non_trivial_conversion_in_x.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_email.py`
