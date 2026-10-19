# CODEGEN: `self.cb = c.add` with `c` an UNTYPED parameter raises `AttributeError: add` when `cb` is called

**Area:** CODEGEN. Found 2026-10-07 while checking the neighbouring shapes of the
fixed "bound method in a module global" bug.

## Reproduction

    class C:
        def __init__(self):
            self.k = 9
        def add(self, a, b):
            return self.k + a + b

    class H:
        def __init__(self, c):          # c is not annotated
            self.cb = c.add
        def go(self):
            return self.cb(1, 2)

    m = C()
    print(H(m).go())

CPython prints `12`. The compiled program exits 1 with
`Unhandled exception: AttributeError: add`. With `def __init__(self, c: C)` the
same program prints `12`, so the typed-receiver store is right.

## Cause

`c` is an `int64_t` (erased) parameter, so `c.add` lowers to
`_mojo_dispatch_getattr(c, "add")`, the generated per-struct getattr, which
dispatches on FIELD names only. A method name is not a field, so it raises, and
the call through `self.cb` (a `mojo_fnptr_call_2` on the stored word) never
happens.

## Next step

Teach `_mojo_getattr_<Struct>` to answer a method name with a
`mojo_bound_method_new(<method pointer>, obj)` (the value `_lower_bound_method_value`
builds for a typed receiver), and make the call through an untyped slot
dispatch on `MojoBoundMethod` the way `_lower_maybe_bound_call` already does for
a tainted local.
