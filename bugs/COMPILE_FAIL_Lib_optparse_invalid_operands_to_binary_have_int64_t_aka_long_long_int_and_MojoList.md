# COMPILE_FAIL: Lib/optparse.py — invalid operands to binary % (have 'int64_t' {aka 'long long int'} and 'MojoList *')

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
invalid operands to binary % (have 'int64_t' {aka 'long long int'} and 'MojoList *')
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_invalid_operands_to_binary_have_x_and_x.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/optparse.py`
