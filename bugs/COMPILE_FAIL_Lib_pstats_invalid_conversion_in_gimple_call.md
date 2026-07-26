# COMPILE_FAIL: Lib/pstats.py — invalid conversion in gimple call

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
invalid conversion in gimple call
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_invalid_conversion_in_gimple_call.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pstats.py`
