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

## Minimized (2026-11-24)

    # m1.py
    class K:
        def __init__(self, a):
            self.a = a
    # m2.py
    class K:
        def __init__(self, a, b):
            self.a = a
            self.b = b
    # main.py
    import m1
    from m2 import K
    print(K(1, 2).b)
    print(m1.K(5).a)

Python prints `2` and `5`. The build fails:
`main.py:3:3: error: too many arguments to function 'm1_K___init__'; expected 2, have 3`.

## Mechanism (measured)

- `emit_resolve.py` (~2324, the extern-declaration path for an imported symbol) records a struct's
  home with `gen._imported_struct_home.setdefault(name, qualifier)`. The dict is per COMPILE, not per
  module, and `setdefault` is first-wins. `import m1` is compiled first, so `K` belongs to `m1` for
  every module in the compile, including `main`, which imported `m2`'s `K`.
- The bare constructor call then takes the cname of that home (`m1_K`). Qualified calls
  (`m2.K(...)`) use `_ctor_cname_via_module`, which takes the module from `imported_symbols`, so they
  are correct. The bare name is the defect.
- A quick attempt to pass the from-import's module as the home inside `_resolve_struct_cname` did
  not change this output: the bare call never reaches that resolver. The change was reverted (the
  tree is clean); it is not the fix.

## Fix direction

The function-level analogue already exists: `_own_imported_func_home` is a per-instance home, written
from THIS module's own FromImportStmt scan, and consulted before the shared fallback (see the
`_func_qualifier` tier comments in `emit_funcs.py`). Do the same for structs: a per-module
`_own_imported_struct_home` filled from the module's own `from m import K` statements, read by the
bare constructor path (the lowering that produces `{cname}___init__`), before the shared
`_imported_struct_home`. Regression: the minimized program above as `test_import_class_name_collision.py`.

## Attempt 2 (2026-11-24): a per-module struct home, reverted

Tried: a per-instance `_own_imported_struct_home`, filled by the extern-declaration path
(`emit_resolve.py` ~2321, next to the shared `setdefault`) and read first by
`funcs_shared._struct_method_qualifier`. Result on the minimized program: unchanged
(`too many arguments to function 'm1_K___init__'`). So the bare constructor's C name is NOT chosen by
`_struct_method_qualifier`; the call site builds it from another source. Reverted (tree clean).

Still open. Next: find the call-site lowering of a bare struct constructor (the `K(1, 2)` expression
in `main`): instrument the emitted callee name and the function that produces it, in a scratch copy,
then move that choice to the module's own import.
