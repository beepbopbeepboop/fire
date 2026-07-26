# COMPILE_FAIL: Lib/posixpath.py — lvalue required as left operand of assignment

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
lvalue required as left operand of assignment
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_lvalue_required_as_left_operand_of_assignment.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/posixpath.py`
