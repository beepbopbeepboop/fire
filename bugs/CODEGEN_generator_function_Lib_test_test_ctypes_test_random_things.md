# CODEGEN_generator_function: Lib/test/test_ctypes/test_random_things.py

## Status (updated 2026-08-23 — PARTIAL)

The documented `cm.unraisable.*` int64_t-member errors are GONE:
attribute reads/calls rooted at opaque-scalar locals now stub to 0
(diagnosed) instead of emitting invalid C++, so `with ...
catch_unraisable_exception() as cm:` bodies compile through. The build
now fails one level deeper, on a NEWLY-diagnosed residual: inherited
unittest.TestCase method calls from generator bodies
(`self.assertIsInstance(...)`) get extern declarations whose parameter
list defaults to `(self)`-only when no param info exists in this module,
so the 3-arg call site fails 'too many arguments'. Same residual blocks
_test_eintr's assertEqual sites. Not attempted here (needs arity-aware
_cpp_struct_method_refs or inherited-method resolution). The #147-shaped
classification below otherwise stands. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (re-verified 2026-08-11, unchanged — deeper investigation confirms genuinely structural, not attempted)

Re-ran a fresh isolated build; reproduces identically to the 2026-08-09
note below (same 4 `cm.unraisable.*`/`int64_t` errors). Went one level
deeper than the prior notes to confirm this is really #147-shaped and
not narrowly fixable, by reading the real source
(`Lib/test/support/__init__.py`'s `catch_unraisable_exception`):

```python
class catch_unraisable_exception:
    def __init__(self): self.unraisable = None; self._old_hook = None
    def _hook(self, unraisable): self.unraisable = unraisable
    def __enter__(self):
        self._old_hook = sys.unraisablehook
        sys.unraisablehook = self._hook
        return self
```

Even a maximally narrow, single-shape fix (special-casing exactly
`with support.catch_unraisable_exception() as cm:` to type `cm` as
`catch_unraisable_exception *` from its `__enter__`'s `return self`)
would only get one level deeper before hitting the SAME wall twice
more: (1) `cm.unraisable` is itself a field set from `sys.
unraisablehook`'s callback argument — a real CPython `UnraisableHookArgs`
object this compiled runtime has no representation for at all (`sys.
unraisablehook` itself isn't implemented here), so the field's type is
unknowable even in principle, not just untracked; and (2) `cm.
unraisable.exc_value` is a THREE-level `self`-rooted chain (`_cpp_expr`'s
`MemberExpr` case only supports a `self.field` one-level read and a
`self.field1.field2` two-level chain, both rooted at `self` — never a
chain rooted at an arbitrary non-`self` local/with-binding at any
depth). Confirms the existing classification: a `with X() as y:`
binding's real type has no representation anywhere in this narrow
scalar-body codegen model (the same "no class-attribute/field-access
story for non-`self` objects inside a generator body" gap #147 already
tracks architecturally), and here it's compounded by a genuinely
un-typeable field (sourced from an unimplemented CPython runtime hook)
one level down. Not attempted, per this task's own guidance to leave
#147-shaped gaps alone and per this session's direct confirmation that
a narrow fix wouldn't reach past the first level anyway.

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
