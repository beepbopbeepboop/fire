# COMPILE_FAIL: Lib/filecmp.py — ld returned 1 exit status

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
ld returned 1 exit status
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/filecmp.py`
