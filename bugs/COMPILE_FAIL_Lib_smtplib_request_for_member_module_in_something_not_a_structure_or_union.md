# COMPILE_FAIL: Lib/smtplib.py — request for member '__module__' in something not a structure or union

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
request for member '__module__' in something not a structure or union
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/smtplib.py`
