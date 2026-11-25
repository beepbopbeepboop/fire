# CODEGEN: an imported name can resolve to a same-named class in another module

Found 2026-11-24 while adding the closure loader (`ClosureLoader` in `funcs_shared.py`).

## Symptom

The compiler's own build (`tools/selfhost_ci.py`, the closure translation unit) failed with:

    gimple_codegen.py:6793: error: too many arguments to function
        'module_loader_ModuleLoader___init__'; expected 1, have 2

The code at that line was `ModuleLoader(gen)`, a call to a class imported from
`mojo.middle.funcs_shared` by name. The C function it resolved to belongs to a DIFFERENT class
named `ModuleLoader`, in `module_loader.py` (a class with a one-argument constructor).

## What is known

- The collision is by BARE class name. Two modules each defining a class with the same name compile
  correctly when they are used independently (measured: two `Node` classes, `a.make()` and
  `b.make()`, print `1` and `y`, matching Python).
- The failing case needs an IMPORT of the name into a module that also imports (or transitively
  reaches) the other class. The symbol chosen was the other module's.
- Workaround applied: the new class was renamed `ClosureLoader`. The rename hides the defect; it does
  not fix it. Any future pair of same-named classes reached this way will fail the same way.

## Next step

1. Minimize: two modules `m1.py` (defines `class K` with `__init__(self, a)`) and `m2.py` (defines
   `class K` with `__init__(self, a, b)`), `main.py` doing `from m2 import K` and calling `K(1, 2)`
   after also importing `m1`. Expect the call to bind to `m1`'s constructor.
2. Find where a call of an imported class name is mangled (`_struct_cname_of_name`, the imported
   struct home in `funcs_shared.py`, and `_resolve_struct_cname(gen, name, home)`): the home module
   should be taken from the FROM-IMPORT that brought the name in, not from the bare-name registry.
3. Regression: the minimized program as `test_import_class_name_collision.py`, in the check bucket.
