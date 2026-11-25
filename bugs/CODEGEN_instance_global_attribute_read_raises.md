# CODEGEN: `module.GLOBAL.field` raises AttributeError at run time

Found 2026-11-24 while testing the import-cycle and global-homonym work
(`test_global_homonym_struct.py`, first version).

## Symptom

A module-level instance global read through its module and then a field:

    # a.py
    class Box:
        def __init__(self, n):
            self.n = n
    BOX: Box = Box(1)

    # main.py
    import a
    print(a.BOX.n)

`python3 main.py` prints `1`. The compiled `prog` prints
`Unhandled exception: AttributeError: BOX` and exits 1.

## What works (measured)

- `import a; print(a.X)` with `X: int = 5` prints `5`. So the module attribute read itself is fine
  for a scalar global.
- The same program with the global read through a FUNCTION in its own module
  (`def box_n(): return BOX.n`, then `print(a.box_n())`) works. The test was rewritten that way.

## What is known

The failing shape is a module attribute whose value is a struct instance, followed by a field
read. The read goes through the module-attribute path, which looks the name up as a function or a
plain attribute of the module and does not find a struct-typed global. The exception text names
the global, so the lookup is by name at run time, not a missing C symbol.

## Next step

1. Find the code that lowers `MemberExpr(obj=IdentExpr(module alias), member=GLOBAL)` when the
   member is a global (`gen._lower_IdentExpr` / the module-attribute path in `emit_exprs.py`), and
   compare it with the bare-name global read path (`_global_var_types` / `_own_overlay_global_ctype`).
2. Check whether the generated C reads `_<mod>_globals.BOX` or calls an attribute lookup
   (`mojo_getattr`-style) with the string `"BOX"`: the traceback text suggests the latter.
3. Fix so a struct-typed module global reads its field the same way a bare global does.
   Regression: the minimal program above (`test_module_global_attr_read.py`, check bucket).
