# COMPILE_FAIL: Lib/rlcompleter.py — 'struct _root_toplev' has no member named 'readline'

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
'struct _root_toplev' has no member named 'readline'
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_x_has_no_member_named_x.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/rlcompleter.py`
