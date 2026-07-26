# COMPILE_FAIL: Lib/pickle.py — 'PYTHON2_EXCEPTIONS' undeclared (first use in this function)

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
'PYTHON2_EXCEPTIONS' undeclared (first use in this function)
```

## Consolidated match
No matching consolidated report found for this error pattern.

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pickle.py`
