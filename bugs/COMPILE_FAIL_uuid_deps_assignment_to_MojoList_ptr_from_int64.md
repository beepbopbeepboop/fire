# COMPILE_FAIL: UUID dependencies — assignment to 'MojoList *' from 'int64_t'

## Status
**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

## First error
```
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:67:28: error: assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```

## Consolidated match
This error pattern is already tracked in:
`consolidated/COMPILE_FAIL_cc_error_assignment_to_x_from_x_makes_pointer_from_integer_w.md`

## Other errors in uuid.py compilation chain
- `io.py` — same assignment-to-pointer error
- `abc.py` — request for member in non-struct/union
- `operator.py` — redeclared symbol, implicit function decl, stray '@', etc.
- `warnings.py` — unknown type name 'partial', expected token before '*'
- `functools.py` — unknown type name 'partial', undeclared identifier

All are COMPILE_FAIL patterns already covered by existing consolidated reports.

Source file: `/Users/mrs/net/Python-3.14.6/Lib/uuid.py`
