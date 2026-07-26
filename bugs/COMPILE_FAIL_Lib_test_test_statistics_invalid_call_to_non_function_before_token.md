# COMPILE_FAIL: Lib/test/test_statistics.py — invalid call to non-function before ';' token

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
invalid call to non-function before ';' token
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_invalid_call_to_non_function_before_x_token.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_statistics.py`
