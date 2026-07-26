# COMPILE_FAIL: Lib/test/test_ctypes/test_keeprefs.py — implicit declaration of function 'pointer'; did you mean 'Pointer'? [-Wimplicit-function-declaration]

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
implicit declaration of function 'pointer'; did you mean 'Pointer'? [-Wimplicit-function-declaration]
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_implicit_declaration_of_function_x_wimplicit_functi.md`

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_keeprefs.py`
