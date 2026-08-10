# CODEGEN_generator_function: Lib/test/test_ctypes/test_random_things.py

## Status (re-verified 2026-08-09, unchanged)

Re-ran `python3 mojo.py build .../Lib/test/test_ctypes/test_random_things.py`
against current master (140 commits past the 2026-08-07 note below). Fails
identically:

```
test_random_things_gen.cpp:124:56: error: request for member 'unraisable'
in 'cm', which is of non-class type 'int64_t' {aka 'long long int'}
```

(4 occurrences, same `cm.unraisable.*` member accesses.) Same root cause as
before: `with support.catch_unraisable_exception() as cm:` inside a
generator body — an untyped `with ... as` binding defaults to `int64_t`
instead of its real context-manager struct type. Confirmed still the same
`with`-binding variant of the broad, deliberately-untouched #147
struct-typed-param-in-generator-body gap. No fix attempted, per this
cluster's guidance to leave #147-shaped gaps alone.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild — reproduces
identically (line numbers shifted by a few lines but the same shape,
same `cm.unraisable`/`int64_t` errors). Classification below unchanged
and still accurate. This is the same "no real class-attribute/field-
access story for non-`self` objects inside a generator body" limitation
already tracked as architecturally broad in `bugs/hard/CODEGEN_
generator_struct_typed_param_refused.md` (task #147) — a `with X() as
local:` binding is a second entry point into the identical gap
(alongside a plain parameter's own declared type). Not attempted here,
consistent with this task's guidance to leave #147-shaped gaps alone.

## Status (updated 2026-08-06, superseded above — re-verified, unchanged)

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
