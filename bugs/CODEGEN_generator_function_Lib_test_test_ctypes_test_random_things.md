# CODEGEN_generator_function: Lib/test/test_ctypes/test_random_things.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — same symptom as 2026-07-30, now precisely classified.

```
test_random_things_gen.cpp:117:31: error: request for member 'unraisable' in 'cm', which is of non-class type 'int64_t' {aka 'long long int'}
test_random_things_gen.cpp:117:27: error: expression cannot be used as a function
```

**Root cause:**
```python
def expect_unraisable(self, exc_type, exc_msg=None):
    with support.catch_unraisable_exception() as cm:
        yield
        self.assertIsInstance(cm.unraisable.exc_value, exc_type)   # line 117
        ...
```
`cm` is bound via `with support.catch_unraisable_exception() as cm:` —
an UNTYPED `with ... as` binding inside a generator body. **Classification:
a `with`-binding variant of `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1** ("untyped params inside a generator default to `int64_t`
instead of their real inferred type") — the same root mechanism (no
usage-based type inference for the coroutine codegen path, unlike the
ordinary closure path's `_gen_lifted_closure`/`ci.inferred_params`), just
triggered by a `with`-statement's bound name rather than a function
parameter. Every subsequent `cm.unraisable`/`cm.foo` member access then
fails since `cm`'s emitted C++ type is a raw `int64_t`, not the real
context-manager struct type.

Not fixed here — already-known gap family, no new fix attempted.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_random_things.py
