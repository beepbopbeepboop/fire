# CODEGEN_generator_function: Lib/test/test_faulthandler.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`), now precisely classified.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
[gimple_codegen] generator method FaultHandlerTests.'check_stderr_none' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
```

**Classification: `bugs/hard/CODEGEN_generator_non_plain_assignment_
target_refused.md`** (4th confirmed occurrence, and the first involving
a MODULE attribute as the target rather than tuple/list-unpack):
```python
def check_stderr_none(self):
    stderr = sys.stderr
    try:
        sys.stderr = None            # <-- module-attribute assignment target
        with self.assertRaises(RuntimeError) as cm:
            yield
        ...
```
`sys.stderr = None` assigns to `sys.stderr` — a `MemberExpr` target
(module attribute), not a bare identifier — refused by the same
generic "only a plain identifier assignment target is supported" check
as the doc's other 3 occurrences (which were tuple/list-pattern
unpacking). Confirms the gap is broader than just unpack-shapes: ANY
non-`IdentExpr` assignment target inside a generator body is refused,
including plain attribute assignment.

Also transitively (via `test.support`, not this file's own code): a
NEW gap, `start_threads` refused with "`print()` argument must be a
scalar int64_t/double/_Bool/char* expression" — a `print()` call with a
non-scalar argument inside a generator body. Single instance, not yet a
hard-bug doc; plausibly related to the pkgutil.py callback-argument-
shape gap (`bugs/CODEGEN_generator_function_Lib_pkgutil.md`) as another
instance of "some call sites inside a generator body have a stricter
argument-shape requirement than the general parameter-type allow-list."

Not fixed here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
