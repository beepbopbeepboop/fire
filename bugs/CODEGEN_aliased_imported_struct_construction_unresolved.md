# OPEN: `from mod import Class as Alias; Alias(...)` does not construct the class

**State: OPEN, found 2026-09-27** while fixing
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`'s §4
blocker (qualified `module.Class(...)` construction, now fixed). This is a
narrower, separate residue in the same neighborhood.

## Repro

    # mod_a.py
    class Dialog:
        def __init__(self, widgetName):
            self.widgetName = widgetName
    # main.py
    from mod_a import Dialog as ADialog
    def main():
        x = ADialog("a")
        print(x.widgetName)
    main()

CPython: `a`. Compiled (`do_imports=True`, builds clean, exit 1 at
runtime): `Unhandled exception: AttributeError: widgetName`.

## Root cause

`ADialog("a")` is an ordinary bare-name `CallExpr` (`IdentExpr` func), so it
reaches the "Struct constructors" dispatch in
`mojo/backend_gimple/emit_calls.py` (`_fname_ctor = gen._c_kw_struct_renames
.get(fname_raw, fname_raw); if _fname_ctor in gen.struct_field_types:`).
`gen.struct_field_types` is keyed by the struct's OWN bare name as written
in its defining module (`"Dialog"`), never by an import alias — so
`"ADialog" in gen.struct_field_types` is `False` and the dispatch falls
through. It lands in the generic single-string-argument "opaque
constructor" fallback (the same one `pathlib.Path`-like wrappers use),
which just returns the argument unchanged: `x` becomes the literal string
`"a"`, and `x.widgetName` then dispatches `_mojo_dispatch_getattr` on a
`char *` — an honest but wrong `AttributeError`.

Unlike function imports, a module-scope `from X import Name as Alias` for a
CLASS is never registered into `gen.imported_symbols` at all in the
`do_imports=True` top-level import-processing pass (verified:
`'ADialog' not in gen.imported_symbols` after a full compile) — that pass's
registration is gated on the export having a `'signature'`, which a class
never has. A FUNCTION alias inside a function body IS recorded (with
`'original_name'`, `mojo/backend_gimple/emit_funcs.py`'s
`_gen_stmt_FromImportStmt`), but nothing downstream ever consults it for
constructor resolution either — the same gap would show up for a
function-scoped class alias too, untested.

## Shape of the fix (not attempted)

Two pieces, either sufficient alone but both worth doing:

1. Record class import aliases somewhere resolvable at the ctor dispatch —
   e.g. a `gen._class_import_aliases: dict[str, str]` (alias -> real bare
   name), populated wherever a `from X import Name as Alias` is processed
   (module-scope top-level pass and/or `_gen_stmt_FromImportStmt`'s
   function-scoped branch), keyed the same way `struct_field_types` is
   (bare names, first-writer-wins collision semantics already apply).
2. In the "Struct constructors" dispatch (`emit_calls.py`, the
   `_fname_ctor in gen.struct_field_types` check), fall back to that alias
   table when the literal name isn't found directly: `_fname_ctor =
   gen._class_import_aliases.get(fname_raw, fname_raw)` before the
   `struct_field_types` membership test.

Not attempted this session — scoped as its own item since the qualified
`module.Class(...)` fix already landed and verified in the same area, and
bundling this in would make either fix harder to verify in isolation.
