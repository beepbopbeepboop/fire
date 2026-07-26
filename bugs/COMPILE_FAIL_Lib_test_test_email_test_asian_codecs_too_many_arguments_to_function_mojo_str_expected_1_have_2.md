# COMPILE_FAIL: Lib/test/test_email/test_asian_codecs.py — too many arguments to function 'mojo_str'; expected 1, have 2

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
too many arguments to function 'mojo_str'; expected 1, have 2
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_too_many_arguments_to_function_x_expected_n_have_n.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_asian_codecs.py`
