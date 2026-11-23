# CODEGEN: an imported bool module global prints `1`, not `True`

**Found while fixing** the per-file (`do_imports=False`) compile's export of an
unannotated module-level scalar global (`CONST = 41` imported by name read 0).
Unannotated scalar globals are now exported from `module_loader.py` with the
type the defining module's accessor returns, and `FLAG = True` is typed `int`
by that accessor (`module_gen._gscan_declare_global`'s BoolLiteral row). That
part is right: the C value IS 1 and a truthiness read is now correct instead
of the silent 0 it used to be. What is still wrong is the RENDERING.

## Symptom

    helper.py:  FLAG: bool = True        (or the unannotated `FLAG = True`)
    main.py:    from helper import FLAG
                print(FLAG)              # CPython: True, compiled: 1

Measured end to end on 2026-11-23: `helper.py` and `main.py` each compiled
through `build_stdlib_dylib.compile_module_to_c` (the per-file path), linked
with `runtime/fire_runtime.c`, run. `annotated_bool` printed `1`;
`annotated_int` (`CONST: int = 41`) printed `41`, so the accessor plumbing is
not the problem — the imported value is an `int`, and `print` of an `int`
renders `1`.

## Where

- `module_loader._ml_py_ann_ctype` maps `bool` to `int` (deliberately: that is
  the definer's accessor type), so the importer's extern is `int` and any
  bool-ness is lost at the C boundary.
- The fix belongs on the RENDERING side, not the export type: the importer
  must know the imported global is a BOOL so `print` renders `True`/`False`
  (`imported_global_accessors`' entry would need a semantic kind alongside
  `c_return_type`, consumed by `print`'s lowering the way a local
  `_Bool`/`int` bool temp already is — if it is; check
  `gimple_exprtypes`/the print path for an existing bool-rendering hook
  first, and reuse it rather than adding a second one).

## Acceptance

`print(FLAG)` of an imported `FLAG = True` (and the annotated `FLAG: bool =
True`) prints `True` in the compiled program, and `FLAG = False` prints
`False`, each compared with CPython by a linked-and-run test. The export's C
type stays `int`; only the printed form changes. A local bool already
printing correctly would be the control that shows this is the imported-global
path, not `print`.

## Done when

A test beside `test_codegen_imported_global_unannotated_scalar.py`'s
`test_bool_literal_export_is_int_typed_like_the_accessor` (which pins only the
C-level export today) links and runs the two-module bool fixture and requires
CPython's `True`/`False`. Delete this doc in that commit.
