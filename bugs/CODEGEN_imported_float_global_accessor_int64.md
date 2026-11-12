# CODEGEN_imported_float_global_accessor_int64

## Summary

A `from m import F` of a module-scope `var F = 2.5` (a `double` global in a
`.mojo` sibling) does not compile. The defining module emits its accessor
`xmodattr_defn__mojo_global_get_F` returning `int64_t`, while the importing
module declares the same accessor `extern double` (from the export table's
`c_return_type`). gcc rejects the importer's translation unit with
"conflicting types".

## Repro (measured 2026-11-12, this tree)

`xmodattr_defn.mojo`:

    var F = 2.5

`xmodattr_use.mojo`:

    from xmodattr_defn import F

    def main():
        print(F)

    main()

Compiled with `compile_to_gimple(use, do_imports=True, filename=<entry>)` and
`gcc -fgimple`:

    error: conflicting types for 'xmodattr_defn__mojo_global_get_F';
           have 'int64_t(void)'
    note: previous declaration ... with type 'double(void)'

Expected: prints `2.5`. The same failure is reached from a class attribute
(`class C(): var fl = F`), so it is not specific to the class-attribute path.

## Where it is

- Importer side: `mojo/backend_gimple/emit_infra.py` `_emit_imported_global_accessors`
  declares the extern from the export table (`c_return_type` = `double`).
- Definer side: the generated `int64_t xmodattr_defn__mojo_global_get_F (void)
  { return _xmodattr_defn_globals.F; }` — its return type is decided
  somewhere other than the export table, and picks `int64_t` for a `double`
  global. Not yet traced to the line.

`from m import S` (`char *`) and `from m import N` (`int64_t`) are correct,
which is why this shows up only for float globals.

## Next step

1. Find the emitter for the `<mod>__mojo_global_get_<name>` definition
   (grep `_mojo_global_get_` in `mojo/backend_gimple/` and `module_gen.py`) and
   record why it returns `int64_t` for a `double` global. Expected: it should use
   the same `(name, c_type, g_mtype)` triple `_module_global_field_type` reads
   for the struct field.
2. Make the definer's return type and the export's `c_return_type` agree by
   construction (one source), then add a regression beside
   `test_module_class_attr_from_imported_global` in `test_gimple_runner.py`
   that prints the imported float.

## Done when

The repro above prints `2.5` and compiles with `gcc -fgimple`.
