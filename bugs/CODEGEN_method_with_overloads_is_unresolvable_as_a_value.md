# CODEGEN: a method with overloads is unresolvable as a value — the link fails on the bare symbol

**State: OPEN, unfixed.** Found 2026-10-19 while fixing the "bound method of an
untyped receiver" defect (fixed, doc removed with its fix). That fix made an
untyped receiver's method arm answer a bound method; this is the shape it
deliberately did *not* cover, because covering it needs the ≥2-overload
symbol-resolution question answered, not just a second call site.

## What I ran and what I saw

    class C:
        def m(self, x: int) -> int:
            return x
        def m(self, x: str) -> str:
            return x

    def main():
        c = C()
        f = c.m
        print(f(1))

    main()

CPython prints `1` and exits 0.

`python3 fire.py --jit` never reaches execution:

    Linking failed: Undefined symbols for architecture arm64:
      "_C_m", referenced from:
          __gimple_main in ovl.o
    ld: symbol(s) not found for architecture arm64

`python3 fire.py run` (interpreter) fails too, differently: the method value
lands as a `MojoOverloadSet` and calling it raises

    AttributeError: 'MojoOverloadSet' object has no attribute '_invoke'

Remove one overload and the same program works — a single-overload method
resolves to its one mangled symbol and `f(1)` runs.

## Why

Each overload gets its own mangled symbol (`C_m__0`, `C_m__1`, …). Taking the
method *as a value* needs one address to hand to `mojo_bound_method_new`, and
there is no correct single answer: CPython resolves the overload at call time
from the argument types. The lowering has to either (a) synthesize a
dispatcher that re-enters the overload resolution, or (b) raise a clear,
catchable error at the point the value is taken. What it must not do — and
what it currently does — is emit a bare `_C_m` reference that cannot link.

## Reproduce

Any file containing the program above:

    python3 fire.py --jit that-file.mojo

The link error is the whole bug.

## Not fixing here

- Overload *resolution by argument type* at runtime. That is a separate,
  larger feature; this doc only asks that taking the value not produce an
  unbuildable binary.
- The untyped-receiver bound-method arm added in the doc this one was found
  during: that path deliberately keeps the ≥2-overload fallback out, and the
  measured result of including it is exactly this link error.
