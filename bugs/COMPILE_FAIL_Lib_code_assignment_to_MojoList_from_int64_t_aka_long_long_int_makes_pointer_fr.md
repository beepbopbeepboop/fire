# COMPILE_FAIL: Lib/code.py — assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_assignment_to_x_aka_x_from_x_makes_integer_from_poi.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/code.py`
